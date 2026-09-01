from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .cluster.engine import Cluster, ClusterEngine
from .filters import Filters
from .health import HealthTracker
from .models import Listing
from .state import StateStore

Enricher = Callable[[Listing], Listing]

# Notifications are exactly-once and pooled at the cluster level, not the
# per-listing level: one alert per apartment regardless of how many sources
# advertised it. This caps how many cluster alerts go out in a single run so
# a burst of new listings never floods the chat; the rest wait for the next
# run rather than being dropped.
MAX_ALERTS_PER_RUN = 12


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
    gate: Any | None = None,
    cluster_salt: str = "",
    max_alerts_per_run: int = MAX_ALERTS_PER_RUN,
) -> RunReport:
    """Fetch, enrich, cluster, filter, and notify for one scheduled run.

    Every adapter is isolated: a source that fails or raises is recorded and
    skipped, never allowed to end the run. A run in which one source breaks is
    a degraded success, not a failure.

    When a `gate` (a `CadenceGate`) is supplied, a source whose cadence isn't
    due yet is skipped entirely before it is fetched: no health record, no
    error, and no effect on the portal-build decision - it simply didn't run
    this cycle. `gate.mark_ran` is called for every source that *does* fetch
    without raising (whether it returns listings or an error result), so a
    persistently failing source is retried no more often than its cadence.

    Listings are clustered (cross-source dedup) after enrichment and before
    filtering: filtering, notification, and the portal all operate on one
    canonical listing per apartment, never on a raw per-source post. A
    cluster counts as already notified if ANY member's stable id was
    previously notified - the pre-clustering, per-listing state - so
    existing notified-state keeps suppressing alerts across the migration.
    After a confirmed send, every member id is marked notified at once.
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

        cadence_hours = config.get("cadence_hours")
        if gate is not None and cadence_hours:
            if not gate.is_due(adapter.name, cadence_hours, now):
                continue

        try:
            result = adapter.fetch(fetcher, config, since=None)
        except Exception as exc:  # noqa: BLE001 - isolation is the whole point
            message = f"{type(exc).__name__}: {exc}"
            report.errors[adapter.name] = message
            health.record(adapter.name, ok=False, error=message)
            continue

        if gate is not None:
            gate.mark_ran(adapter.name, now)

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

    clusters = ClusterEngine().cluster(enriched, cluster_salt)

    canonical_listings: list[Listing] = []
    candidates: list[Cluster] = []
    for cluster in clusters:
        canonical = cluster.canonical
        canonical.sources = list(cluster.sources)

        # The canonical's first-seen must be the earliest of any member's,
        # not whichever field the pooling happened to pick - otherwise a
        # long-known listing that just got cross-posted to a new source
        # could show up with a dishonest "NEW" badge.
        member_first_seen = [
            member.first_seen_at
            for member in cluster.members
            if member.first_seen_at is not None
        ]
        if member_first_seen:
            canonical.first_seen_at = min(member_first_seen)

        canonical_listings.append(canonical)

        if not filters.matches(canonical):
            continue
        report.matched += 1

        member_ids = [member.stable_id() for member in cluster.members]
        if any(member_id in already_notified for member_id in member_ids):
            # Suppression must self-heal the whole cluster's notified state,
            # not just the member id that happened to trigger it - otherwise
            # once the originally-notified source's listing expires and
            # drops out of future fetches, a surviving member forms a fresh,
            # unsuppressed cluster and fires a duplicate alert.
            unrecorded = [mid for mid in member_ids if mid not in already_notified]
            if unrecorded:
                store.mark_notified(unrecorded)
                already_notified.update(unrecorded)
            continue
        candidates.append(cluster)

    to_send, overflow = candidates[:max_alerts_per_run], candidates[max_alerts_per_run:]

    for cluster in to_send:
        if notifier.send_listing(cluster.canonical):
            # Persisted immediately: a crash later in the loop must never
            # un-record an alert that was already delivered.
            store.mark_notified([member.stable_id() for member in cluster.members])
            report.notified += 1

    if overflow:
        notifier.send_text(f"+ עוד {len(overflow)} דירות תואמות — ראו בפורטל")

    report.listings = canonical_listings

    store.record_seen(new_seen)

    return report
