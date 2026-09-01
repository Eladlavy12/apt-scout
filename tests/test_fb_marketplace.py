import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apt_scout.adapters import fb_marketplace
from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.fb_marketplace import (
    ACTOR_RUN_URL,
    DEFAULT_SEARCH_URL,
    FbMarketplaceAdapter,
    parse_marketplace_items,
)
from apt_scout.models import Occupancy

FIXTURE = Path(__file__).parent / "fixtures" / "fb_marketplace.json"


def _fixture_items() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestParseRealFixture:
    def test_parses_at_least_three_listings(self):
        listings = parse_marketplace_items(_fixture_items())
        assert len(listings) >= 3

    def test_every_listing_is_from_fb_marketplace_with_an_id(self):
        listings = parse_marketplace_items(_fixture_items())
        assert listings
        for listing in listings:
            assert listing.source == "fb_marketplace"
            assert listing.source_id
            assert isinstance(listing.source_id, str)

    def test_urls_are_facebook_marketplace_item_links(self):
        listings = parse_marketplace_items(_fixture_items())
        for listing in listings:
            assert listing.url.startswith(
                "https://www.facebook.com/marketplace/item/"
            )

    def test_prices_are_ints_and_ils_only(self):
        listings = parse_marketplace_items(_fixture_items())
        priced = [l for l in listings if l.price is not None]
        assert priced
        for listing in priced:
            assert isinstance(listing.price, int)
            assert not isinstance(listing.price, bool)

    def test_occupancy_is_classified_not_forced_whole(self):
        # Marketplace mixes whole-apartment ads with roommate ads; a naive
        # adapter that hardcodes WHOLE would misclassify roommate posts.
        listings = parse_marketplace_items(_fixture_items())
        occupancies = {l.occupancy for l in listings}
        assert Occupancy.ROOMMATES in occupancies
        assert Occupancy.WHOLE in occupancies

    def test_known_roommate_listing_is_classified_as_roommates(self):
        listings = parse_marketplace_items(_fixture_items())
        by_id = {l.source_id: l for l in listings}
        # This listing's description says "דירת 2 חדרים מעולה לשותפים".
        assert by_id["3572971062871836"].occupancy is Occupancy.ROOMMATES

    def test_titles_and_descriptions_are_populated(self):
        listings = parse_marketplace_items(_fixture_items())
        assert any(l.title for l in listings)
        assert any(l.raw_text for l in listings)

    def test_photos_are_populated_for_at_least_some_listings(self):
        listings = parse_marketplace_items(_fixture_items())
        assert any(l.photos for l in listings)


class TestSyntheticParsing:
    def _item(self, **overrides):
        base = {
            "id": "111",
            "marketplace_listing_title": "דירה להשכרה",
            "redacted_description": {"text": "דירה יפה במרכז העיר"},
            "listing_price": {"amount": "4500.00", "currency": "ILS"},
            "listingUrl": "https://www.facebook.com/marketplace/item/111",
            "creation_time": 1735689600,
            "location": {"latitude": 32.08, "longitude": 34.78},
        }
        base.update(overrides)
        return base

    def test_missing_price_field_becomes_none(self):
        item = self._item()
        del item["listing_price"]
        listing = parse_marketplace_items([item])[0]
        assert listing.price is None

    def test_non_ils_price_is_skipped_to_none(self):
        item = self._item(listing_price={"amount": "1200.00", "currency": "USD"})
        listing = parse_marketplace_items([item])[0]
        assert listing.price is None

    def test_ils_price_normalizes_to_int(self):
        item = self._item(listing_price={"amount": "4999.00", "currency": "ILS"})
        listing = parse_marketplace_items([item])[0]
        assert listing.price == 4999
        assert isinstance(listing.price, int)

    def test_item_without_id_is_skipped(self):
        item = self._item()
        del item["id"]
        assert parse_marketplace_items([item]) == []

    def test_item_with_empty_id_is_skipped(self):
        item = self._item(id="")
        assert parse_marketplace_items([item]) == []

    def test_error_sentinel_item_has_no_id_and_is_skipped(self):
        # The actor emits entries like {"error": "..."} with no "id" - these
        # must not crash the parser or become a Listing.
        listings = parse_marketplace_items(
            [self._item(), {"error": "limited to 10 for free users"}]
        )
        assert len(listings) == 1

    def test_non_dict_items_are_skipped(self):
        listings = parse_marketplace_items([self._item(), "not a dict", None, 42])
        assert len(listings) == 1

    def test_non_list_input_returns_empty_list(self):
        assert parse_marketplace_items(None) == []
        assert parse_marketplace_items({"not": "a list"}) == []

    def test_missing_description_still_classifies_from_title(self):
        item = self._item(marketplace_listing_title="דירת שותפים להשכרה")
        del item["redacted_description"]
        listing = parse_marketplace_items([item])[0]
        assert listing.occupancy is Occupancy.ROOMMATES

    def test_falls_back_to_primary_photo_when_no_listing_photos(self):
        item = self._item(primary_listing_photo_url="https://example.com/p.jpg")
        listing = parse_marketplace_items([item])[0]
        assert listing.photos == ["https://example.com/p.jpg"]


TEST_TOKEN = "test-token"


class FakeBudget:
    def __init__(self, allow: bool = True):
        self._allow = allow
        self.can_spend_calls: list[tuple] = []
        self.record_calls: list[tuple] = []

    def can_spend(self, source: str, now: datetime) -> bool:
        self.can_spend_calls.append((source, now))
        return self._allow

    def record(self, source: str, results: int, cost_usd: float, now: datetime) -> None:
        self.record_calls.append((source, results, cost_usd, now))


def _dataset_text(items: list[dict]) -> str:
    return json.dumps(items)


class TestAdapterBudget:
    def test_name_is_fb_marketplace(self):
        assert FbMarketplaceAdapter(FakeBudget()).name == "fb_marketplace"

    def test_budget_exhausted_returns_error_and_makes_no_http_call(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("post_json must not be called when budget is exhausted")

        monkeypatch.setattr(fb_marketplace, "post_json", explode)
        budget = FakeBudget(allow=False)
        config = {"token": TEST_TOKEN}

        result = FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert isinstance(result, AdapterResult)
        assert result.listings == []
        assert result.error == "budget exhausted"
        assert budget.record_calls == []

    def test_missing_token_returns_error_without_http_call(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("post_json must not be called without a token")

        monkeypatch.setattr(fb_marketplace, "post_json", explode)
        budget = FakeBudget(allow=True)

        result = FbMarketplaceAdapter(budget).fetch(fetcher=None, config={}, since=None)

        assert result.listings == []
        assert result.error is not None
        assert "token" in result.error.lower()

    def test_success_path_parses_items_and_records_budget(self, monkeypatch):
        items = [
            {
                "id": "1",
                "marketplace_listing_title": "דירה להשכרה",
                "redacted_description": {"text": "דירה משופצת"},
                "listing_price": {"amount": "4500.00", "currency": "ILS"},
                "listingUrl": "https://www.facebook.com/marketplace/item/1",
            },
            {
                "id": "2",
                "marketplace_listing_title": "חדר לשותף",
                "redacted_description": {"text": "חדר בדירה משותפת"},
                "listing_price": {"amount": "2000.00", "currency": "ILS"},
                "listingUrl": "https://www.facebook.com/marketplace/item/2",
            },
        ]
        captured = {}

        def fake_post_json(url, payload, timeout=280.0):
            captured["url"] = url
            captured["payload"] = payload
            return 201, _dataset_text(items)

        monkeypatch.setattr(fb_marketplace, "post_json", fake_post_json)
        budget = FakeBudget(allow=True)
        config = {"token": TEST_TOKEN}

        result = FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert result.error is None
        assert len(result.listings) == 2
        assert budget.record_calls == [
            ("fb_marketplace", 2, 2 * 0.0005, budget.record_calls[0][3])
        ]
        assert isinstance(budget.record_calls[0][3], datetime)
        # token travels in the URL, not committed anywhere; payload uses the
        # actor's real input field name "urls" (not "startUrls").
        assert TEST_TOKEN in captured["url"]
        assert ACTOR_RUN_URL in captured["url"]
        assert captured["payload"]["urls"] == [DEFAULT_SEARCH_URL]
        assert captured["payload"]["getListingDetails"] is True

    def test_custom_search_url_is_used_when_configured(self, monkeypatch):
        captured = {}

        def fake_post_json(url, payload, timeout=280.0):
            captured["payload"] = payload
            return 201, _dataset_text([])

        monkeypatch.setattr(fb_marketplace, "post_json", fake_post_json)
        budget = FakeBudget(allow=True)
        config = {"token": TEST_TOKEN, "search_url": "https://example.com/search"}

        FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert captured["payload"]["urls"] == ["https://example.com/search"]

    def test_http_transport_failure_becomes_error_result(self, monkeypatch):
        def raising(url, payload, timeout=280.0):
            raise RuntimeError("connection reset")

        monkeypatch.setattr(fb_marketplace, "post_json", raising)
        budget = FakeBudget(allow=True)
        config = {"token": TEST_TOKEN}

        result = FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert result.listings == []
        assert result.error is not None
        assert "connection reset" in result.error
        assert budget.record_calls == []

    def test_non_200_status_becomes_error_result(self, monkeypatch):
        monkeypatch.setattr(
            fb_marketplace, "post_json", lambda url, payload, timeout=280.0: (500, "boom")
        )
        budget = FakeBudget(allow=True)
        config = {"token": TEST_TOKEN}

        result = FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert result.listings == []
        assert result.error is not None
        assert "500" in result.error
        assert budget.record_calls == []

    def test_unparseable_json_response_becomes_error_result(self, monkeypatch):
        monkeypatch.setattr(
            fb_marketplace, "post_json", lambda url, payload, timeout=280.0: (201, "not json")
        )
        budget = FakeBudget(allow=True)
        config = {"token": TEST_TOKEN}

        result = FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert result.listings == []
        assert result.error is not None
        assert budget.record_calls == []

    def test_max_results_truncates_and_budget_reflects_truncated_count(self, monkeypatch):
        items = [
            {
                "id": str(i),
                "marketplace_listing_title": "דירה להשכרה",
                "listing_price": {"amount": "4000.00", "currency": "ILS"},
                "listingUrl": f"https://www.facebook.com/marketplace/item/{i}",
            }
            for i in range(5)
        ]
        monkeypatch.setattr(
            fb_marketplace,
            "post_json",
            lambda url, payload, timeout=280.0: (201, _dataset_text(items)),
        )
        budget = FakeBudget(allow=True)
        config = {"token": TEST_TOKEN, "max_results": 2}

        result = FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert result.error is None
        assert len(result.listings) == 2
        assert budget.record_calls[0][1] == 2

    def test_can_spend_is_checked_with_a_timezone_aware_now(self, monkeypatch):
        monkeypatch.setattr(
            fb_marketplace, "post_json", lambda url, payload, timeout=280.0: (201, "[]")
        )
        budget = FakeBudget(allow=True)
        config = {"token": TEST_TOKEN}

        FbMarketplaceAdapter(budget).fetch(fetcher=None, config=config, since=None)

        assert len(budget.can_spend_calls) == 1
        source, now = budget.can_spend_calls[0]
        assert source == "fb_marketplace"
        assert now.tzinfo is not None
