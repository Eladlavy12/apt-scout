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
        # Original brief coordinate (32.0900, 34.7915) lies just outside the
        # OSM Bavli polygon, inside the neighbouring new_north_kikar_hamedina
        # polygon instead; this point sits near the Bavli centroid.
        assert index.lookup(32.0970, 34.7990) == "bavli"
        assert index.lookup(32.0720, 34.8110) == "givatayim"  # outside mapped hoods
        assert index.lookup(32.0100, 34.7600) is None  # Bat Yam: out of scope
