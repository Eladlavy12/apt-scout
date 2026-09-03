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
# OSM spells the Tel Aviv relation name with a Hebrew maqaf and an en dash
# (תל־אביב–יפו), not the plain hyphen/spaces used elsewhere in this file.
CITY_OSM_NAMES = {"תל־אביב–יפו": "תל אביב יפו", "גבעתיים": "גבעתיים", "רמת גן": "רמת גן"}

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
  relation["boundary"="administrative"]["admin_level"="8"]["name"="תל־אביב–יפו"];
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
    # overpass-api.de returns 406 Not Acceptable for the default httpx
    # User-Agent (an Apache-level block, not an Overpass rate limit); a
    # normal-looking UA avoids it.
    headers = {"User-Agent": "apt-scout-neighborhoods/1.0 (+https://github.com/)"}
    response = httpx.post(OVERPASS, data={"data": query}, timeout=180, headers=headers)
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
