import json
from pathlib import Path

from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.onmap import OnmapAdapter, parse_onmap_payload
from apt_scout.fetch import FetchError, FetchResult
from apt_scout.models import Occupancy

FIXTURE = Path(__file__).parent / "fixtures" / "onmap_search.json"


def sample_item(**overrides):
    # Field paths verified against the real captured fixture (see
    # .superpowers/sdd + scratchpad RECIPE.md): address names live under
    # address.en / address.he (each holding street_name/house_number/
    # neighborhood/city_name), not address.city.he_name as first guessed.
    base = {
        "id": "abc-123",
        "price": 5200,
        "additional_info": {"rooms": 3, "area": {"base": 68}},
        "address": {
            "en": {
                "city_name": "Tel Aviv-Yafo",
                "street_name": "Ibn Gvirol",
                "house_number": "10",
                "neighborhood": "",
            },
            "he": {
                "city_name": "תל אביב יפו",
                "street_name": "אבן גבירול",
                "house_number": "10",
                "neighborhood": "",
            },
            "location": {"lat": 32.08, "lon": 34.781},
        },
        "images": [{"full": "https://img.onmap.co.il/1.jpg"}],
        "created_at": "2026-08-30T10:00:00.000Z",
        "search_option": "rent",
        "slug": "apartment-for-rent-abc-123",
    }
    base.update(overrides)
    return base


class TestParsing:
    def test_extracts_core_fields(self):
        listing = parse_onmap_payload([sample_item()])[0]
        assert listing.source == "onmap"
        assert listing.source_id == "abc-123"
        assert listing.price == 5200
        assert listing.rooms == 3.0
        assert listing.size_sqm == 68.0
        assert listing.lat == 32.08
        assert listing.lon == 34.781
        assert listing.photos == ["https://img.onmap.co.il/1.jpg"]
        assert listing.occupancy is Occupancy.WHOLE
        assert listing.posted_at is not None

    def test_builds_a_listing_url_containing_the_id(self):
        listing = parse_onmap_payload([sample_item()])[0]
        assert "abc-123" in listing.url and listing.url.startswith("https://")

    def test_missing_fields_become_none(self):
        listing = parse_onmap_payload([{"id": "x"}])[0]
        assert listing.price is None and listing.rooms is None
        assert listing.lat is None and listing.photos == []

    def test_items_without_an_id_are_skipped(self):
        assert parse_onmap_payload([{"price": 5000}]) == []

    def test_accepts_wrapped_dict_payloads(self):
        # Feathers.js sometimes wraps results as {"data": [...]}
        assert len(parse_onmap_payload({"data": [sample_item()]})) == 1

    def test_parses_real_fixture(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        listings = parse_onmap_payload(payload)
        assert len(listings) >= 5
        assert all(l.source_id for l in listings)
        assert all(l.url.startswith("https://") for l in listings)
        priced = [l for l in listings if l.price is not None]
        assert priced, "real fixture must contain priced listings"


class FakeFetcher:
    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error
        self.requested = []

    def get(self, url, min_tier="http", headers=None):
        self.requested.append((url, min_tier))
        if self._error:
            raise self._error
        return FetchResult(url=url, status=200, text=self._text, tier=min_tier)


def sample_payload():
    return {"data": [sample_item()]}


class TestAdapter:
    def test_returns_listings_on_success(self):
        fetcher = FakeFetcher(text=json.dumps(sample_payload()))
        config = {
            "url_template": (
                "https://phoenix.onmap.co.il/v1/properties/mixed_search"
                "?min={price_min}&max={price_max}&rooms[]=2&rooms[]=3"
            ),
            "min_tier": "http",
        }

        result = OnmapAdapter().fetch(fetcher, config, since=None)

        assert isinstance(result, AdapterResult)
        assert result.error is None
        assert len(result.listings) == 1

    def test_uses_the_configured_minimum_tier(self):
        fetcher = FakeFetcher(text=json.dumps(sample_payload()))
        config = {
            "url_template": "https://phoenix.onmap.co.il/v1/properties/mixed_search?min={price_min}&max={price_max}",
            "min_tier": "browser",
        }

        OnmapAdapter().fetch(fetcher, config, since=None)

        assert fetcher.requested[0][1] == "browser"

    def test_fetch_failure_becomes_an_error_result_not_an_exception(self):
        # A failing source must degrade the run, never fail it.
        fetcher = FakeFetcher(error=FetchError("blocked"))
        config = {
            "url_template": "https://phoenix.onmap.co.il/v1/properties/mixed_search?min={price_min}&max={price_max}",
            "min_tier": "http",
        }

        result = OnmapAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert "blocked" in result.error

    def test_malformed_json_becomes_an_error_result(self):
        fetcher = FakeFetcher(text="<html>blocked</html>")
        config = {
            "url_template": "https://phoenix.onmap.co.il/v1/properties/mixed_search?min={price_min}&max={price_max}",
            "min_tier": "http",
        }

        result = OnmapAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None

    def test_missing_url_template_becomes_an_error_result(self):
        result = OnmapAdapter().fetch(FakeFetcher(text="{}"), {}, since=None)
        assert result.listings == []
        assert "url_template" in result.error
