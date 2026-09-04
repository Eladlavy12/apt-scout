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
