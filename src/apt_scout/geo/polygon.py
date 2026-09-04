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
