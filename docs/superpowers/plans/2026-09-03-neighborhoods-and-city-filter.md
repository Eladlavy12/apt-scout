# Neighborhood Intelligence and City Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every listing gets a canonical city and a neighborhood id; each neighborhood has a curated consensus profile (reputation tier, summary, pros, cons, tags); the user can filter by city and exclude neighborhoods in the portal and for Telegram alerts; each card shows the profile and a Street View link.

**Architecture:** Pure-Python point-in-polygon over a committed GeoJSON of OpenStreetMap neighborhood boundaries (plus city boundaries as fallback) assigns `Listing.neighborhood`; a hand-curated `data/neighborhoods.json` holds the profiles; `Filters` gains `cities` and `excluded_neighborhoods`; the portal joins profile data client-side. No new dependencies, no runtime AI, no paid imagery.

**Tech Stack:** Python 3.11+, dataclasses, pytest; vanilla JS (DOM-only, no innerHTML); Overpass API (build-time only, via `httpx` in a script).

Spec: `docs/superpowers/specs/2026-09-03-neighborhoods-and-city-filter-design.md`.

**Spec amendments decided while planning (verified against live data on 2026-09-03):**
- Boundary source is OpenStreetMap for all three cities (the Tel Aviv municipality's ArcGIS layer id could not be verified, and OSM already carries what looks like the municipal import: ~60 `place=suburb` polygons within 5 km). Givatayim has only two OSM neighborhood polygons, so the GeoJSON also carries the three **city boundaries** (`admin_level=8`) as features with `"kind": "city"`; the lookup tries neighborhood features first, then city features, so a Givatayim listing outside Borochov/City resolves to the city-level entry `givatayim`. City-level entries are ordinary knowledge-base entries.
- Real distinct city strings observed in `state/portal_cache.json`: `תל אביב יפו`, `תל אביב - יפו`, `תל אביב, TA`, `Tel Aviv-Yafo`, `Tel Aviv`, `רמת גן`, `גבעתיים`, `חולון`, `חולון, TA`, `בת ים`, `אזור`, plus far cities from fb_marketplace. The normaliser must strip a trailing `, XX` region code.

## Global Constraints

- Python `>=3.11`; dependencies stay `httpx>=0.27`, `beautifulsoup4>=4.12` only (no shapely, no geopandas).
- Adapters and enrichers never raise; missing values are `None`; filters fail open on unknown values.
- Portal JS is DOM-only: `textContent` / `createElement`, never `innerHTML`; every URL passes `safeHttpUrl`.
- `PUBLIC_FIELDS` is the only path to the published portal; nothing new with PII.
- Canonical city strings, exactly: `"תל אביב יפו"`, `"גבעתיים"`, `"רמת גן"`.
- Reputation enum, exactly: `sought_after`, `solid`, `mixed`, `weak`.
- Tag vocabulary, exactly: `quiet`, `nightlife`, `family`, `young`, `beach`, `green`, `light_rail`, `renewal`, `old_buildings`, `noisy`, `parking_hard`, `expensive`, `value`, `religious`, `industrial_edge`.
- `data/neighborhoods.geojson` ≤ 300 KB.
- Run tests with the venv interpreter: `C:\Github\Apt-scout\.venv\Scripts\python.exe -m pytest` (there is no `python` on PATH; PowerShell 5.1, no `&&`).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Hebrew in source files is fine (all files UTF-8); do not `print` Hebrew from Python on this Windows console (cp1252) — use `ascii()` or write to a file.

## File Structure

| Path | Responsibility |
|---|---|
| `src/apt_scout/enrich/city.py` | `normalise_city()` and `CANONICAL_CITIES` (create) |
| `src/apt_scout/geo/__init__.py`, `src/apt_scout/geo/polygon.py` | point-in-polygon and `PolygonIndex` (create) |
| `src/apt_scout/neighborhoods/__init__.py`, `src/apt_scout/neighborhoods/knowledge.py` | `KnowledgeBase` loader, validation, name matching, public projection (create) |
| `src/apt_scout/enrich/neighborhood.py` | `NeighborhoodEnricher` (create) |
| `src/apt_scout/enrich/pipeline_enrichers.py` | wire city normalisation and neighborhood steps (modify) |
| `src/apt_scout/models.py` | `Listing.neighborhood` (modify) |
| `src/apt_scout/cluster/engine.py` | pool `neighborhood` (modify) |
| `src/apt_scout/filters.py` | `cities`, `excluded_neighborhoods` (modify) |
| `src/apt_scout/notify/commands.py`, `src/apt_scout/notify/telegram.py` | commands and alert line (modify) |
| `src/apt_scout/portal/builder.py`, `assets/index.html`, `assets/app.js`, `assets/style.css` | publish profiles, chips, card panel, Street View link (modify) |
| `src/apt_scout/__main__.py` | pass `repo_root / "data"` into enrichers and builder (modify) |
| `scripts/build_neighborhoods_geojson.py` | one-off Overpass download + simplify (create) |
| `data/neighborhoods.geojson`, `data/neighborhoods.json` | committed data (create) |
| `docs/neighborhoods-sources.md` | research provenance (create) |
| `tests/test_city.py`, `tests/test_polygon.py`, `tests/test_knowledge_base.py`, `tests/test_neighborhood_enricher.py` | new tests (create); existing test files extended |

---

### Task 1: City normalisation

**Files:**
- Create: `src/apt_scout/enrich/city.py`
- Modify: `src/apt_scout/enrich/pipeline_enrichers.py`
- Test: `tests/test_city.py`, `tests/test_enrichers.py`

**Interfaces:**
- Produces: `CANONICAL_CITIES: tuple[str, str, str] = ("תל אביב יפו", "גבעתיים", "רמת גן")`; `normalise_city(text: str | None) -> str | None`; enricher step `_normalise_city_step(listing) -> Listing` inserted after `_fill_from_text` in `build_enrichers`.

- [ ] **Step 1: Write the failing tests**

`tests/test_city.py`:

```python
import pytest

from apt_scout.enrich.city import CANONICAL_CITIES, normalise_city

TEL_AVIV, GIVATAYIM, RAMAT_GAN = CANONICAL_CITIES


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("תל אביב יפו", TEL_AVIV),
        ("תל אביב - יפו", TEL_AVIV),
        ("תל אביב-יפו", TEL_AVIV),
        ("תל-אביב", TEL_AVIV),
        ("תל אביב", TEL_AVIV),
        ("  תל אביב, TA ", TEL_AVIV),
        ('ת"א', TEL_AVIV),
        ("יפו", TEL_AVIV),
        ("Tel Aviv-Yafo", TEL_AVIV),
        ("Tel Aviv", TEL_AVIV),
        ("tel aviv yafo", TEL_AVIV),
        ("גבעתיים", GIVATAYIM),
        ("Givatayim", GIVATAYIM),
        ("Giv'atayim", GIVATAYIM),
        ("רמת גן", RAMAT_GAN),
        ("רמת-גן", RAMAT_GAN),
        ("Ramat Gan", RAMAT_GAN),
        ("ramat-gan", RAMAT_GAN),
    ],
)
def test_maps_variants_to_the_canonical_name(raw, expected):
    assert normalise_city(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "חולון", "בת ים", "Jerusalem", "ירושלים, JM"])
def test_unknown_cities_return_none(raw):
    assert normalise_city(raw) is None


def test_canonical_names_are_fixed_points():
    for name in CANONICAL_CITIES:
        assert normalise_city(name) == name
```

Append to `tests/test_enrichers.py`:

```python
class TestCityNormalisation:
    def test_rewrites_a_variant_to_the_canonical_city(self, tmp_path):
        result = enrich(base(city="Tel Aviv-Yafo", lat=32.07, lon=34.79), tmp_path)
        assert result.city == "תל אביב יפו"

    def test_leaves_an_unknown_city_untouched(self, tmp_path):
        result = enrich(base(city="חולון", lat=32.02, lon=34.77), tmp_path)
        assert result.city == "חולון"

    def test_leaves_a_missing_city_missing(self, tmp_path):
        result = enrich(base(city=None, lat=32.07, lon=34.79), tmp_path)
        assert result.city is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_city.py tests/test_enrichers.py -q`
Expected: `ModuleNotFoundError: No module named 'apt_scout.enrich.city'` (collection error).

- [ ] **Step 3: Implement `enrich/city.py`**

```python
from __future__ import annotations

import re

# The three cities the user cares about, in preference order. Every other
# city keeps whatever string the source supplied.
CANONICAL_CITIES = ("תל אביב יפו", "גבעתיים", "רמת גן")

# Sources spell the same city many ways (hyphens, Yafo suffix, English,
# a trailing ", TA" region code from Facebook Marketplace). Everything is
# lower-cased, punctuation-stripped and whitespace-collapsed before lookup,
# so this table lists the *normalised* spellings.
_ALIASES = {
    "תל אביב יפו": CANONICAL_CITIES[0],
    "תל אביב": CANONICAL_CITIES[0],
    "תא": CANONICAL_CITIES[0],
    "יפו": CANONICAL_CITIES[0],
    "tel aviv yafo": CANONICAL_CITIES[0],
    "tel aviv jaffa": CANONICAL_CITIES[0],
    "tel aviv": CANONICAL_CITIES[0],
    "גבעתיים": CANONICAL_CITIES[1],
    "givatayim": CANONICAL_CITIES[1],
    "givataim": CANONICAL_CITIES[1],
    "רמת גן": CANONICAL_CITIES[2],
    "ramat gan": CANONICAL_CITIES[2],
}

_REGION_SUFFIX = re.compile(r",\s*[A-Za-z]{1,3}\s*$")
_PUNCTUATION = re.compile(r"[\-\u2013\u2014'\"\u05f3\u05f4.]+")
_WHITESPACE = re.compile(r"\s+")


def _key(text: str) -> str:
    cleaned = _REGION_SUFFIX.sub("", text)
    cleaned = _PUNCTUATION.sub(" ", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip().lower()


def normalise_city(text: str | None) -> str | None:
    """Map a source's city spelling to one of CANONICAL_CITIES, else None."""
    if not text:
        return None
    return _ALIASES.get(_key(text))
```

Note: `_PUNCTUATION` turns `ת"א` into `ת א`, so also add `"ת א": CANONICAL_CITIES[0]` to `_ALIASES` (keep the `"תא"` entry too for inputs typed without the quote).

- [ ] **Step 4: Wire the step into `build_enrichers`**

In `src/apt_scout/enrich/pipeline_enrichers.py` add the import `from .city import normalise_city`, the step:

```python
def _normalise_city_step(listing: Listing) -> Listing:
    """Rewrite known city spellings to their canonical form.

    Only the three cities the filters know about are rewritten; anything
    else keeps the source's string so the portal can still show it.
    """
    canonical = normalise_city(listing.city)
    if canonical is not None:
        listing.city = canonical
    return listing
```

and insert `_normalise_city_step,` right after `_fill_from_text,` in the returned list.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_city.py tests/test_enrichers.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/apt_scout/enrich/city.py src/apt_scout/enrich/pipeline_enrichers.py tests/test_city.py tests/test_enrichers.py
git commit -m "feat: normalise source city names to canonical forms

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `Listing.neighborhood` field, serialisation, pooling, public projection

**Files:**
- Modify: `src/apt_scout/models.py` (after `distance_km`), `src/apt_scout/cluster/engine.py`, `src/apt_scout/portal/builder.py` (`PUBLIC_FIELDS`)
- Test: `tests/test_serialise.py`, `tests/test_cluster_engine.py`, `tests/test_portal_builder.py`

**Interfaces:**
- Produces: `Listing.neighborhood: str | None = None` (knowledge-base id). Serialise round-trips it; a legacy dict without the key deserialises to `None`. Cluster canonical takes the first member (priority order) with a non-None value. `PUBLIC_FIELDS` includes `"neighborhood"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_serialise.py` (reuse that file's existing listing helper if one exists; otherwise this standalone test):

```python
from apt_scout.models import Listing
from apt_scout.serialise import deserialise_listing, serialise_listing


def test_neighborhood_round_trips():
    original = Listing(source="yad2", source_id="9", url="https://y/9", neighborhood="florentin")
    assert deserialise_listing(serialise_listing(original)).neighborhood == "florentin"


def test_legacy_dict_without_neighborhood_deserialises_to_none():
    data = serialise_listing(Listing(source="yad2", source_id="9", url="https://y/9"))
    del data["neighborhood"]
    assert deserialise_listing(data).neighborhood is None
```

Append to `tests/test_cluster_engine.py` (use the file's existing listing factory name; if it is called `make_listing`, adapt the call):

```python
def test_canonical_takes_the_first_member_with_a_neighborhood():
    from apt_scout.cluster.engine import ClusterEngine
    from apt_scout.models import Listing

    # Fingerprints read the phone from the text (not from phone_hash), so
    # both ads carry the same number in raw_text to force a strong merge.
    a = Listing(source="yad2", source_id="1", url="https://y/1", raw_text="לפרטים 052-1234567", neighborhood=None)
    b = Listing(source="komo", source_id="2", url="https://k/2", raw_text="טל' 052-1234567", neighborhood="bavli")
    clusters = ClusterEngine().cluster([a, b], salt="s")
    assert len(clusters) == 1
    assert clusters[0].canonical.neighborhood == "bavli"
```

Append to `tests/test_portal_builder.py` inside `TestPublicDict`:

```python
    def test_publishes_the_neighborhood_id(self):
        assert listing_to_public_dict(listing(neighborhood="bavli"))["neighborhood"] == "bavli"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_serialise.py tests/test_cluster_engine.py tests/test_portal_builder.py -q`
Expected: `TypeError: Listing.__init__() got an unexpected keyword argument 'neighborhood'`.

- [ ] **Step 3: Add the field**

In `src/apt_scout/models.py`, after `distance_km: float | None = None`:

```python
    # Knowledge-base id of the neighborhood (see data/neighborhoods.json),
    # resolved from coordinates by the neighborhood enricher. None until
    # resolved, or when the point lies outside every known boundary.
    neighborhood: str | None = None
```

`serialise_listing` uses `dataclasses.asdict`, so no change there. Confirm the phone-hash check on `ClusterEngine` test: `phone_hash` shared by 2 listings is a strong fingerprint (below `_MAX_PHONE_CLUSTER`), so the two merge. `_pool_canonical`'s generic "first non-None" rule already handles `neighborhood`; no engine change is needed unless the test fails.

In `src/apt_scout/portal/builder.py`, add `"neighborhood",` to `PUBLIC_FIELDS` right after `"distance_km",`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_serialise.py tests/test_cluster_engine.py tests/test_portal_builder.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/models.py src/apt_scout/portal/builder.py tests/test_serialise.py tests/test_cluster_engine.py tests/test_portal_builder.py
git commit -m "feat: add Listing.neighborhood and publish it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Point-in-polygon index

**Files:**
- Create: `src/apt_scout/geo/__init__.py` (empty), `src/apt_scout/geo/polygon.py`
- Test: `tests/test_polygon.py`

**Interfaces:**
- Produces:
  - `point_in_ring(lat: float, lon: float, ring: list[list[float]]) -> bool` — ring is GeoJSON order `[lon, lat]`.
  - `point_in_polygon(lat, lon, polygon: list[list[list[float]]]) -> bool` — first ring outer, rest holes.
  - `class PolygonIndex` with `@classmethod from_geojson(cls, data: dict) -> PolygonIndex`, `lookup(self, lat: float, lon: float) -> str | None`, and `feature_ids(self) -> list[str]`. Features need `properties.id` (str) and optional `properties.kind` (`"city"` features are tried only after every non-city feature misses). Features with unsupported geometry or missing id are skipped.

- [ ] **Step 1: Write the failing tests**

`tests/test_polygon.py`:

```python
from apt_scout.geo.polygon import PolygonIndex, point_in_polygon, point_in_ring

# A 1x1 degree square (lat 32..33, lon 34..35), GeoJSON [lon, lat] order.
SQUARE = [[34.0, 32.0], [35.0, 32.0], [35.0, 33.0], [34.0, 33.0], [34.0, 32.0]]
HOLE = [[34.4, 32.4], [34.6, 32.4], [34.6, 32.6], [34.4, 32.6], [34.4, 32.4]]


def test_point_inside_ring():
    assert point_in_ring(32.5, 34.2, SQUARE)


def test_point_outside_ring():
    assert not point_in_ring(31.5, 34.2, SQUARE)
    assert not point_in_ring(32.5, 35.5, SQUARE)


def test_hole_excludes_points():
    assert point_in_polygon(32.2, 34.2, [SQUARE, HOLE])
    assert not point_in_polygon(32.5, 34.5, [SQUARE, HOLE])


def geojson(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def feature(fid, coords, geometry_type="Polygon", kind=None):
    props = {"id": fid}
    if kind:
        props["kind"] = kind
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": geometry_type, "coordinates": coords},
    }


def test_lookup_returns_the_containing_feature_id():
    index = PolygonIndex.from_geojson(geojson(feature("a", [SQUARE])))
    assert index.lookup(32.5, 34.5) == "a"
    assert index.lookup(30.0, 30.0) is None


def test_lookup_supports_multipolygon():
    east = [[36.0, 32.0], [37.0, 32.0], [37.0, 33.0], [36.0, 33.0], [36.0, 32.0]]
    index = PolygonIndex.from_geojson(
        geojson(feature("m", [[SQUARE], [east]], geometry_type="MultiPolygon"))
    )
    assert index.lookup(32.5, 36.5) == "m"


def test_city_features_are_only_a_fallback():
    small = [[34.4, 32.4], [34.6, 32.4], [34.6, 32.6], [34.4, 32.6], [34.4, 32.4]]
    index = PolygonIndex.from_geojson(
        geojson(feature("city", [SQUARE], kind="city"), feature("hood", [small]))
    )
    assert index.lookup(32.5, 34.5) == "hood"
    assert index.lookup(32.1, 34.1) == "city"


def test_skips_features_without_id_or_with_unsupported_geometry():
    point = {
        "type": "Feature",
        "properties": {"id": "pt"},
        "geometry": {"type": "Point", "coordinates": [34.5, 32.5]},
    }
    no_id = {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [SQUARE]},
    }
    index = PolygonIndex.from_geojson(geojson(point, no_id, feature("ok", [SQUARE])))
    assert index.feature_ids() == ["ok"]
    assert index.lookup(32.5, 34.5) == "ok"


def test_lookup_is_deterministic_on_a_shared_border():
    left = [[34.0, 32.0], [34.5, 32.0], [34.5, 33.0], [34.0, 33.0], [34.0, 32.0]]
    right = [[34.5, 32.0], [35.0, 32.0], [35.0, 33.0], [34.5, 33.0], [34.5, 32.0]]
    index = PolygonIndex.from_geojson(geojson(feature("left", [left]), feature("right", [right])))
    first = index.lookup(32.5, 34.5)
    assert first in ("left", "right")
    assert all(index.lookup(32.5, 34.5) == first for _ in range(5))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_polygon.py -q`
Expected: `ModuleNotFoundError: No module named 'apt_scout.geo'`.

- [ ] **Step 3: Implement `geo/polygon.py`**

Create an empty `src/apt_scout/geo/__init__.py`, then `src/apt_scout/geo/polygon.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

Ring = list[list[float]]  # GeoJSON order: [lon, lat]
Polygon = list[Ring]  # outer ring first, then holes


def point_in_ring(lat: float, lon: float, ring: Ring) -> bool:
    """Even-odd ray casting.

    A point exactly on a shared edge is counted on one side only, which is
    what keeps lookups on a border deterministic.
    """
    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lat: float, lon: float, polygon: Polygon) -> bool:
    if not polygon or not point_in_ring(lat, lon, polygon[0]):
        return False
    return not any(point_in_ring(lat, lon, hole) for hole in polygon[1:])


def _bbox(polygons: list[Polygon]) -> tuple[float, float, float, float]:
    lons = [pt[0] for poly in polygons for pt in poly[0]]
    lats = [pt[1] for poly in polygons for pt in poly[0]]
    return min(lats), min(lons), max(lats), max(lons)


@dataclass
class _Feature:
    id: str
    kind: str
    polygons: list[Polygon]
    bbox: tuple[float, float, float, float]

    def contains(self, lat: float, lon: float) -> bool:
        min_lat, min_lon, max_lat, max_lon = self.bbox
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            return False
        return any(point_in_polygon(lat, lon, poly) for poly in self.polygons)


class PolygonIndex:
    """Which named area contains a point.

    Neighborhood features are tried first (file order, first hit wins);
    features whose ``properties.kind`` is ``"city"`` are a fallback so a
    listing inside a city but outside every mapped neighborhood still
    resolves to the city-level profile.
    """

    def __init__(self, features: list[_Feature]) -> None:
        self._neighborhoods = [f for f in features if f.kind != "city"]
        self._cities = [f for f in features if f.kind == "city"]

    @classmethod
    def from_geojson(cls, data: dict) -> "PolygonIndex":
        features: list[_Feature] = []
        for raw in data.get("features", []):
            props = raw.get("properties") or {}
            fid = props.get("id")
            geometry = raw.get("geometry") or {}
            gtype = geometry.get("type")
            coords = geometry.get("coordinates")
            if not isinstance(fid, str) or not fid or not coords:
                continue
            if gtype == "Polygon":
                polygons = [coords]
            elif gtype == "MultiPolygon":
                polygons = list(coords)
            else:
                continue
            try:
                bbox = _bbox(polygons)
            except (IndexError, TypeError, ValueError):
                continue
            features.append(_Feature(fid, str(props.get("kind") or ""), polygons, bbox))
        return cls(features)

    def feature_ids(self) -> list[str]:
        return [f.id for f in self._neighborhoods + self._cities]

    def lookup(self, lat: float, lon: float) -> str | None:
        for group in (self._neighborhoods, self._cities):
            for feature in group:
                if feature.contains(lat, lon):
                    return feature.id
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_polygon.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/geo tests/test_polygon.py
git commit -m "feat: pure-python point-in-polygon index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Boundary download script and committed GeoJSON

**Files:**
- Create: `scripts/build_neighborhoods_geojson.py`, `data/neighborhoods.geojson`
- Test: `tests/test_neighborhood_data.py` (GeoJSON half; Task 6 adds the knowledge-base half)

**Interfaces:**
- Produces: `data/neighborhoods.geojson` — FeatureCollection; each feature has `properties.id` (ASCII slug), `properties.name` (Hebrew), `properties.name_en` (may be null), `properties.city` (canonical string), `properties.kind` (`"neighborhood"` or `"city"`), `properties.osm` (e.g. `"way/819219042"`). City features have ids `tel_aviv_yafo`, `givatayim`, `ramat_gan`. Coordinates rounded to 5 decimals; rings simplified with Ramer–Douglas–Peucker.
- Consumes: `PolygonIndex` (Task 3).

- [ ] **Step 1: Write the script**

`scripts/build_neighborhoods_geojson.py`:

```python
"""One-off: download neighborhood boundaries from OpenStreetMap and write
data/neighborhoods.geojson. Re-run only when boundaries change.

Usage (from the repo root):
    .venv\\Scripts\\python.exe scripts\\build_neighborhoods_geojson.py

Sources: OSM place=suburb/neighbourhood/quarter closed ways and relations
in a box around the reference point, plus the admin_level=8 boundary of
each of the three cities (fallback features, kind="city").
"""
from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from apt_scout.geo.polygon import PolygonIndex, point_in_ring  # noqa: E402

OVERPASS = "https://overpass-api.de/api/interpreter"
OUT = Path(__file__).resolve().parents[1] / "data" / "neighborhoods.geojson"
CENTRE = (32.056581, 34.804087)
RADIUS_KM = 6.0
BBOX = "32.00,34.74,32.13,34.87"
TOLERANCE_DEG = 0.00015

CITY_IDS = {"תל אביב יפו": "tel_aviv_yafo", "גבעתיים": "givatayim", "רמת גן": "ramat_gan"}
# OSM spells the Tel Aviv relation name with a spaced hyphen.
CITY_OSM_NAMES = {"תל אביב - יפו": "תל אביב יפו", "גבעתיים": "גבעתיים", "רמת גן": "רמת גן"}

# OSM name -> knowledge-base id. None drops the feature (non-residential or
# out of scope). Names without name:en would otherwise get Hebrew slugs.
OVERRIDES: dict[str, str | None] = {
    "מתחם חסן ערפה": None,
    "אזור תעסוקה - צומת חולון": None,
    'אוניברסיטת ת"א': None,
    "בת ים": None,
    "אונו הצעירה": None,
    "פארק דרום": "park_darom",
    "נחלת יצחק": "nahalat_yitzhak",
    "רמת החייל": "ramat_hahayal",
    "נופי ים": "nofey_yam",
    "המשתלה": "hamishtala",
    "הצפון החדש - החלק הדרומי": "new_north_south",
    "הצפון החדש - סביבת ככר המדינה": "new_north_kikar_hamedina",
    "הצפון החדש - החלק הצפוני": "new_north_north",
    "הצפון הישן - החלק הדרומי": "old_north_south",
    "הצפון הישן - החלק הצפוני": "old_north_north",
    "לב תל-אביב": "lev_tel_aviv",
    "נוה ברבור, כפר שלם מערב": "neve_barbur_kfar_shalem_west",
    "נוה אליעזר וכפר שלם מזרח": "neve_eliezer_kfar_shalem_east",
    "ביצרון ורמת ישראל": "bitzaron_ramat_israel",
    "לבנה, ידידיה": "livna_yedidya",
    "עזרא והארגזים": "ezra_haargazim",
    "צהלון ושיכוני חסכון": "tzahalon",
    "יפו העתיקה,נמל יפו": "old_jaffa",
    "מכללת יפו תל אביב ודקר": "jaffa_college_dakar",
    "נווה שאנן": "neve_shaanan",
    "גני שרונה": "sarona",
    "סיטי": "givatayim_city",
    "בורוכוב": "borochov",
}

QUERY_AREAS = f"""
[out:json][timeout:120];
(
  relation["place"~"neighbourhood|suburb|quarter"]({BBOX});
  way["place"~"neighbourhood|suburb|quarter"]({BBOX});
);
out body geom;
"""

QUERY_CITIES = """
[out:json][timeout:120];
(
  relation["boundary"="administrative"]["admin_level"="8"]["name"="תל אביב - יפו"];
  relation["boundary"="administrative"]["admin_level"="8"]["name"="גבעתיים"];
  relation["boundary"="administrative"]["admin_level"="8"]["name"="רמת גן"];
);
out body geom;
"""


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    x = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def slugify(name_en: str | None, name_he: str) -> str:
    base = unicodedata.normalize("NFKD", name_en or name_he)
    base = re.sub(r"[^A-Za-z0-9֐-׿]+", "_", base).strip("_").lower()
    return base or "unnamed"


def rdp(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Ramer-Douglas-Peucker on a closed ring; keeps at least 4 points."""
    if len(points) < 4:
        return points

    def dist(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(x - x1, y - y1)
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))

    def simplify(seg):
        if len(seg) < 3:
            return seg
        index, best = 0, 0.0
        for i in range(1, len(seg) - 1):
            d = dist(seg[i], seg[0], seg[-1])
            if d > best:
                index, best = i, d
        if best > tolerance:
            return simplify(seg[: index + 1])[:-1] + simplify(seg[index:])
        return [seg[0], seg[-1]]

    # The ring's first/last point is a poor anchor; split at the far point.
    far = max(range(1, len(points) - 1), key=lambda i: math.hypot(points[i][0] - points[0][0], points[i][1] - points[0][1]))
    simplified = simplify(points[: far + 1])[:-1] + simplify(points[far:])
    return simplified if len(simplified) >= 4 else points


def ring_from_geometry(geometry: list[dict]) -> list[list[float]]:
    return [[round(pt["lon"], 5), round(pt["lat"], 5)] for pt in geometry]


def stitch(fragments: list[list[list[float]]]) -> list[list[list[float]]]:
    """Join way fragments end-to-end into closed rings."""
    rings = []
    fragments = [f for f in fragments if len(f) >= 2]
    while fragments:
        ring = fragments.pop(0)
        progress = True
        while progress and ring[0] != ring[-1]:
            progress = False
            for frag in list(fragments):
                if frag[0] == ring[-1]:
                    ring = ring + frag[1:]
                elif frag[-1] == ring[-1]:
                    ring = ring + frag[-2::-1]
                elif frag[-1] == ring[0]:
                    ring = frag[:-1] + ring
                elif frag[0] == ring[0]:
                    ring = frag[:0:-1] + ring
                else:
                    continue
                fragments.remove(frag)
                progress = True
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def polygons(element: dict) -> list[list[list[list[float]]]]:
    """OSM element -> list of polygons (outer ring + holes each)."""
    if element["type"] == "way":
        ring = ring_from_geometry(element.get("geometry", []))
        if len(ring) < 3:
            return []
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return [[ring]]
    members = element.get("members", [])
    outers = stitch([ring_from_geometry(m["geometry"]) for m in members if m.get("role") == "outer" and m.get("geometry")])
    inners = stitch([ring_from_geometry(m["geometry"]) for m in members if m.get("role") == "inner" and m.get("geometry")])
    return [[outer] + [inner for inner in inners if point_in_ring(inner[0][1], inner[0][0], outer)] for outer in outers]


def centroid(poly: list[list[list[float]]]) -> tuple[float, float]:
    ring = poly[0]
    return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)


def fetch(query: str) -> list[dict]:
    response = httpx.post(OVERPASS, data={"data": query}, timeout=180)
    response.raise_for_status()
    return response.json()["elements"]


def feature(fid, name, name_en, city, kind, osm, polys) -> dict:
    coords = [[rdp(ring, TOLERANCE_DEG) for ring in poly] for poly in polys]
    if len(coords) == 1:
        geometry = {"type": "Polygon", "coordinates": coords[0]}
    else:
        geometry = {"type": "MultiPolygon", "coordinates": coords}
    props = {"id": fid, "name": name, "name_en": name_en, "city": city, "kind": kind, "osm": osm}
    return {"type": "Feature", "properties": props, "geometry": geometry}


def main() -> int:
    city_features = []
    for el in fetch(QUERY_CITIES):
        canonical = CITY_OSM_NAMES[el["tags"]["name"]]
        polys = polygons(el)
        city_features.append(feature(CITY_IDS[canonical], canonical, el["tags"].get("name:en"), canonical, "city", f"relation/{el['id']}", polys))
    if len(city_features) != 3:
        print("expected 3 city relations, got", len(city_features), file=sys.stderr)
        return 1
    city_index = PolygonIndex.from_geojson({"features": [
        {"properties": {"id": f["properties"]["city"]}, "geometry": f["geometry"]} for f in city_features
    ]})

    features = []
    used: dict[str, int] = {}
    for el in fetch(QUERY_AREAS):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        polys = polygons(el)
        if not polys:
            continue
        centre = centroid(polys[0])
        if haversine_km(CENTRE, centre) > RADIUS_KM:
            continue
        city = city_index.lookup(*centre)
        if city is None:
            continue  # Holon, Bnei Brak, Or Yehuda... out of scope
        if name in OVERRIDES:
            fid = OVERRIDES[name]
            if fid is None:
                continue
        else:
            fid = slugify(tags.get("name:en"), name)
        used[fid] = used.get(fid, 0) + 1
        if used[fid] > 1:
            fid = f"{fid}_{used[fid]}"
        features.append(feature(fid, name, tags.get("name:en"), city, "neighborhood", f"{el['type']}/{el['id']}", polys))

    features.sort(key=lambda f: (f["properties"]["city"], f["properties"]["id"]))
    collection = {"type": "FeatureCollection", "features": features + city_features}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    index = PolygonIndex.from_geojson(collection)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(features)} neighborhoods + 3 cities)")
    print("centre resolves to:", index.lookup(*CENTRE))
    non_ascii = [f["properties"]["id"] for f in features if not re.fullmatch(r"[a-z0-9_]+", f["properties"]["id"])]
    print("non-ascii ids:", [ascii(i) for i in non_ascii])
    for f in features:
        print(" ", f["properties"]["city"].encode("ascii", "backslashreplace").decode(), f["properties"]["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the script**

Run: `.\.venv\Scripts\python.exe scripts\build_neighborhoods_geojson.py`
Expected: `wrote ...neighborhoods.geojson (<300 KB, ~55-60 neighborhoods + 3 cities)`, `centre resolves to: orot`, `non-ascii ids: []`.

- If the size exceeds 300 KB, set `TOLERANCE_DEG = 0.0003` and re-run.
- If `expected 3 city relations` fails, run once `relation["boundary"="administrative"]["admin_level"="8"](32.00,34.74,32.13,34.87); out tags;` through Overpass, copy the exact `name` values into `QUERY_CITIES` and `CITY_OSM_NAMES`, re-run.
- If `non-ascii ids` is not empty, add an `OVERRIDES` entry per listed name with an ASCII id, re-run.
- Keep the printed id list: Task 6 needs it.

- [ ] **Step 3: Write the data test**

`tests/test_neighborhood_data.py`:

```python
import json
import re
from pathlib import Path

from apt_scout.geo.polygon import PolygonIndex

GEOJSON = Path("data/neighborhoods.geojson")
CANONICAL = {"תל אביב יפו", "גבעתיים", "רמת גן"}


def load_geojson() -> dict:
    return json.loads(GEOJSON.read_text(encoding="utf-8"))


class TestGeoJson:
    def test_is_small_enough_to_commit(self):
        assert GEOJSON.stat().st_size <= 300 * 1024

    def test_every_feature_is_well_formed(self):
        for feature in load_geojson()["features"]:
            props = feature["properties"]
            assert re.fullmatch(r"[a-z0-9_]+", props["id"]), props["id"]
            assert props["city"] in CANONICAL
            assert props["kind"] in ("neighborhood", "city")
            assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_ids_are_unique(self):
        ids = [f["properties"]["id"] for f in load_geojson()["features"]]
        assert len(ids) == len(set(ids))

    def test_has_all_three_city_fallbacks(self):
        cities = {
            f["properties"]["id"]
            for f in load_geojson()["features"]
            if f["properties"]["kind"] == "city"
        }
        assert cities == {"tel_aviv_yafo", "givatayim", "ramat_gan"}

    def test_reference_point_and_known_addresses_resolve(self):
        index = PolygonIndex.from_geojson(load_geojson())
        assert index.lookup(32.056581, 34.804087) == "orot"  # Ort Singalovski
        assert index.lookup(32.0553, 34.7702) == "florentin"
        assert index.lookup(32.0900, 34.7915) == "bavli"
        assert index.lookup(32.0720, 34.8110) == "givatayim"  # outside mapped hoods
        assert index.lookup(32.0100, 34.7600) is None  # Bat Yam: out of scope
```

- [ ] **Step 4: Run the test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_neighborhood_data.py -q`
Expected: 5 passed. If a known-address assertion fails, check what the script produced for that point (`PolygonIndex(...).lookup`), and either fix the test coordinate (it may sit in a neighbouring polygon) or add an `OVERRIDES` mapping so the ids `orot`, `florentin`, `bavli` hold — Task 6 uses those ids.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_neighborhoods_geojson.py data/neighborhoods.geojson tests/test_neighborhood_data.py
git commit -m "feat: commit OSM neighborhood boundaries for TLV, Givatayim, Ramat Gan

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Knowledge-base loader and validation

**Files:**
- Create: `src/apt_scout/neighborhoods/__init__.py` (empty), `src/apt_scout/neighborhoods/knowledge.py`
- Test: `tests/test_knowledge_base.py`

**Interfaces:**
- Produces:
  - `REPUTATIONS = ("sought_after", "solid", "mixed", "weak")`, `TAGS = frozenset({...15 tags...})`, `REQUIRED_FIELDS = ("names", "city", "reputation", "summary", "pros", "cons", "tags")`.
  - `@dataclass(frozen=True) class Neighborhood: id, names: tuple[str, ...], city: str, reputation: str, summary: str, pros: tuple[str, ...], cons: tuple[str, ...], tags: tuple[str, ...], sources: tuple[str, ...], notes: str` with `display_name -> str` (first name).
  - `class KnowledgeBase`: `@classmethod from_dict(cls, raw: dict) -> KnowledgeBase` (raises `ValueError` listing every problem), `@classmethod load(cls, path: Path) -> KnowledgeBase`, `get(id) -> Neighborhood | None`, `__contains__`, `ids() -> list[str]`, `entries() -> list[Neighborhood]`, `find_by_name(text: str) -> list[Neighborhood]` (alias equality after `normalise_text`+lower, whitespace/hyphen-insensitive), `match_in_text(text: str | None, city: str | None) -> str | None` (longest alias found as a whole word, restricted to `city` when given), `public_dict() -> dict` (id → entry minus `notes`/`sources`).
  - Validation rules: every required field present and of the right type; `names` non-empty strings; `city` in `CANONICAL_CITIES`; `reputation` in `REPUTATIONS`; `tags` ⊆ `TAGS`, ≤ 5, no duplicates; ≥ 2 pros and ≥ 2 cons; `sources` list of strings (may be empty only when `notes` explains why — enforce "non-empty" for simplicity); `id` matches `[a-z0-9_]+`.

- [ ] **Step 1: Write the failing tests**

`tests/test_knowledge_base.py`:

```python
import json

import pytest

from apt_scout.neighborhoods.knowledge import REPUTATIONS, TAGS, KnowledgeBase


def entry(**overrides) -> dict:
    base = {
        "names": ["פלורנטין", "Florentin"],
        "city": "תל אביב יפו",
        "reputation": "mixed",
        "summary": "שכונה צעירה ורועשת.",
        "pros": ["חיי לילה", "מחירים"],
        "cons": ["רעש", "לכלוך"],
        "tags": ["nightlife", "young", "noisy"],
        "sources": ["homemarket"],
    }
    base.update(overrides)
    return base


def kb(**entries) -> KnowledgeBase:
    return KnowledgeBase.from_dict(entries or {"florentin": entry()})


class TestValidation:
    def test_accepts_a_well_formed_entry(self):
        base = kb()
        assert base.get("florentin").display_name == "פלורנטין"
        assert "florentin" in base
        assert base.ids() == ["florentin"]

    @pytest.mark.parametrize(
        "bad",
        [
            {"reputation": "great"},
            {"tags": ["nightlife", "unknown_tag"]},
            {"tags": ["quiet"] * 2},
            {"tags": ["quiet", "green", "family", "beach", "value", "young"]},
            {"city": "חולון"},
            {"pros": ["only one"]},
            {"cons": []},
            {"names": []},
            {"sources": []},
            {"summary": ""},
        ],
    )
    def test_rejects_malformed_entries(self, bad):
        with pytest.raises(ValueError) as excinfo:
            kb(florentin=entry(**bad))
        assert "florentin" in str(excinfo.value)

    def test_rejects_a_missing_field(self):
        broken = entry()
        del broken["summary"]
        with pytest.raises(ValueError, match="summary"):
            kb(florentin=broken)

    def test_rejects_a_bad_id(self):
        with pytest.raises(ValueError, match="Florentin"):
            kb(Florentin=entry())

    def test_reports_every_problem_at_once(self):
        with pytest.raises(ValueError) as excinfo:
            KnowledgeBase.from_dict({"a": entry(reputation="x"), "b": entry(city="חולון")})
        message = str(excinfo.value)
        assert "a" in message and "b" in message

    def test_vocabularies_are_the_spec_values(self):
        assert REPUTATIONS == ("sought_after", "solid", "mixed", "weak")
        assert TAGS == frozenset(
            {
                "quiet", "nightlife", "family", "young", "beach", "green", "light_rail",
                "renewal", "old_buildings", "noisy", "parking_hard", "expensive", "value",
                "religious", "industrial_edge",
            }
        )


class TestLookup:
    def test_find_by_name_is_alias_and_case_insensitive(self):
        base = kb()
        assert [n.id for n in base.find_by_name("florentin")] == ["florentin"]
        assert [n.id for n in base.find_by_name(" פלורנטין ")] == ["florentin"]
        assert base.find_by_name("nowhere") == []

    def test_match_in_text_prefers_the_longest_alias(self):
        base = kb(
            neve_tzedek=entry(names=["נווה צדק"], city="תל אביב יפו"),
            neve_tzedek_north=entry(names=["נווה צדק צפון"], city="תל אביב יפו"),
        )
        assert base.match_in_text("דירה בנווה צדק צפון, קומה 2", None) == "neve_tzedek_north"
        assert base.match_in_text("דירה בנווה צדק", None) == "neve_tzedek"

    def test_match_in_text_respects_the_city_when_known(self):
        base = kb(
            tlv_hood=entry(names=["הדר"], city="תל אביב יפו"),
            rg_hood=entry(names=["הדר"], city="רמת גן"),
        )
        assert base.match_in_text("רחוב הדר 3", "רמת גן") == "rg_hood"
        assert base.match_in_text("רחוב הדר 3", None) is None  # ambiguous

    def test_match_in_text_needs_whole_words(self):
        base = kb(orot=entry(names=["אורות"], city="תל אביב יפו"))
        assert base.match_in_text("מאורות הכרך", None) is None
        assert base.match_in_text("שכונת אורות", None) == "orot"
        assert base.match_in_text(None, None) is None


class TestPublicProjection:
    def test_strips_notes_and_sources(self):
        public = kb(florentin=entry(notes="private remark")).public_dict()
        assert set(public) == {"florentin"}
        assert "notes" not in public["florentin"]
        assert "sources" not in public["florentin"]
        assert public["florentin"]["names"] == ["פלורנטין", "Florentin"]
        json.dumps(public, ensure_ascii=False)  # JSON-serialisable


def test_load_reads_a_file(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"florentin": entry()}, ensure_ascii=False), encoding="utf-8")
    assert KnowledgeBase.load(path).ids() == ["florentin"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_base.py -q`
Expected: `ModuleNotFoundError: No module named 'apt_scout.neighborhoods'`.

- [ ] **Step 3: Implement `neighborhoods/knowledge.py`**

Create empty `src/apt_scout/neighborhoods/__init__.py`, then:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..enrich.city import CANONICAL_CITIES
from ..normalise.text import normalise_text

REPUTATIONS = ("sought_after", "solid", "mixed", "weak")
TAGS = frozenset(
    {
        "quiet", "nightlife", "family", "young", "beach", "green", "light_rail",
        "renewal", "old_buildings", "noisy", "parking_hard", "expensive", "value",
        "religious", "industrial_edge",
    }
)
REQUIRED_FIELDS = ("names", "city", "reputation", "summary", "pros", "cons", "tags")
MAX_TAGS = 5
_ID = re.compile(r"[a-z0-9_]+")
_ALIAS_NOISE = re.compile(r"[\s\-–'\"׳״]+")


def _alias_key(text: str) -> str:
    return _ALIAS_NOISE.sub(" ", normalise_text(text)).strip().lower()


@dataclass(frozen=True)
class Neighborhood:
    id: str
    names: tuple[str, ...]
    city: str
    reputation: str
    summary: str
    pros: tuple[str, ...]
    cons: tuple[str, ...]
    tags: tuple[str, ...]
    sources: tuple[str, ...]
    notes: str = ""

    @property
    def display_name(self) -> str:
        return self.names[0]

    def public(self) -> dict:
        return {
            "names": list(self.names),
            "city": self.city,
            "reputation": self.reputation,
            "summary": self.summary,
            "pros": list(self.pros),
            "cons": list(self.cons),
            "tags": list(self.tags),
        }


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def _problems(nid: str, raw: object) -> list[str]:
    issues: list[str] = []
    if not _ID.fullmatch(nid):
        issues.append(f"{nid}: id must match [a-z0-9_]+")
    if not isinstance(raw, dict):
        return issues + [f"{nid}: entry must be an object"]
    for field in REQUIRED_FIELDS:
        if field not in raw:
            issues.append(f"{nid}: missing '{field}'")
    if issues:
        return issues
    if not _strings(raw["names"]) or not raw["names"]:
        issues.append(f"{nid}: names must be a non-empty list of strings")
    if raw["city"] not in CANONICAL_CITIES:
        issues.append(f"{nid}: city must be one of {list(CANONICAL_CITIES)}")
    if raw["reputation"] not in REPUTATIONS:
        issues.append(f"{nid}: reputation must be one of {list(REPUTATIONS)}")
    if not isinstance(raw["summary"], str) or not raw["summary"].strip():
        issues.append(f"{nid}: summary must be a non-empty string")
    for field in ("pros", "cons"):
        if not _strings(raw[field]) or len(raw[field]) < 2:
            issues.append(f"{nid}: {field} needs at least two strings")
    tags = raw["tags"]
    if not _strings(tags):
        issues.append(f"{nid}: tags must be a list of strings")
    else:
        unknown = sorted(set(tags) - TAGS)
        if unknown:
            issues.append(f"{nid}: unknown tags {unknown}")
        if len(tags) != len(set(tags)):
            issues.append(f"{nid}: duplicate tags")
        if len(tags) > MAX_TAGS:
            issues.append(f"{nid}: at most {MAX_TAGS} tags")
    if not _strings(raw.get("sources", [])) or not raw.get("sources"):
        issues.append(f"{nid}: sources must be a non-empty list of strings")
    if not isinstance(raw.get("notes", ""), str):
        issues.append(f"{nid}: notes must be a string")
    return issues


class KnowledgeBase:
    """Curated neighborhood profiles keyed by id (see data/neighborhoods.json)."""

    def __init__(self, entries: dict[str, Neighborhood]) -> None:
        self._entries = entries
        self._by_alias: dict[str, list[Neighborhood]] = {}
        for item in entries.values():
            for name in item.names:
                self._by_alias.setdefault(_alias_key(name), []).append(item)

    @classmethod
    def from_dict(cls, raw: dict) -> "KnowledgeBase":
        issues: list[str] = []
        entries: dict[str, Neighborhood] = {}
        for nid, value in raw.items():
            found = _problems(nid, value)
            if found:
                issues.extend(found)
                continue
            entries[nid] = Neighborhood(
                id=nid,
                names=tuple(value["names"]),
                city=value["city"],
                reputation=value["reputation"],
                summary=value["summary"],
                pros=tuple(value["pros"]),
                cons=tuple(value["cons"]),
                tags=tuple(value["tags"]),
                sources=tuple(value["sources"]),
                notes=value.get("notes", ""),
            )
        if issues:
            raise ValueError("invalid neighborhoods knowledge base:\n" + "\n".join(issues))
        return cls(entries)

    @classmethod
    def load(cls, path: Path) -> "KnowledgeBase":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def get(self, nid: str) -> Neighborhood | None:
        return self._entries.get(nid)

    def __contains__(self, nid: object) -> bool:
        return nid in self._entries

    def ids(self) -> list[str]:
        return list(self._entries)

    def entries(self) -> list[Neighborhood]:
        return list(self._entries.values())

    def find_by_name(self, text: str) -> list[Neighborhood]:
        return list(self._by_alias.get(_alias_key(text), []))

    def match_in_text(self, text: str | None, city: str | None) -> str | None:
        """Longest alias appearing as a whole word in text; None if ambiguous.

        Punctuation is treated as a word break, and a single attached Hebrew
        prefix letter ב/ל/ו/ה ("בפלורנטין", "לבבלי") is allowed before the
        alias. מ and ש are deliberately not allowed: "מאורות" must not read
        as the Orot neighborhood.
        """
        if not text:
            return None
        haystack = re.sub(r"[^\w\s]", " ", _alias_key(text))
        best: tuple[int, set[str]] = (0, set())
        for alias, items in self._by_alias.items():
            pattern = r"(?<!\S)[בלוה]?" + re.escape(alias) + r"(?!\S)"
            if not re.search(pattern, haystack):
                continue
            ids = {item.id for item in items if city is None or item.city == city}
            if not ids:
                continue
            if len(alias) > best[0]:
                best = (len(alias), ids)
            elif len(alias) == best[0]:
                best[1].update(ids)
        return next(iter(best[1])) if len(best[1]) == 1 else None

    def public_dict(self) -> dict:
        return {nid: item.public() for nid, item in self._entries.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_base.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/neighborhoods tests/test_knowledge_base.py
git commit -m "feat: neighborhood knowledge-base loader with validation

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Research and author the knowledge base

**Files:**
- Create: `data/neighborhoods.json`, `docs/neighborhoods-sources.md`
- Modify: `tests/test_neighborhood_data.py` (add the knowledge-base half)

**Interfaces:**
- Produces: one entry per GeoJSON feature id (neighborhoods and the three city-level ids), validated by `KnowledgeBase.load`. Ids used elsewhere in tests: `orot`, `florentin`, `bavli`, `givatayim`.

This is a research task, not a coding task. Do it with real reading, not from memory alone.

- [ ] **Step 1: Read the user's sources and take notes**

Fetch and read each of these (WebFetch), writing per-neighborhood notes into `docs/neighborhoods-sources.md` as you go (a `## Sources` table with a short key per source, then `## Notes by neighborhood`):

1. `https://homemarket.co.il/מדריך-השכונות-של-תל-אביב-איפה-אתם-באמת/` — key `homemarket`
2. `https://www.facebook.com/groups/secrettelaviv/posts/10161343037675943/` — key `secrettlv-2023` (public group posts may not render without login; if the fetch returns nothing usable, note "not fetchable without login" and rely on the remaining sources)
3. `https://he.quora.com/באיזו-שכונה-הכי-כדאי-לגור-בתל-אביב` — key `quora-he`
4. `https://www.facebook.com/groups/secrettelaviv/posts/10156576550365943/` — key `secrettlv-2019` (same caveat)
5. `https://www.reddit.com/r/Israel/comments/ypxcgo/how_is_it_like_to_live_in_tel_aviv/` — key `reddit-israel` (use `https://old.reddit.com/...` or append `.json` if the page does not render)
6. `https://www.diytelavivguide.com/blog/moving-to-tel-aviv/tel-aviv-neighbourhood-guide` — key `diytlv`

Then at least ten more, found with WebSearch, covering the gaps (Ramat Gan and Givatayim neighborhoods, south/east Tel Aviv neighborhoods near the reference point — Orot, Ramat HaTayasim, Neve Hen, Tel Haim, Yad Eliyahu, HaTikva, Bitzaron, Nahalat Yitzhak, Kfar Shalem, Ezra, Neve Eliezer — and the light-rail Red/Purple line status). Good candidates: Madlan neighborhood pages (`madlan.co.il/local-info/...`), Wikipedia (he) neighborhood articles, Tel Aviv municipality neighborhood profiles, Ynet/Globes/TheMarker articles on urban renewal (פינוי-בינוי) in Ramat Gan and Givatayim, Xnet / Mako city guides, Secret Tel Aviv blog posts. Give each a key and a row in the sources table.

- [ ] **Step 2: Write `data/neighborhoods.json`**

One entry per id printed by the Task 4 script (get the list with `python -c "import json;print([f['properties']['id'] for f in json.load(open('data/neighborhoods.geojson',encoding='utf-8'))['features']])"`). Follow the schema from Task 5 exactly. Rules for content:

- `names[0]` is the everyday Hebrew name (e.g. `"פלורנטין"`, not the OSM compound `"נוה ברבור, כפר שלם מערב"` — split compounds into aliases: `["כפר שלם", "נווה ברבור", "Kfar Shalem"]`). Include common misspellings (`"נוה"`/`"נווה"`, `"בבלי"`/`"באבלי"`) and the English name.
- `reputation` follows the majority view across sources; when sources conflict, choose the tier the majority supports and say so in `summary`.
- `summary`: 1–3 Hebrew sentences, concrete (what kind of buildings, who lives there, noise, what's changing).
- `pros`/`cons`: 2–5 each, short, specific to the neighborhood (not "close to everything").
- `tags`: up to 5 from the vocabulary, most defining first.
- `sources`: the keys from `docs/neighborhoods-sources.md` that informed the entry.
- City-level entries (`tel_aviv_yafo`, `givatayim`, `ramat_gan`) describe the city as a whole with reputation `solid` and a summary that says the exact neighborhood was not mapped.

Example entry (use this shape):

```json
{
  "florentin": {
    "names": ["פלורנטין", "Florentin"],
    "city": "תל אביב יפו",
    "reputation": "mixed",
    "summary": "שכונה צעירה ואמנותית בדרום העיר עם חיי לילה, בתי קפה וגרפיטי; הבנייה ישנה, הרחובות רועשים בלילה והניקיון לא אחיד. פינוי-בינוי מתקדם באזור הרחובות הדרומיים.",
    "pros": ["חיי לילה ובתי קפה במרחק הליכה", "מחירים נמוכים יחסית למרכז", "קהילה צעירה ופעילה", "קרוב לשוק לוינסקי ולנווה צדק"],
    "cons": ["רעש בלילה, במיוחד ברחובות הראשיים", "ניקיון וחזות רחוב לא אחידים", "כמעט אין חניה", "בניינים ישנים, לרוב ללא מעלית"],
    "tags": ["nightlife", "young", "noisy", "old_buildings", "renewal"],
    "sources": ["homemarket", "diytlv", "quora-he"]
  }
}
```

- [ ] **Step 3: Add the cross-check tests**

Append to `tests/test_neighborhood_data.py`:

```python
from apt_scout.neighborhoods.knowledge import KnowledgeBase

KB_PATH = Path("data/neighborhoods.json")
SOURCES_DOC = Path("docs/neighborhoods-sources.md")


class TestKnowledgeBaseFile:
    def test_loads_and_validates(self):
        assert len(KnowledgeBase.load(KB_PATH).ids()) >= 40

    def test_every_geojson_feature_has_a_profile(self):
        base = KnowledgeBase.load(KB_PATH)
        missing = [f["properties"]["id"] for f in load_geojson()["features"] if f["properties"]["id"] not in base]
        assert missing == []

    def test_profile_city_matches_the_polygon_city(self):
        base = KnowledgeBase.load(KB_PATH)
        for feature in load_geojson()["features"]:
            props = feature["properties"]
            assert base.get(props["id"]).city == props["city"], props["id"]

    def test_every_source_key_is_documented(self):
        doc = SOURCES_DOC.read_text(encoding="utf-8")
        base = KnowledgeBase.load(KB_PATH)
        undocumented = sorted({key for item in base.entries() for key in item.sources if f"`{key}`" not in doc})
        assert undocumented == []

    def test_key_ids_exist(self):
        base = KnowledgeBase.load(KB_PATH)
        for nid in ("orot", "florentin", "bavli", "givatayim", "tel_aviv_yafo", "ramat_gan"):
            assert nid in base, nid
```

Document each source in `docs/neighborhoods-sources.md` as a table row whose first cell is the key in backticks, e.g. `` | `homemarket` | HomeMarket neighborhood guide | https://... | 2026-09-03 | ``.

- [ ] **Step 4: Run the data tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_neighborhood_data.py -q`
Expected: all pass. A `ValueError` from `KnowledgeBase.load` lists every schema problem at once; fix them all, re-run.

- [ ] **Step 5: Commit**

```bash
git add data/neighborhoods.json docs/neighborhoods-sources.md tests/test_neighborhood_data.py
git commit -m "feat: curated neighborhood profiles for TLV, Givatayim, Ramat Gan

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Neighborhood enricher and runtime wiring

**Files:**
- Create: `src/apt_scout/enrich/neighborhood.py`
- Modify: `src/apt_scout/enrich/pipeline_enrichers.py`, `src/apt_scout/__main__.py`
- Test: `tests/test_neighborhood_enricher.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `PolygonIndex` (Task 3), `KnowledgeBase` (Task 5), `normalise_city` (Task 1).
- Produces:
  - `NeighborhoodEnricher(store: StateStore, index: PolygonIndex, knowledge: KnowledgeBase)` callable `(listing) -> Listing`; state key `CACHE = "neighborhoods"` mapping `stable_id -> id | None`.
  - `load_neighborhood_data(data_dir: Path) -> tuple[PolygonIndex, KnowledgeBase]`.
  - `build_enrichers(store, salt, geocoder=None, drive=None, neighborhood: Enricher | None = None)` — when `neighborhood` is None the step is skipped (keeps existing tests and callers working); `__main__.build_runtime` passes `NeighborhoodEnricher(store, *load_neighborhood_data(repo_root / "data"))`.
  - Resolution: (1) if `lat`/`lon` present: `index.lookup`; a hit also sets `listing.city` to the profile's city; (2) else `knowledge.match_in_text(address_text, city)` then `(title, city)`; (3) None. Cache semantics: results from (1) are cached including misses; results from (2)/(3) are cached only when non-None (coordinates may arrive later).

- [ ] **Step 1: Write the failing tests**

`tests/test_neighborhood_enricher.py`:

```python
from apt_scout.enrich.neighborhood import CACHE, NeighborhoodEnricher
from apt_scout.geo.polygon import PolygonIndex
from apt_scout.models import Listing
from apt_scout.neighborhoods.knowledge import KnowledgeBase
from apt_scout.state import StateStore

SQUARE = [[34.0, 32.0], [35.0, 32.0], [35.0, 33.0], [34.0, 33.0], [34.0, 32.0]]
SMALL = [[34.4, 32.4], [34.6, 32.4], [34.6, 32.6], [34.4, 32.6], [34.4, 32.4]]


def index():
    return PolygonIndex.from_geojson(
        {
            "features": [
                {"properties": {"id": "hood"}, "geometry": {"type": "Polygon", "coordinates": [SMALL]}},
                {"properties": {"id": "ramat_gan", "kind": "city"}, "geometry": {"type": "Polygon", "coordinates": [SQUARE]}},
            ]
        }
    )


def knowledge():
    def entry(name, city):
        return {
            "names": [name],
            "city": city,
            "reputation": "solid",
            "summary": "s",
            "pros": ["a", "b"],
            "cons": ["c", "d"],
            "tags": ["quiet"],
            "sources": ["x"],
        }

    return KnowledgeBase.from_dict(
        {"hood": entry("רמת חן", "רמת גן"), "ramat_gan": entry("רמת גן", "רמת גן"), "orot": entry("אורות", "תל אביב יפו")}
    )


def enricher(tmp_path):
    return NeighborhoodEnricher(StateStore(tmp_path), index(), knowledge())


def listing(**overrides) -> Listing:
    base = dict(source="yad2", source_id="1", url="https://y/1")
    base.update(overrides)
    return Listing(**base)


class TestPointInPolygon:
    def test_resolves_from_coordinates_and_fixes_the_city(self, tmp_path):
        result = enricher(tmp_path)(listing(lat=32.5, lon=34.5, city="Ramat Gan"))
        assert result.neighborhood == "hood"
        assert result.city == "רמת גן"

    def test_falls_back_to_the_city_polygon(self, tmp_path):
        assert enricher(tmp_path)(listing(lat=32.1, lon=34.1)).neighborhood == "ramat_gan"

    def test_outside_every_polygon_is_none_and_cached(self, tmp_path):
        store = StateStore(tmp_path)
        step = NeighborhoodEnricher(store, index(), knowledge())
        assert step(listing(lat=30.0, lon=30.0)).neighborhood is None
        assert store.load(CACHE, {})["yad2:1"] is None

    def test_uses_the_cache_before_geometry(self, tmp_path):
        store = StateStore(tmp_path)
        store.save(CACHE, {"yad2:1": "orot"})
        step = NeighborhoodEnricher(store, index(), knowledge())
        assert step(listing(lat=32.5, lon=34.5)).neighborhood == "orot"

    def test_ignores_a_cached_id_the_knowledge_base_no_longer_has(self, tmp_path):
        store = StateStore(tmp_path)
        store.save(CACHE, {"yad2:1": "deleted_hood"})
        step = NeighborhoodEnricher(store, index(), knowledge())
        assert step(listing(lat=32.5, lon=34.5)).neighborhood == "hood"


class TestTextFallback:
    def test_matches_an_alias_in_the_address(self, tmp_path):
        result = enricher(tmp_path)(listing(address_text="שכונת אורות, תל אביב", city="תל אביב יפו"))
        assert result.neighborhood == "orot"

    def test_matches_an_alias_in_the_title_when_the_address_has_none(self, tmp_path):
        result = enricher(tmp_path)(listing(title="דירה מקסימה ברמת חן", city="רמת גן"))
        assert result.neighborhood == "hood"

    def test_a_miss_without_coordinates_is_not_cached(self, tmp_path):
        store = StateStore(tmp_path)
        step = NeighborhoodEnricher(store, index(), knowledge())
        assert step(listing(address_text="הרצל 1")).neighborhood is None
        assert "yad2:1" not in store.load(CACHE, {})


class TestSafety:
    def test_keeps_an_existing_value(self, tmp_path):
        assert enricher(tmp_path)(listing(neighborhood="orot", lat=32.5, lon=34.5)).neighborhood == "orot"

    def test_never_raises_on_garbage_coordinates(self, tmp_path):
        result = enricher(tmp_path)(listing(lat=float("nan"), lon=34.5))
        assert result.neighborhood is None
```

Append to `tests/test_enrichers.py`:

```python
class TestNeighborhoodStep:
    def test_runs_the_neighborhood_step_when_given(self, tmp_path):
        def fake(listing):
            listing.neighborhood = "fake"
            return listing

        enrichers = build_enrichers(StateStore(tmp_path), salt="s", geocoder=StubGeocoder(), drive=StubDrive(), neighborhood=fake)
        result = base(lat=32.07, lon=34.79)
        for step in enrichers:
            result = step(result)
        assert result.neighborhood == "fake"

    def test_skips_the_neighborhood_step_when_absent(self, tmp_path):
        assert enrich(base(lat=32.07, lon=34.79), tmp_path).neighborhood is None
```

Append to `tests/test_main.py` (this file already builds a runtime against a temp repo; reuse its fixture that copies `config/` — if it has none, create the temp repo with `config/filters.json`, `config/sources.json` copied from the real ones and `data/` copied from the real `data/`):

```python
def test_runtime_wires_the_neighborhood_enricher(tmp_path):
    import shutil
    from pathlib import Path

    from apt_scout.__main__ import build_runtime
    from apt_scout.models import Listing

    shutil.copytree(Path("config"), tmp_path / "config")
    shutil.copytree(Path("data"), tmp_path / "data")
    runtime = build_runtime(tmp_path, {}, dry_run=True)
    item = Listing(source="yad2", source_id="1", url="https://y/1", lat=32.056581, lon=34.804087)
    for step in runtime.enrichers:
        item = step(item)
    assert item.neighborhood == "orot"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_neighborhood_enricher.py tests/test_enrichers.py tests/test_main.py -q`
Expected: `ModuleNotFoundError: No module named 'apt_scout.enrich.neighborhood'`.

- [ ] **Step 3: Implement `enrich/neighborhood.py`**

```python
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
    or title. Results are cached per stable id; a miss is cached only when
    it came from geometry, because a text miss may turn into a hit once the
    geocoder supplies coordinates on a later run.
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
                self._apply(listing, cached)
                return listing

        if _finite(listing.lat) and _finite(listing.lon):
            found = self._index.lookup(listing.lat, listing.lon)
            if found is not None and found not in self._knowledge:
                found = None
            self._remember(key, found)
        else:
            found = self._knowledge.match_in_text(listing.address_text, listing.city)
            if found is None:
                found = self._knowledge.match_in_text(listing.title, listing.city)
            if found is not None:
                self._remember(key, found)
        self._apply(listing, found)
        return listing

    def _apply(self, listing: Listing, nid: str | None) -> None:
        listing.neighborhood = nid
        if nid is None:
            return
        profile = self._knowledge.get(nid)
        if profile is not None:
            # The polygon knows better than the source which city a border
            # street belongs to.
            listing.city = profile.city

    def _remember(self, key: str, nid: str | None) -> None:
        self._cache[key] = nid
        self._store.save(CACHE, self._cache)
```

- [ ] **Step 4: Wire into `build_enrichers` and `build_runtime`**

`src/apt_scout/enrich/pipeline_enrichers.py`: change the signature to

```python
def build_enrichers(
    store: StateStore,
    salt: str,
    geocoder: Any = None,
    drive: Any = None,
    neighborhood: Enricher | None = None,
) -> list[Enricher]:
```

and build the list as

```python
    steps: list[Enricher] = [
        _fill_from_text,
        _normalise_city_step,
        _classify,
        _flag_sublet,
        _make_phone_hasher(salt),
        _make_geocoder_step(geocoder),
        _add_distance,
        _make_drive_step(drive),
    ]
    if neighborhood is not None:
        steps.append(neighborhood)
    return steps
```

`src/apt_scout/__main__.py`: add imports `from .enrich.neighborhood import NeighborhoodEnricher, load_neighborhood_data`, and in `build_runtime` replace `enrichers=build_enrichers(store, salt=salt),` with:

```python
        enrichers=build_enrichers(
            store,
            salt=salt,
            neighborhood=NeighborhoodEnricher(store, *load_neighborhood_data(repo_root / "data")),
        ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_neighborhood_enricher.py tests/test_enrichers.py tests/test_main.py -q`
Expected: all pass. If other `test_main.py` tests build a runtime from a temp repo that lacks `data/`, they will now fail with `FileNotFoundError`; fix them by copying `data/` in their fixture (as in the new test), not by making the loader silently optional.

- [ ] **Step 6: Commit**

```bash
git add src/apt_scout/enrich/neighborhood.py src/apt_scout/enrich/pipeline_enrichers.py src/apt_scout/__main__.py tests/test_neighborhood_enricher.py tests/test_enrichers.py tests/test_main.py
git commit -m "feat: resolve each listing's neighborhood from its coordinates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Filters — cities and excluded neighborhoods

**Files:**
- Modify: `src/apt_scout/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `CANONICAL_CITIES` (Task 1).
- Produces: `Filters.cities: list[str]` (default `list(CANONICAL_CITIES)`; empty = no restriction), `Filters.excluded_neighborhoods: list[str]` (default `[]`). `matches()` fails open on `city is None` / `neighborhood is None`. `Filters.load` of a legacy file yields the defaults. `to_dict()` includes both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_filters.py`:

```python
class TestCities:
    def test_defaults_to_the_three_cities(self):
        assert Filters().cities == ["תל אביב יפו", "גבעתיים", "רמת גן"]

    def test_rejects_a_listing_from_another_city(self):
        assert not default_filters().matches(listing(city="חולון"))

    def test_accepts_a_listed_city(self):
        assert default_filters(cities=["גבעתיים"]).matches(listing(city="גבעתיים"))
        assert not default_filters(cities=["גבעתיים"]).matches(listing(city="תל אביב יפו"))

    def test_unknown_city_fails_open(self):
        assert default_filters(cities=["גבעתיים"]).matches(listing(city=None))

    def test_empty_list_means_no_restriction(self):
        assert default_filters(cities=[]).matches(listing(city="חולון"))


class TestExcludedNeighborhoods:
    def test_defaults_to_none_excluded(self):
        assert Filters().excluded_neighborhoods == []

    def test_rejects_an_excluded_neighborhood(self):
        f = default_filters(excluded_neighborhoods=["florentin"])
        assert not f.matches(listing(neighborhood="florentin"))
        assert f.matches(listing(neighborhood="bavli"))

    def test_unknown_neighborhood_fails_open(self):
        assert default_filters(excluded_neighborhoods=["florentin"]).matches(listing(neighborhood=None))


class TestPersistence:
    def test_legacy_file_without_new_keys_loads_defaults(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps({"min_price": 4000, "max_price": 5500}), encoding="utf-8")
        loaded = Filters.load(path)
        assert loaded.cities == ["תל אביב יפו", "גבעתיים", "רמת גן"]
        assert loaded.excluded_neighborhoods == []

    def test_round_trips_the_new_fields(self, tmp_path):
        original = default_filters(cities=["רמת גן"], excluded_neighborhoods=["hatikva"])
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(original.to_dict(), ensure_ascii=False), encoding="utf-8")
        loaded = Filters.load(path)
        assert loaded.cities == ["רמת גן"]
        assert loaded.excluded_neighborhoods == ["hatikva"]
```

`listing()` in that file does not set `city`, so existing tests keep passing (fail-open); `default_filters()` there builds `Filters(**base)` and will pick up the new defaults.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_filters.py -q`
Expected: `TypeError: Filters.__init__() got an unexpected keyword argument 'cities'` / `AttributeError`.

- [ ] **Step 3: Implement**

In `src/apt_scout/filters.py`:

```python
from dataclasses import dataclass, field, fields
...
from .enrich.city import CANONICAL_CITIES
```

Add after `paused: bool = False`:

```python
    # Canonical city names (see enrich.city). Empty means no restriction;
    # a listing whose city is unknown is not disqualified.
    cities: list[str] = field(default_factory=lambda: list(CANONICAL_CITIES))
    # Knowledge-base neighborhood ids the user has ruled out.
    excluded_neighborhoods: list[str] = field(default_factory=list)
```

In `matches`, before the final `return True`:

```python
        if self.cities and listing.city is not None and listing.city not in self.cities:
            return False

        if (
            listing.neighborhood is not None
            and listing.neighborhood in self.excluded_neighborhoods
        ):
            return False
```

Check for an import cycle: `enrich/city.py` imports nothing from `apt_scout` except `re`, so `filters -> enrich.city` is safe (`enrich/__init__.py` must not import `pipeline_enrichers` eagerly; if it does, import `normalise_city` lazily inside a function instead).

- [ ] **Step 4: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass. `config/filters.json` is not touched here; `Filters.load` fills defaults, and the next Telegram-driven save will write the new keys.

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/filters.py tests/test_filters.py
git commit -m "feat: city and excluded-neighborhood alert filters

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Telegram commands and alert line

**Files:**
- Modify: `src/apt_scout/notify/commands.py`, `src/apt_scout/notify/telegram.py`, `src/apt_scout/__main__.py`
- Test: `tests/test_commands.py`, `tests/test_telegram.py`

**Interfaces:**
- Consumes: `normalise_city` (Task 1), `KnowledgeBase` (Task 5), `Filters` fields (Task 8).
- Produces:
  - `apply_command(filters, command, args, knowledge: KnowledgeBase | None = None) -> tuple[Filters, str]` — new commands `cities`, `exclude`, `include`; `status` shows both fields.
  - `process_commands(notifier, store, filters, filters_path, chat_id, knowledge: KnowledgeBase | None = None)`; `__main__` passes the loaded knowledge base (`Runtime.knowledge`).
  - `format_listing(listing, knowledge: KnowledgeBase | None = None)`; `TelegramNotifier(token, chat_id, client=None, timeout=15.0, knowledge=None)` forwards it. New line after the address when resolved: `🏘 <name> · <reputation label> · <tag1>, <tag2>`.
  - Hebrew labels: `REPUTATION_LABELS = {"sought_after": "מבוקשת מאוד", "solid": "טובה", "mixed": "מעורבת", "weak": "פחות מומלצת"}` and `TAG_LABELS` (15 entries) live in `src/apt_scout/neighborhoods/labels.py` so the portal JS (Task 11) can keep an identical copy.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commands.py`:

```python
from apt_scout.neighborhoods.knowledge import KnowledgeBase


def knowledge() -> KnowledgeBase:
    def entry(names, city):
        return {"names": names, "city": city, "reputation": "mixed", "summary": "s",
                "pros": ["a", "b"], "cons": ["c", "d"], "tags": ["noisy"], "sources": ["x"]}

    return KnowledgeBase.from_dict(
        {"florentin": entry(["פלורנטין", "Florentin"], "תל אביב יפו"),
         "hatikva": entry(["התקווה", "HaTikva"], "תל אביב יפו")}
    )


class TestCities:
    def test_sets_the_city_list_from_hebrew_names(self):
        updated, reply = apply_command(Filters(), "cities", ["תל", "אביב,", "גבעתיים"])
        assert updated.cities == ["תל אביב יפו", "גבעתיים"]
        assert "גבעתיים" in reply

    def test_accepts_english_and_odd_spacing(self):
        updated, _ = apply_command(Filters(), "cities", ["Ramat", "Gan", ",", "tel-aviv"])
        assert updated.cities == ["רמת גן", "תל אביב יפו"]

    def test_all_clears_the_restriction(self):
        updated, reply = apply_command(Filters(), "cities", ["all"])
        assert updated.cities == []
        assert "כל הערים" in reply

    def test_unknown_city_changes_nothing_and_lists_the_options(self):
        original = Filters()
        updated, reply = apply_command(original, "cities", ["חולון"])
        assert updated.to_dict() == original.to_dict()
        assert "רמת גן" in reply and "חולון" in reply

    def test_no_arguments_explains_the_usage(self):
        _, reply = apply_command(Filters(), "cities", [])
        assert "/cities" in reply


class TestExcludeInclude:
    def test_exclude_adds_by_any_alias(self):
        updated, reply = apply_command(Filters(), "exclude", ["florentin"], knowledge())
        assert updated.excluded_neighborhoods == ["florentin"]
        assert "פלורנטין" in reply

    def test_exclude_is_idempotent(self):
        once, _ = apply_command(Filters(), "exclude", ["פלורנטין"], knowledge())
        twice, _ = apply_command(once, "exclude", ["פלורנטין"], knowledge())
        assert twice.excluded_neighborhoods == ["florentin"]

    def test_include_removes(self):
        excluded = Filters(excluded_neighborhoods=["florentin", "hatikva"])
        updated, _ = apply_command(excluded, "include", ["התקווה"], knowledge())
        assert updated.excluded_neighborhoods == ["florentin"]

    def test_unknown_name_changes_nothing(self):
        original = Filters()
        updated, reply = apply_command(original, "exclude", ["נרניה"], knowledge())
        assert updated.to_dict() == original.to_dict()
        assert "נרניה" in reply

    def test_without_a_knowledge_base_the_command_is_refused(self):
        original = Filters()
        updated, reply = apply_command(original, "exclude", ["florentin"])
        assert updated.to_dict() == original.to_dict()
        assert reply


class TestStatusShowsNeighborhoods:
    def test_status_lists_cities_and_exclusions(self):
        f = Filters(cities=["גבעתיים"], excluded_neighborhoods=["florentin"])
        _, reply = apply_command(f, "status", [], knowledge())
        assert "גבעתיים" in reply
        assert "פלורנטין" in reply

    def test_status_with_no_restriction(self):
        _, reply = apply_command(Filters(cities=[]), "status", [])
        assert "כל הערים" in reply


def test_process_commands_forwards_the_knowledge_base(tmp_path):
    class Notifier:
        def __init__(self):
            self.sent = []

        def get_updates(self, offset=None):
            return [{"update_id": 1, "message": {"chat": {"id": 7}, "text": "/exclude florentin"}}]

        def send_text(self, text):
            self.sent.append(text)
            return True

    store = StateStore(tmp_path)
    path = tmp_path / "filters.json"
    result = process_commands(Notifier(), store, Filters(), path, chat_id="7", knowledge=knowledge())
    assert result.excluded_neighborhoods == ["florentin"]
    assert json.loads(path.read_text(encoding="utf-8"))["excluded_neighborhoods"] == ["florentin"]
```

Append to `tests/test_telegram.py` (reuse its listing helper if present):

```python
from apt_scout.neighborhoods.knowledge import KnowledgeBase
from apt_scout.notify.telegram import format_listing


def test_format_adds_a_neighborhood_line_when_resolved():
    from apt_scout.models import Listing

    kb = KnowledgeBase.from_dict(
        {"bavli": {"names": ["בבלי"], "city": "תל אביב יפו", "reputation": "sought_after", "summary": "s",
                   "pros": ["a", "b"], "cons": ["c", "d"], "tags": ["quiet", "green", "expensive"], "sources": ["x"]}}
    )
    item = Listing(source="yad2", source_id="1", url="https://y/1", address_text="בבלי 5", neighborhood="bavli")
    text = format_listing(item, kb)
    assert "🏘 בבלי · מבוקשת מאוד · שקטה, ירוקה" in text


def test_format_without_a_neighborhood_is_unchanged():
    from apt_scout.models import Listing

    item = Listing(source="yad2", source_id="1", url="https://y/1", address_text="בבלי 5")
    assert "🏘" not in format_listing(item, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_commands.py tests/test_telegram.py -q`
Expected: failures (`USAGE` returned for `cities`, `TypeError` on the extra argument).

- [ ] **Step 3: Create `neighborhoods/labels.py`**

```python
from __future__ import annotations

# Hebrew display labels. The portal keeps an identical copy in app.js
# (REPUTATION_LABELS / TAG_LABELS); tests/test_portal_assets.py checks they
# stay in sync.
REPUTATION_LABELS = {
    "sought_after": "מבוקשת מאוד",
    "solid": "טובה",
    "mixed": "מעורבת",
    "weak": "פחות מומלצת",
}

TAG_LABELS = {
    "quiet": "שקטה",
    "nightlife": "חיי לילה",
    "family": "משפחתית",
    "young": "צעירה",
    "beach": "קרוב לים",
    "green": "ירוקה",
    "light_rail": "רכבת קלה",
    "renewal": "התחדשות עירונית",
    "old_buildings": "בניינים ישנים",
    "noisy": "רועשת",
    "parking_hard": "חניה קשה",
    "expensive": "יקרה",
    "value": "תמורה למחיר",
    "religious": "אופי דתי",
    "industrial_edge": "צמוד לאזור תעשייה",
}
```

- [ ] **Step 4: Implement the commands**

In `src/apt_scout/notify/commands.py`:

Imports: `from ..enrich.city import CANONICAL_CITIES, normalise_city` and `from ..neighborhoods.knowledge import KnowledgeBase`.

Extend `USAGE` with three lines before `/pause`:

```
    "/cities <ערים מופרדות בפסיק> | all\n"
    "/exclude <שם שכונה> — הסתרת שכונה\n"
    "/include <שם שכונה> — החזרת שכונה\n"
```

Replace `_describe` with a version that takes the knowledge base:

```python
def _describe(filters: Filters, knowledge: KnowledgeBase | None = None) -> str:
    state = "מושהה" if filters.paused else "פעיל"
    cities = ", ".join(filters.cities) if filters.cities else "כל הערים"
    if filters.excluded_neighborhoods:
        names = []
        for nid in filters.excluded_neighborhoods:
            profile = knowledge.get(nid) if knowledge else None
            names.append(profile.display_name if profile else nid)
        excluded = ", ".join(names)
    else:
        excluded = "אין"
    return (
        f"סטטוס: {state}\n"
        f"מחיר: {filters.min_price:,}–{filters.max_price:,} ₪\n"
        f"נסיעה: עד {filters.max_drive_minutes:g} דק'\n"
        f'מרחק: עד {filters.max_distance_km:g} ק"מ\n'
        f"חדרים: מ-{filters.min_rooms:g}\n"
        f'שטח: מ-{filters.min_size_sqm:g} מ"ר\n'
        f"סאבלטים: {'מוסתרים' if filters.exclude_sublets else 'מוצגים'}\n"
        f"ערים: {cities}\n"
        f"שכונות מוסתרות: {excluded}"
    )
```

Add helpers:

```python
def _parse_cities(args: list[str]) -> tuple[list[str], list[str]]:
    """Split comma-separated city names; return (canonical, unknown)."""
    joined = " ".join(args)
    canonical: list[str] = []
    unknown: list[str] = []
    for part in joined.split(","):
        part = part.strip()
        if not part:
            continue
        city = normalise_city(part)
        if city is None:
            unknown.append(part)
        elif city not in canonical:
            canonical.append(city)
    return canonical, unknown


def _resolve_neighborhood(args: list[str], knowledge: KnowledgeBase | None) -> tuple[str | None, str]:
    """Resolve a typed neighborhood name to an id; the str is an error reply."""
    if knowledge is None:
        return None, "מאגר השכונות לא נטען; נסה שוב בריצה הבאה."
    name = " ".join(args).strip()
    if not name:
        return None, "שימוש: /exclude פלורנטין"
    matches = knowledge.find_by_name(name)
    if len(matches) == 1:
        return matches[0].id, ""
    if not matches:
        return None, f"לא מצאתי שכונה בשם '{name}'."
    options = ", ".join(f"{m.display_name} ({m.city})" for m in matches)
    return None, f"'{name}' לא חד-משמעי: {options}. ציין את השם המלא."
```

Change the signature of `apply_command` to `apply_command(filters, command, args, knowledge: KnowledgeBase | None = None)`, pass `knowledge` to every `_describe` call, and add before the final `return filters, USAGE`:

```python
    if command == "cities":
        if not args:
            return filters, "שימוש: /cities תל אביב, גבעתיים  או  /cities all"
        if len(args) == 1 and args[0].lower() == "all":
            updated = replace(filters, cities=[])
            return updated, _describe(updated, knowledge)
        canonical, unknown = _parse_cities(args)
        if unknown or not canonical:
            return filters, (
                f"לא מזהה: {', '.join(unknown) or ' '.join(args)}. "
                f"ערים אפשריות: {', '.join(CANONICAL_CITIES)}"
            )
        updated = replace(filters, cities=canonical)
        return updated, _describe(updated, knowledge)

    if command in ("exclude", "include"):
        nid, error = _resolve_neighborhood(args, knowledge)
        if nid is None:
            return filters, error
        current = list(filters.excluded_neighborhoods)
        if command == "exclude" and nid not in current:
            current.append(nid)
        if command == "include" and nid in current:
            current.remove(nid)
        updated = replace(filters, excluded_neighborhoods=current)
        return updated, _describe(updated, knowledge)
```

`process_commands` gains `knowledge: KnowledgeBase | None = None` and passes it: `filters, reply = apply_command(filters, command, args, knowledge)`.

- [ ] **Step 5: Implement the alert line**

In `src/apt_scout/notify/telegram.py`: import `from ..neighborhoods.labels import REPUTATION_LABELS, TAG_LABELS`; make `format_listing(listing: Listing, knowledge=None) -> str` and insert after the address/city block:

```python
    profile = knowledge.get(listing.neighborhood) if (knowledge and listing.neighborhood) else None
    if profile is not None:
        parts = [html.escape(profile.display_name), REPUTATION_LABELS.get(profile.reputation, profile.reputation)]
        tags = [TAG_LABELS.get(tag, tag) for tag in profile.tags[:2]]
        if tags:
            parts.append(", ".join(tags))
        lines.append("🏘 " + " · ".join(parts))
```

`TelegramNotifier.__init__` gains `knowledge=None`, stores `self._knowledge`, and `send_listing` calls `format_listing(listing, self._knowledge)`.

In `src/apt_scout/__main__.py`: add `knowledge: Any = None` to `Runtime`; in `build_runtime` load the data once —

```python
    index, knowledge = load_neighborhood_data(repo_root / "data")
```

— use it for `NeighborhoodEnricher(store, index, knowledge)`, pass `knowledge=knowledge` to `TelegramNotifier(...)` and set `knowledge=knowledge` on the `Runtime`. In `main`, pass `knowledge=runtime.knowledge` to `process_commands`.

- [ ] **Step 6: Run the suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/apt_scout/neighborhoods/labels.py src/apt_scout/notify/commands.py src/apt_scout/notify/telegram.py src/apt_scout/__main__.py tests/test_commands.py tests/test_telegram.py
git commit -m "feat: /cities, /exclude, /include commands and neighborhood line in alerts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Portal builder publishes the profiles

**Files:**
- Modify: `src/apt_scout/portal/builder.py`, `src/apt_scout/__main__.py`
- Test: `tests/test_portal_builder.py`

**Interfaces:**
- Consumes: `KnowledgeBase.public_dict()` (Task 5).
- Produces: `build_portal(output_dir, listings, health, filters, generated_at, knowledge: KnowledgeBase | None = None)` writes `data/neighborhoods.json` (`{}` when `knowledge` is None) next to `data/listings.json`. `defaults` already comes from `filters.to_dict()`, so `cities` / `excluded_neighborhoods` appear automatically.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_portal_builder.py`:

```python
from apt_scout.neighborhoods.knowledge import KnowledgeBase


def knowledge():
    return KnowledgeBase.from_dict(
        {"bavli": {"names": ["בבלי"], "city": "תל אביב יפו", "reputation": "sought_after", "summary": "s",
                   "pros": ["a", "b"], "cons": ["c", "d"], "tags": ["quiet"], "sources": ["x"],
                   "notes": "private"}}
    )


class TestNeighborhoodsFile:
    def test_publishes_profiles_without_notes_or_sources(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW, knowledge=knowledge())
        data = json.loads((tmp_path / "data" / "neighborhoods.json").read_text(encoding="utf-8"))
        assert data["bavli"]["names"] == ["בבלי"]
        assert "notes" not in data["bavli"]
        assert "sources" not in data["bavli"]
        assert "private" not in (tmp_path / "data" / "neighborhoods.json").read_text(encoding="utf-8")

    def test_writes_an_empty_object_without_a_knowledge_base(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW)
        assert json.loads((tmp_path / "data" / "neighborhoods.json").read_text(encoding="utf-8")) == {}

    def test_defaults_carry_the_new_filter_fields(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(excluded_neighborhoods=["bavli"]), NOW)
        payload = json.loads((tmp_path / "data" / "listings.json").read_text(encoding="utf-8"))
        assert payload["defaults"]["cities"] == ["תל אביב יפו", "גבעתיים", "רמת גן"]
        assert payload["defaults"]["excluded_neighborhoods"] == ["bavli"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_portal_builder.py -q`
Expected: `TypeError: build_portal() got an unexpected keyword argument 'knowledge'` and a missing-file error.

- [ ] **Step 3: Implement**

In `src/apt_scout/portal/builder.py`, add the parameter `knowledge: KnowledgeBase | None = None` (import `from ..neighborhoods.knowledge import KnowledgeBase`) and, right after writing `listings.json`:

```python
    # Profiles are joined client-side by id; notes/sources stay private.
    (output_dir / "data" / "neighborhoods.json").write_text(
        json.dumps(knowledge.public_dict() if knowledge else {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

In `src/apt_scout/__main__.py` pass `knowledge=runtime.knowledge` to `build_portal(...)`.

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_portal_builder.py tests/test_portal_publish.py tests/test_main.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/portal/builder.py src/apt_scout/__main__.py tests/test_portal_builder.py
git commit -m "feat: publish neighborhood profiles with the portal

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Portal front-end — city and neighborhood chips, card panel, Street View link

**Files:**
- Modify: `src/apt_scout/portal/assets/index.html`, `src/apt_scout/portal/assets/app.js`, `src/apt_scout/portal/assets/style.css`
- Test: `tests/test_portal_assets.py`

**Interfaces:**
- Consumes: `data/neighborhoods.json` (Task 10), `listing.neighborhood` and `listing.city` in `listings.json`.
- Produces (DOM ids): `#city-toggles` (chips `city-<canonical or "other">`), `#neighborhood-toggles` (a `<details>` per city containing chips `hood-<id>`), card elements `.hood` (name + `.pill.rep-<tier>` + `.tag` chips), `<details class="hood-details">`, `a.streetview`. JS constants `REPUTATION_LABELS`, `TAG_LABELS` identical to `neighborhoods/labels.py`.

Static tests only (no browser automation in this repo); correctness is checked by loading the built portal in the Browser pane in Task 12.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_portal_assets.py`:

```python
import json
import re

from apt_scout.neighborhoods.labels import REPUTATION_LABELS, TAG_LABELS


class TestNeighborhoodUi:
    def test_html_has_city_and_neighborhood_chip_containers(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="city-toggles"' in html
        assert 'id="neighborhood-toggles"' in html

    def test_js_loads_the_profiles_file(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert 'fetch("data/neighborhoods.json")' in js

    def test_js_never_uses_innerhtml(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "innerHTML" not in js

    def test_js_labels_match_the_python_labels(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")

        def block(name):
            match = re.search(name + r"\s*=\s*(\{.*?\});", js, re.S)
            assert match, name
            body = re.sub(r",\s*}", "}", match.group(1))  # tolerate a trailing comma
            return json.loads(body)

        assert block("REPUTATION_LABELS") == REPUTATION_LABELS
        assert block("TAG_LABELS") == TAG_LABELS

    def test_street_view_link_uses_the_google_maps_pattern(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "https://www.google.com/maps?layer=c&cbll=" in js

    def test_css_styles_the_reputation_tiers(self):
        css = (ASSETS / "style.css").read_text(encoding="utf-8")
        for tier in ("sought_after", "solid", "mixed", "weak"):
            assert f".rep-{tier}" in css, tier
```

Write the JS label objects with double-quoted keys and values and no trailing comma so the regex-JSON check parses them.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_portal_assets.py -q`
Expected: the six new tests fail.

- [ ] **Step 3: Update `index.html`**

Replace the sources block

```html
    <div>
      <span class="controls-subtitle">מקורות</span>
      <div id="source-toggles" class="chips"></div>
    </div>
```

with

```html
    <div>
      <span class="controls-subtitle">מקורות</span>
      <div id="source-toggles" class="chips"></div>
    </div>
    <div>
      <span class="controls-subtitle">ערים</span>
      <div id="city-toggles" class="chips"></div>
    </div>
    <div class="wide">
      <span class="controls-subtitle">שכונות</span>
      <div id="neighborhood-toggles"></div>
    </div>
```

- [ ] **Step 4: Update `app.js`**

Add near the top (after `CENTRE`):

```js
const OTHER_CITY = "other";
const REPUTATION_LABELS = {
  "sought_after": "מבוקשת מאוד",
  "solid": "טובה",
  "mixed": "מעורבת",
  "weak": "פחות מומלצת"
};
const TAG_LABELS = {
  "quiet": "שקטה",
  "nightlife": "חיי לילה",
  "family": "משפחתית",
  "young": "צעירה",
  "beach": "קרוב לים",
  "green": "ירוקה",
  "light_rail": "רכבת קלה",
  "renewal": "התחדשות עירונית",
  "old_buildings": "בניינים ישנים",
  "noisy": "רועשת",
  "parking_hard": "חניה קשה",
  "expensive": "יקרה",
  "value": "תמורה למחיר",
  "religious": "אופי דתי",
  "industrial_edge": "צמוד לאזור תעשייה"
};
let profiles = {};
let cityToggleIds = [];
let hoodToggleIds = [];
```

Helpers (after `itemSources`):

```js
function cityKey(item) {
  return item.city && CITY_RANK[item.city] !== undefined ? item.city : OTHER_CITY;
}

function profileOf(item) {
  return item.neighborhood ? profiles[item.neighborhood] || null : null;
}

function makeChip(id, text, count) {
  const label = document.createElement("label");
  label.className = "chip";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = id;
  input.checked = true;
  label.appendChild(input);
  label.appendChild(document.createTextNode(count === undefined ? text : text + " (" + count + ")"));
  return label;
}

function buildCityToggles(allListings) {
  const counts = new Map();
  allListings.forEach((item) => {
    const key = cityKey(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const keys = Array.from(counts.keys()).sort((a, b) => {
    const ra = a === OTHER_CITY ? 99 : CITY_RANK[a];
    const rb = b === OTHER_CITY ? 99 : CITY_RANK[b];
    return ra - rb;
  });
  const container = document.getElementById("city-toggles");
  container.replaceChildren();
  cityToggleIds = keys.map((key) => "city-" + key);
  keys.forEach((key) => {
    container.appendChild(makeChip("city-" + key, key === OTHER_CITY ? "אחר" : key, counts.get(key)));
  });
}

function buildNeighborhoodToggles(allListings) {
  const counts = new Map();
  allListings.forEach((item) => {
    if (item.neighborhood && profiles[item.neighborhood]) {
      counts.set(item.neighborhood, (counts.get(item.neighborhood) || 0) + 1);
    }
  });
  const byCity = new Map();
  counts.forEach((count, id) => {
    const city = profiles[id].city;
    if (!byCity.has(city)) byCity.set(city, []);
    byCity.get(city).push(id);
  });
  const container = document.getElementById("neighborhood-toggles");
  container.replaceChildren();
  hoodToggleIds = [];
  Array.from(byCity.keys())
    .sort((a, b) => (CITY_RANK[a] ?? 99) - (CITY_RANK[b] ?? 99))
    .forEach((city) => {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = city;
      details.appendChild(summary);
      const chips = document.createElement("div");
      chips.className = "chips";
      byCity.get(city)
        .sort((a, b) => counts.get(b) - counts.get(a))
        .forEach((id) => {
          hoodToggleIds.push("hood-" + id);
          chips.appendChild(makeChip("hood-" + id, profiles[id].names[0], counts.get(id)));
        });
      details.appendChild(chips);
      container.appendChild(details);
    });
}
```

State plumbing — in `readControls`, `applyControls`, `wire`, and the reset handler, treat `cityToggleIds` and `hoodToggleIds` exactly like `sourceToggleIds` (read `.checked`, default to `true` when absent from saved state, re-enable on reset, listen for `input`). Concretely, wherever the file has `sourceToggleIds.forEach(...)`, add the same loop for `cityToggleIds` and `hoodToggleIds`.

In `matches(item, state)`, after the source check:

```js
  if (state["city-" + cityKey(item)] === false) return false;
  if (item.neighborhood && state["hood-" + item.neighborhood] === false) return false;
```

In `card(item)`, after the address paragraph and before the "למודעה המקורית" link:

```js
  const profile = profileOf(item);
  if (profile) {
    const hood = document.createElement("p");
    hood.className = "hood";
    const name = document.createElement("span");
    name.className = "hood-name";
    name.textContent = profile.names[0];
    hood.appendChild(name);
    const pill = document.createElement("span");
    pill.className = "pill rep-" + profile.reputation;
    pill.textContent = REPUTATION_LABELS[profile.reputation] || profile.reputation;
    hood.appendChild(pill);
    profile.tags.slice(0, 3).forEach((tag) => {
      const chip = document.createElement("span");
      chip.className = "tag";
      chip.textContent = TAG_LABELS[tag] || tag;
      hood.appendChild(chip);
    });
    body.appendChild(hood);

    const details = document.createElement("details");
    details.className = "hood-details";
    const summary = document.createElement("summary");
    summary.textContent = "פרטים על השכונה";
    details.appendChild(summary);
    const summaryP = document.createElement("p");
    summaryP.textContent = profile.summary;
    details.appendChild(summaryP);
    [["יתרונות", profile.pros], ["חסרונות", profile.cons]].forEach(([title, items]) => {
      const h = document.createElement("strong");
      h.textContent = title;
      details.appendChild(h);
      const ul = document.createElement("ul");
      items.forEach((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        ul.appendChild(li);
      });
      details.appendChild(ul);
    });
    body.appendChild(details);
  }

  if (item.lat !== null && item.lon !== null) {
    const sv = document.createElement("a");
    sv.className = "streetview";
    sv.textContent = "Street View";
    sv.target = "_blank";
    sv.rel = "noopener noreferrer";
    const svUrl = safeHttpUrl("https://www.google.com/maps?layer=c&cbll=" + item.lat + "," + item.lon);
    if (svUrl) sv.href = svUrl;
    body.appendChild(sv);
    body.appendChild(document.createTextNode(" · "));
  }
```

In `popupContent(item)`, after the price line, add the neighborhood name when a profile exists:

```js
  const profile = profileOf(item);
  if (profile) {
    wrap.appendChild(document.createTextNode(profile.names[0]));
    wrap.appendChild(document.createElement("br"));
  }
```

Loading — replace the single `fetch("data/listings.json")` chain with two fetches; profiles are optional (a missing file must not break the page):

```js
Promise.all([
  fetch("data/listings.json").then((response) => response.json()),
  fetch("data/neighborhoods.json").then((response) => (response.ok ? response.json() : {})).catch(() => ({})),
])
  .then(([data, loadedProfiles]) => {
    profiles = loadedProfiles || {};
    listings = data.listings || [];
    defaults = data.defaults || {};
    buildSourceToggles(listings);
    buildCityToggles(listings);
    buildNeighborhoodToggles(listings);
    // ... existing applyControls / wire / render / renderHealth calls unchanged
  })
  .catch(() => {
    document.getElementById("summary").textContent = "שגיאה בטעינת הנתונים";
  });
```

- [ ] **Step 5: Update `style.css`**

Append:

```css
#controls .wide { grid-column: 1 / -1; }
#city-toggles { display: flex; flex-wrap: wrap; gap: .5rem; }
#neighborhood-toggles details { margin-bottom: .4rem; }
#neighborhood-toggles summary { cursor: pointer; font-size: .85rem; color: var(--muted); }
#neighborhood-toggles .chips { display: flex; flex-wrap: wrap; gap: .4rem; padding: .4rem 0 .2rem; }

.card .hood { display: flex; flex-wrap: wrap; align-items: center; gap: .35rem; font-size: .85rem; }
.card .hood-name { font-weight: 600; }
.pill { padding: .05rem .5rem; border-radius: 999px; font-size: .72rem; color: #fff; }
.rep-sought_after { background: var(--good); }
.rep-solid { background: var(--accent); }
.rep-mixed { background: #b7791f; }
.rep-weak { background: var(--muted); }
.tag { padding: .05rem .45rem; border: 1px solid var(--line); border-radius: 999px; font-size: .72rem; color: var(--muted); }
.hood-details { margin: .35rem 0 .5rem; font-size: .85rem; }
.hood-details summary { cursor: pointer; color: var(--accent); }
.hood-details ul { margin: .2rem 0 .5rem; padding-inline-start: 1.1rem; }
.card a.streetview { margin-inline-end: .1rem; }
```

- [ ] **Step 6: Run the asset tests and the suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_portal_assets.py -q` then `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/apt_scout/portal/assets tests/test_portal_assets.py
git commit -m "feat: portal city/neighborhood chips, neighborhood profile panel, Street View link

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: End-to-end check, docs, memory

**Files:**
- Modify: `README.md`, `C:\Users\eladl\.claude\projects\C--Github-Apt-scout\memory\apt-scout-project-state.md`
- No new source files.

- [ ] **Step 1: Dry run against the real state**

Run from the repo root:

```
.\.venv\Scripts\python.exe -m apt_scout --repo . --dry-run --build-portal --portal-dir site
```

Expected: exit 0, `fetched=... matched=...` line. The dry run may hit the network for sources whose cadence is due; that is fine. Then count resolutions:

```
.\.venv\Scripts\python.exe -c "import json,collections;d=json.load(open('site/data/listings.json',encoding='utf-8'));c=collections.Counter(i['neighborhood'] for i in d['listings']);print(len(d['listings']), 'listings;', sum(v for k,v in c.items() if k), 'with neighborhood;', c.most_common(8))"
```

Expected: a large majority of listings resolve (yad2 ships coordinates for all 200; the rest are geocoded). Investigate if fewer than ~70% resolve — the usual cause is a listing outside every polygon (Holon/Bat Yam), which is correct.

Important: the dry run writes `state/` (cadence, caches, the new `state/neighborhoods.json` cache). Only `state/neighborhoods.json` is new and it is safe to commit; revert any other state changes before committing: `git checkout -- state/cadence.json state/seen.json state/notified.json` etc. (`git status` shows them). `config/filters.json` is not rewritten by a dry run.

- [ ] **Step 2: Look at the portal**

Serve `site/` locally (`.\.venv\Scripts\python.exe -m http.server 8765 --directory site`, in the background) and open `http://localhost:8765` in the Browser pane. Check: city chips present with counts, neighborhood group per city expands, cards show neighborhood name + coloured pill + tags, "פרטים על השכונה" expands to summary/pros/cons, Street View link opens Google Maps at the listing, toggling a neighborhood chip hides its cards, reset re-enables everything. Take one screenshot for the summary message. Stop the server afterwards.

- [ ] **Step 3: README**

In the commands table add rows after `/sublets`:

```
| `/cities תל אביב, גבעתיים` | Restrict alerts to these cities (`/cities all` lifts the restriction) |
| `/exclude פלורנטין` / `/include פלורנטין` | Hide or restore a neighborhood (any Hebrew/English alias) |
```

Add a `## Neighborhoods` section before `## Portal`:

```
## Neighborhoods

Every listing is assigned a neighborhood by point-in-polygon against
`data/neighborhoods.geojson` (OpenStreetMap `place=suburb` boundaries for
Tel Aviv-Yafo, Givatayim and Ramat Gan, plus the city boundaries as a
fallback). `data/neighborhoods.json` holds a hand-curated profile per
neighborhood: a consensus reputation tier (`sought_after` / `solid` /
`mixed` / `weak`), a summary, pros, cons and tags. Sources for each call are
listed in `docs/neighborhoods-sources.md`. The profile appears on portal
cards and as one line in Telegram alerts; it is opinion distilled from
public guides, not a score, and the JSON is meant to be edited.

Rebuild the boundaries with `scripts/build_neighborhoods_geojson.py`; every
polygon must have a profile (a test enforces it).
```

Update the `## Portal` section's control list to mention city chips, neighborhood chips and the Street View link.

- [ ] **Step 4: Memory**

In `apt-scout-project-state.md` add a bullet: neighborhoods shipped 2026-09-03 (OSM polygons + curated KB, city normaliser, `/cities` `/exclude` `/include`, portal chips + profile panel + Street View link); Givatayim has only two OSM neighborhood polygons so most Givatayim listings resolve to the city-level `givatayim` profile; the KB is user-editable at `data/neighborhoods.json`.

- [ ] **Step 5: Full suite, commit, push**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass (previous count 552 + the new tests).

```bash
git add README.md state/neighborhoods.json
git commit -m "docs: neighborhoods, city filter and new commands

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

Then trigger a real run (`gh workflow run scan --repo Eladlavy12/apt-scout`), wait for it, and confirm on https://eladlavy12.github.io/apt-scout/ that city chips and neighborhood pills appear. If the CI run fails on the new data loading (`FileNotFoundError` for `data/`), the cause is the checkout path — `--repo .` is the repo root on CI, so `data/` is present; check the workflow log before changing code.

---

## Self-review notes

- Spec coverage: §1 knowledge base → Tasks 5–6; §2 geography, model, city normalisation, enricher → Tasks 1–4, 7; §3 filters and commands → Tasks 8–9; §4 portal → Tasks 10–11; §5 tests → inside each task; Street View link → Task 11; docs → Task 12.
- Deviation from spec §2: the spec's `/exclude` matches "any alias"; `find_by_name` does exact alias match (after normalisation), not substring — deliberate, so `/exclude יפו` cannot accidentally hit the wrong entry. Ambiguity returns the options list.
- Deviation from spec §4: neighborhood chip default state is "all on" even for ids in `defaults.excluded_neighborhoods`; the portal is a browsing surface and the alert exclusions are shown via `/status`. Reset keeps "all on".
