from __future__ import annotations

import dataclasses
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from apt_scout.cluster.fingerprints import fingerprints
from apt_scout.models import Listing, Occupancy

# Members are ordered by "how much we trust this source's data" for
# canonical-field pooling and for tie-breaking cluster ordering. Sources not
# in this list (future adapters) sort after every known one.
_SOURCE_PRIORITY = ["yad2", "onmap", "komo", "homeless", "fb_marketplace", "prog"]

_MIN_SHARED_WEAK_FINGERPRINTS = 2

# A phone number shared by more listings than any one apartment plausibly
# has ads is an agency switchboard, not an identity signal: merging on it
# would collapse an agency's whole inventory into one mega-cluster (and one
# notification would permanently mark every member notified). Above this
# many listings in a single run, a phone: key is ignored as a merge signal;
# exturl: keys are unaffected - a listing URL can't be a switchboard.
_MAX_PHONE_CLUSTER = 4


@dataclass
class Cluster:
    """One apartment, deduplicated across every source that advertised it."""

    cluster_id: str
    members: list[Listing]
    canonical: Listing
    sources: list[str]


class _UnionFind:
    """Plain union-find with path compression over listing indices."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]
            item = self._parent[item]
        return item

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_a] = root_b


def _source_rank(source: str) -> int:
    try:
        return _SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(_SOURCE_PRIORITY)


def _order_members(members: list[Listing]) -> list[Listing]:
    return sorted(members, key=lambda m: (_source_rank(m.source), m.stable_id()))


def _pool_photos(ordered_members: list[Listing]) -> list[str]:
    """First member (in priority order) with a non-empty photos list wins.

    A never-None field like ``photos`` defaults to ``[]``, so "first
    non-None" would let a top-priority member with no photos beat a
    lower-priority member that actually has some. Pick the first non-empty
    list instead, falling back to [] only when nobody has photos.
    """
    for member in ordered_members:
        if member.photos:
            return list(member.photos)
    return []


def _pool_occupancy(ordered_members: list[Listing]) -> Occupancy:
    """Safety first: ROOMMATES beats everything, then priority order.

    ``occupancy`` defaults to UNSURE, so "first non-None" would let a
    top-priority UNSURE hide a lower-priority member's definite value -
    in the worst case losing a ROOMMATES detection and letting a
    roommates-ad slip past the roommates filter. So: if ANY member was
    detected as ROOMMATES, the cluster is ROOMMATES, full stop - one
    roommate-ad detection poisons the whole cluster. Otherwise take the
    first non-UNSURE value in priority order, falling back to UNSURE only
    if every member is UNSURE.
    """
    if any(member.occupancy == Occupancy.ROOMMATES for member in ordered_members):
        return Occupancy.ROOMMATES
    for member in ordered_members:
        if member.occupancy != Occupancy.UNSURE:
            return member.occupancy
    return Occupancy.UNSURE


def _pool_sublet(ordered_members: list[Listing]) -> bool:
    """Safety first, same as occupancy: any member flagged sublet wins.

    ``is_sublet`` defaults to False, so "first non-None" would let a
    top-priority False hide a lower-priority member's True detection - in
    the worst case letting a sublet ad slip past the sublet filter. So: if
    ANY member was flagged as a sublet, the cluster is a sublet, full stop.
    """
    return any(member.is_sublet for member in ordered_members)


def _pool_canonical(ordered_members: list[Listing]) -> Listing:
    """Build a synthetic Listing whose fields come from the first (highest
    priority) member that has a non-None value for that field.

    ``photos``, ``occupancy``, and ``is_sublet`` never take the value None
    (they default to ``[]`` / ``Occupancy.UNSURE`` / ``False``), so "first
    non-None" can't distinguish "unset" from "explicitly this value" for
    them - they get dedicated pooling rules instead. See _pool_photos,
    _pool_occupancy, and _pool_sublet.
    """
    values: dict[str, object] = {}
    for field in dataclasses.fields(Listing):
        if field.name == "photos":
            values[field.name] = _pool_photos(ordered_members)
            continue
        if field.name == "occupancy":
            values[field.name] = _pool_occupancy(ordered_members)
            continue
        if field.name == "is_sublet":
            values[field.name] = _pool_sublet(ordered_members)
            continue
        if field.name == "sources":
            # Populated by the pipeline from cluster.sources, not pooled here.
            continue
        value = None
        for member in ordered_members:
            candidate = getattr(member, field.name)
            if candidate is not None:
                value = candidate
                break
        if isinstance(value, list):
            value = list(value)
        values[field.name] = value
    return Listing(**values)  # type: ignore[arg-type]


def _cluster_id(members: list[Listing]) -> str:
    """sha1 of the lexicographically smallest member stable_id.

    Depends only on the *set* of members, not on input order, so the same
    cluster gets the same id regardless of how listings were fed in.
    """
    smallest = min(member.stable_id() for member in members)
    return hashlib.sha1(smallest.encode()).hexdigest()


class ClusterEngine:
    """Cross-source deduplication: same apartment, one cluster."""

    def cluster(self, listings: list[Listing], salt: str) -> list[Cluster]:
        count = len(listings)
        union_find = _UnionFind(count)
        fingerprint_sets = [fingerprints(listing, salt) for listing in listings]

        strong_index: dict[str, list[int]] = defaultdict(list)
        weak_index: dict[str, list[int]] = defaultdict(list)
        for index, fp in enumerate(fingerprint_sets):
            for key in set(fp["strong"]):
                strong_index[key].append(index)
            for key in set(fp["weak"]):
                weak_index[key].append(index)

        # Any shared strong fingerprint merges outright - except a phone
        # shared too widely to be one apartment's (see _MAX_PHONE_CLUSTER).
        # Other signals still apply to those listings.
        for key, indices in strong_index.items():
            if key.startswith("phone:") and len(indices) > _MAX_PHONE_CLUSTER:
                continue
            for other in indices[1:]:
                union_find.union(indices[0], other)

        # Weak fingerprints only merge once two *distinct* keys agree.
        shared_weak_counts: dict[tuple[int, int], int] = defaultdict(int)
        for indices in weak_index.values():
            for a, b in combinations(sorted(set(indices)), 2):
                shared_weak_counts[(a, b)] += 1
        for (a, b), shared in shared_weak_counts.items():
            if shared >= _MIN_SHARED_WEAK_FINGERPRINTS:
                union_find.union(a, b)

        groups: dict[int, list[int]] = defaultdict(list)
        for index in range(count):
            groups[union_find.find(index)].append(index)

        clusters: list[Cluster] = []
        for indices in groups.values():
            members = _order_members([listings[i] for i in indices])
            sources: list[str] = []
            seen_sources: set[str] = set()
            for member in members:
                if member.source not in seen_sources:
                    seen_sources.add(member.source)
                    sources.append(member.source)
            clusters.append(
                Cluster(
                    cluster_id=_cluster_id(members),
                    members=members,
                    canonical=_pool_canonical(members),
                    sources=sources,
                )
            )
        return clusters
