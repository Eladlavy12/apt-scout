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

    already_notified = store.notified_ids()
    seen = store.seen_ids()

    newly_notified: list[str] = []
    enriched: list[Listing] = []
    for listing in collected:
        listing_id = listing.stable_id()
        if listing_id not in seen:
            listing.first_seen_at = now
            report.new += 1

        for enrich in enrichers:
            listing = enrich(listing)
        enriched.append(listing)

        if not filters.matches(listing):
            continue
        report.matched += 1

        if listing_id in already_notified:
            continue
        if notifier.send_listing(listing):
            newly_notified.append(listing_id)
            report.notified += 1

    report.listings = enriched

    store.mark_seen(item.stable_id() for item in collected)
    if newly_notified:
        store.mark_notified(newly_notified)

    return report
