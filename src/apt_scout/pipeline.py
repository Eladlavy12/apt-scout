from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .filters import Filters
from .health import HealthTracker
from .models import Listing
from .state import StateStore

Enricher = Callable[[Listing], Listing]


@dataclass
class RunReport:
    fetched: int = 0
    new: int = 0
    matched: int = 0
    notified: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    listings: list[Listing] = field(default_factory=list)


def run_pipeline(
    adapters: Iterable,
    fetcher: Any,
    sources_config: dict,
    filters: Filters,
    store: StateStore,
    notifier: Any,
    enrichers: list[Enricher] | None = None,
    now: datetime | None = None,
) -> RunReport:
    """Fetch, enrich, filter, and notify for one scheduled run.

    Every adapter is isolated: a source that fails or raises is recorded and
    skipped, never allowed to end the run. A run in which one source breaks is
    a degraded success, not a failure.
    """
    now = now or datetime.now(timezone.utc)
    enrichers = enrichers or []
    health = HealthTracker(store)
    report = RunReport()

    collected: list[Listing] = []
    for adapter in adapters:
        config = sources_config.get(adapter.name, {})
        if not config.get("enabled", True):
            continue
        try:
            result = adapter.fetch(fetcher, config, since=None)
        except Exception as exc:  # noqa: BLE001 - isolation is the whole point
            message = f"{type(exc).__name__}: {exc}"
            report.errors[adapter.name] = message
            health.record(adapter.name, ok=False, error=message)
            continue

        if result.error:
            report.errors[adapter.name] = result.error
            health.record(adapter.name, ok=False, error=result.error)
            continue

        health.record(adapter.name, ok=True)
        collected.extend(result.listings)

    report.fetched = len(collected)

    # The same advertisement can arrive twice in one run (overlapping pages,
    # or two adapters for one site). First occurrence wins.
    deduped: list[Listing] = []
    ids_this_run: set[str] = set()
    for listing in collected:
        listing_id = listing.stable_id()
        if listing_id in ids_this_run:
            continue
        ids_this_run.add(listing_id)
        deduped.append(listing)

    already_notified = store.notified_ids()
    first_seen = store.first_seen()

    new_seen: dict[str, str] = {}
    enriched: list[Listing] = []
    for listing in deduped:
        listing_id = listing.stable_id()
        if listing_id in first_seen:
            stored = first_seen[listing_id]
            if stored:
                try:
                    listing.first_seen_at = datetime.fromisoformat(stored)
                except ValueError:
                    pass  # unreadable timestamp is not worth failing a run
        else:
            listing.first_seen_at = now
            new_seen[listing_id] = now.isoformat()
            report.new += 1

        # Enrichers are isolated like adapters: one bad listing (or one flaky
        # enrichment service) degrades that listing, never the whole run.
        for enrich in enrichers:
            try:
                listing = enrich(listing)
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                report.errors.setdefault(
                    f"enrich:{listing_id}", f"{type(exc).__name__}: {exc}"
                )
        enriched.append(listing)

        if not filters.matches(listing):
            continue
        report.matched += 1

        if listing_id in already_notified:
            continue
        if notifier.send_listing(listing):
            # Persisted immediately: a crash later in the loop must never
            # un-record an alert that was already delivered.
            store.mark_notified([listing_id])
            report.notified += 1

    report.listings = enriched

    store.record_seen(new_seen)

    return report
