from __future__ import annotations

import json
import math
from pathlib import Path

from ..geo.polygon import PolygonIndex
from ..models import Listing
from ..neighborhoods.knowledge import KnowledgeBase
from ..state import StateStore

CACHE = "neighborhoods"
GEOJSON_FILE = "neighborhoods.geojson"
KNOWLEDGE_FILE = "neighborhoods.json"


def load_neighborhood_data(data_dir: Path) -> tuple[PolygonIndex, KnowledgeBase]:
    data_dir = Path(data_dir)
    geojson = json.loads((data_dir / GEOJSON_FILE).read_text(encoding="utf-8"))
    return PolygonIndex.from_geojson(geojson), KnowledgeBase.load(data_dir / KNOWLEDGE_FILE)


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


class NeighborhoodEnricher:
    """Assign a knowledge-base neighborhood id to a listing.

    Coordinates win (point-in-polygon, city polygons as fallback); a
    listing without coordinates falls back to an alias found in its address
    or title. Only geometry results are cached (hits AND misses): a text
    guess is microseconds to recompute, and caching it would let a stale
    guess outrank real coordinates forever once the geocoder supplies them
    on a later run, since the cache is consulted before the geometry
    branch. For the same reason, a text hit sets `listing.neighborhood` but
    never overwrites `listing.city` — only a polygon (which sits inside a
    single city by construction) is trusted enough to correct a
    mislabelled border street.
    """

    def __init__(self, store: StateStore, index: PolygonIndex, knowledge: KnowledgeBase) -> None:
        self._store = store
        self._index = index
        self._knowledge = knowledge
        self._cache: dict[str, str | None] = store.load(CACHE, {})

    def __call__(self, listing: Listing) -> Listing:
        if listing.neighborhood is not None:
            return listing
        key = listing.stable_id()
        if key in self._cache:
            cached = self._cache[key]
            if cached is None or cached in self._knowledge:
                # Only geometry results are ever cached, so a cached value
                # is always a geometry result.
                self._apply(listing, cached, from_geometry=True)
                return listing

        if _finite(listing.lat) and _finite(listing.lon):
            found = self._index.lookup(listing.lat, listing.lon)
            if found is not None and found not in self._knowledge:
                found = None
            self._remember(key, found)
            self._apply(listing, found, from_geometry=True)
        else:
            found = self._knowledge.match_in_text(listing.address_text, None)
            if found is None:
                found = self._knowledge.match_in_text(listing.title, None)
            self._apply(listing, found, from_geometry=False)
        return listing

    def _apply(self, listing: Listing, nid: str | None, from_geometry: bool) -> None:
        listing.neighborhood = nid
        if nid is None or not from_geometry:
            return
        profile = self._knowledge.get(nid)
        if profile is not None:
            # The polygon knows better than the source which city a border
            # street belongs to. A text guess does not get this trust.
            listing.city = profile.city

    def _remember(self, key: str, nid: str | None) -> None:
        self._cache[key] = nid
        self._store.save(CACHE, self._cache)
