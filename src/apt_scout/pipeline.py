from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .cluster.engine import Cluster, ClusterEngine
from .filters import Filters
from .health import HealthTracker
from .models import Listing, Occupancy
from .state import StateStore

Enricher = Callable[[Listing], Listing]

# State key for the carry-forward cache: each source's latest enriched
# listings, persisted so a cadence-skipped source still contributes to
# clustering and the portal (see run_pipeline's docstring).
PORTAL_CACHE = "portal_cache"

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
    # Enabled sources whose fetch was actually attempted this run (whether it
    # succeeded, errored, or raised). A cadence-skipped source is NOT in here;
    # should_build_portal uses that to tell "nothing ran" from "nothing found".
    attempted: list[str] = field(default_factory=list)


def _serialise_listing(listing: Listing) -> dict:
    """Listing -> JSON-safe dict for the carry-forward cache."""
    data = dataclasses.asdict(listing)
    for key in ("posted_at", "first_seen_at"):
        value = data[key]
        data[key] = value.isoformat() if value is not None else None
    data["occupancy"] = listing.occupancy.value
    return data


def _deserialise_listing(data: dict) -> Listing:
    """Inverse of _serialise_listing; raises on a malformed cache entry."""
    values = dict(data)
    for key in ("posted_at", "first_seen_at"):
        raw = values.get(key)
        values[key] = datetime.fromisoformat(raw) if raw else None
    values["occupancy"] = Occupancy(values.get("occupancy", Occupancy.UNSURE.value))
    return Listing(**values)


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

    A cadence-skipped source must not vanish from the portal, though: the
    portal is rebuilt from this run's listings only, so a 6h-cadence source
    would otherwise disappear 5 runs out of 6. Each run persists every
    successfully-fetched source's enriched listings into the `portal_cache`
    state, and restores the cached listings of any source the gate skipped,
    feeding them into clustering alongside the fresh ones. Restored listings
    are not re-fetched, re-enriched, or re-counted: they do not contribute to
    `report.fetched`/`report.new` and never re-stamp seen state.

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
    gate_skipped: list[str] = []
    fetched_ok: set[str] = set()
    for adapter in adapters:
        config = sources_config.get(adapter.name, {})
        if not config.get("enabled", True):
            continue

        cadence_hours = config.get("cadence_hours")
        if gate is not None and cadence_hours:
            if not gate.is_due(adapter.name, cadence_hours, now):
                gate_skipped.append(adapter.name)
                continue

        report.attempted.append(adapter.name)
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
        fetched_ok.add(adapter.name)
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

    # Carry-forward cache: replace only the sources that actually fetched
    # this run; a skipped (or errored) source keeps its previous entry.
    cache = store.load(PORTAL_CACHE, {})
    for source in fetched_ok:
        cache[source] = [
            _serialise_listing(item) for item in enriched if item.source == source
        ]
    store.save(PORTAL_CACHE, cache)

    # Restore cached listings for cadence-skipped sources. They are already
    # enriched and already seen (their seen state was stamped the run they
    # were fetched), so they merge in only AFTER the fetched/new counting -
    # they never enter `new_seen`, so they can't inflate `new` or re-stamp
    # seen state.
    restored: list[Listing] = []
    for source in gate_skipped:
        for raw in cache.get(source, []):
            try:
                restored.append(_deserialise_listing(raw))
            except (TypeError, ValueError, KeyError):
                continue  # one corrupt cache entry must not fail the run

    clusters = ClusterEngine().cluster(enriched + restored, cluster_salt)

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
