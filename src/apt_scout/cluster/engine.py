from __future__ import annotations

import dataclasses
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from apt_scout.cluster.fingerprints import fingerprints
from apt_scout.models import Listing

# Members are ordered by "how much we trust this source's data" for
# canonical-field pooling and for tie-breaking cluster ordering. Sources not
# in this list (future adapters) sort after every known one.
_SOURCE_PRIORITY = ["yad2", "onmap", "komo", "homeless", "fb_marketplace", "prog"]

_MIN_SHARED_WEAK_FINGERPRINTS = 2


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


def _pool_canonical(ordered_members: list[Listing]) -> Listing:
    """Build a synthetic Listing whose fields come from the first (highest
    priority) member that has a non-None value for that field."""
    values: dict[str, object] = {}
    for field in dataclasses.fields(Listing):
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

        # Any shared strong fingerprint merges outright.
        for indices in strong_index.values():
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
            clusters.append(
                Cluster(
                    cluster_id=_cluster_id(members),
                    members=members,
                    canonical=_pool_canonical(members),
                    sources=[member.source for member in members],
                )
            )
        return clusters
