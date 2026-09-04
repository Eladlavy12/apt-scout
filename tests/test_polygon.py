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
