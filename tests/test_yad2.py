import json
from pathlib import Path

from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.yad2 import Yad2Adapter, parse_yad2_payload
from apt_scout.fetch import FetchError, FetchResult
from apt_scout.models import Occupancy

FIXTURE = Path(__file__).parent / "fixtures" / "yad2_search.json"


def sample_payload():
    return {
        "data": {
            "markers": [
                {
                    "orderId": "111",
                    "price": 4800,
                    "additionalDetails": {
                        "roomsCount": 3,
                        "squareMeter": 72,
                        "property": {"text": "דירה"},
                    },
                    "address": {
                        "city": {"text": "תל אביב יפו"},
                        "street": {"text": "הרצל"},
                        "house": {"number": 10, "floor": 2},
                        "coords": {"lat": 32.0561, "lon": 34.8041},
                    },
                    "metaData": {"images": ["https://img/1.jpg"]},
                }
            ]
        }
    }


class TestParsing:
    def test_extracts_core_fields(self):
        listings = parse_yad2_payload(sample_payload())
        assert len(listings) == 1
        listing = listings[0]
        assert listing.source == "yad2"
        assert listing.source_id == "111"
        assert listing.price == 4800
        assert listing.rooms == 3.0
        assert listing.size_sqm == 72.0
        assert listing.city == "תל אביב יפו"
        assert listing.lat == 32.0561
        assert listing.lon == 34.8041
        assert listing.photos == ["https://img/1.jpg"]

    def test_builds_a_listing_url(self):
        listing = parse_yad2_payload(sample_payload())[0]
        assert listing.source_id in listing.url
        assert listing.url.startswith("https://")

    def test_yad2_listings_are_whole_apartments(self):
        # yad2's rental apartment category never contains roommate ads, so the
        # classifier does not need to guess here.
        assert parse_yad2_payload(sample_payload())[0].occupancy is Occupancy.WHOLE

    def test_missing_fields_become_none_not_zero(self):
        payload = {"data": {"markers": [{"orderId": "222"}]}}
        listing = parse_yad2_payload(payload)[0]
        assert listing.price is None
        assert listing.rooms is None
        assert listing.size_sqm is None
        assert listing.lat is None

    def test_entries_without_an_id_are_skipped(self):
        payload = {"data": {"markers": [{"price": 5000}]}}
        assert parse_yad2_payload(payload) == []

    def test_empty_payload_returns_empty_list(self):
        assert parse_yad2_payload({}) == []

    def test_parses_real_fixture(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        listings = parse_yad2_payload(payload)
        assert listings, "real yad2 fixture must yield at least one listing"
        assert all(listing.source_id for listing in listings)
        assert all(listing.url.startswith("https://") for listing in listings)

    def test_prefers_token_over_order_id_for_identity(self):
        payload = {"data": {"markers": [{"token": "abc123", "orderId": 999, "price": 5000}]}}
        listing = parse_yad2_payload(payload)[0]
        assert listing.source_id == "abc123"
        assert "abc123" in listing.url

    def test_includes_agency_promotions(self):
        payload = {
            "data": {
                "markers": [{"token": "aaa", "price": 5000}],
                "agencyPromotions": [{"token": "bbb", "price": 5200}],
            }
        }
        ids = [l.source_id for l in parse_yad2_payload(payload)]
        assert ids == ["aaa", "bbb"]


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


class TestAdapter:
    def test_returns_listings_on_success(self):
        fetcher = FakeFetcher(text=json.dumps(sample_payload()))
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "http"}

        result = Yad2Adapter().fetch(fetcher, config, since=None)

        assert isinstance(result, AdapterResult)
        assert result.error is None
        assert len(result.listings) == 1

    def test_uses_the_configured_minimum_tier(self):
        fetcher = FakeFetcher(text=json.dumps(sample_payload()))
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "browser"}

        Yad2Adapter().fetch(fetcher, config, since=None)

        assert fetcher.requested[0][1] == "browser"

    def test_fetch_failure_becomes_an_error_result_not_an_exception(self):
        # A failing source must degrade the run, never fail it.
        fetcher = FakeFetcher(error=FetchError("blocked"))
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "http"}

        result = Yad2Adapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert "blocked" in result.error

    def test_malformed_json_becomes_an_error_result(self):
        fetcher = FakeFetcher(text="<html>blocked</html>")
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "http"}

        result = Yad2Adapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None

    def test_missing_url_template_becomes_an_error_result(self):
        result = Yad2Adapter().fetch(FakeFetcher(text="{}"), {}, since=None)
        assert result.listings == []
        assert "url_template" in result.error
