from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..enrich.occupancy import classify_occupancy
from ..models import Listing
from .base import AdapterResult

# Facebook Marketplace via the "curious_coder~facebook-marketplace" Apify
# actor (pay-per-event: ~$0.0015 per listing item measured with detail
# fetches enabled, see the actor's
# pricingInfos). Discovery on 2026-09-01, using the live APIFY_TOKEN secret:
#
#   GET https://api.apify.com/v2/acts/curious_coder~facebook-marketplace
#       ?token=...
#   GET https://api.apify.com/v2/acts/curious_coder~facebook-marketplace
#       /builds/{data.taggedBuilds.latest.buildId}?token=...
#     -> data.inputSchema (a JSON string) documents the real input fields:
#        "urls" (array of search/listing URLs - NOT "startUrls"),
#        "getListingDetails" (bool, must be true to get descriptions -
#        occupancy classification needs them), "maxPagesPerUrl", etc. There
#        is no per-request item-count field in the input schema itself; the
#        cap is applied via the run endpoint's own "maxItems" query param.
#
# The actual capture call (token redacted):
#
#   POST https://api.apify.com/v2/acts/curious_coder~facebook-marketplace
#        /run-sync-get-dataset-items?token=...&timeout=280&maxItems=20
#   Content-Type: application/json
#   {
#     "urls": ["https://www.facebook.com/marketplace/telaviv/propertyrentals"
#              "?minPrice=4000&maxPrice=5500&sortBy=creation_time_descend"
#              "&exact=false"],
#     "getListingDetails": true,
#     "maxPagesPerUrl": 1
#   }
#
# Returned HTTP 201 with 20 real listing items plus one trailing
# `{"error": "...limited to 10 for free users..."}` sentinel object (the
# actor's free-tier notice on some other internal cap - it did not stop the
# 20 items from coming through, and this adapter simply skips any item
# lacking an "id", which drops that sentinel along with anything else
# malformed). Saved to tests/fixtures/fb_marketplace.json.
#
# Each dataset item is a near-verbatim Facebook GraphQL listing node. The
# fields this adapter reads: "id", "marketplace_listing_title" /
# "custom_title", "redacted_description.text", "listing_price" (an
# {"amount": "4800.00", "currency": "ILS", ...} dict - ILS only, per the
# binding; USD/other currencies are skipped rather than misconverted),
# "listingUrl", "creation_time" (unix seconds), "location" (lat/lon plus a
# best-effort reverse-geocoded city), "location_text", and "listing_photos"
# (falling back to "primary_listing_photo_url"). Marketplace mixes whole
# apartments and roommate posts in the same rentals category, so occupancy
# is classified from title + description rather than forced WHOLE.
#
# Extending nothing: Fetcher's tier system exists to disguise scraping
# requests from bot-protected sites. Apify is a cooperative, paid API we are
# a legitimate client of - there is nothing to disguise here - so this
# module makes its own minimal httpx POST via `post_json` below instead of
# going through Fetcher. This is a deliberate, localized exception.

ACTOR_RUN_URL = (
    "https://api.apify.com/v2/acts/curious_coder~facebook-marketplace/"
    "run-sync-get-dataset-items"
)

DEFAULT_SEARCH_URL = (
    "https://www.facebook.com/marketplace/telaviv/propertyrentals"
    "?minPrice=4000&maxPrice=5500&sortBy=creation_time_descend&exact=false"
)

COST_PER_ITEM_USD = 0.0015  # curious_coder actor: ~$0.50/1k basic + detail fetches; measured effective rate ~$1.50/1k


def post_json(url: str, payload: dict, timeout: float = 280.0) -> tuple[int, str]:
    """Minimal POST helper used only by this adapter - see module docstring."""
    import httpx

    response = httpx.post(url, json=payload, timeout=timeout)
    return response.status_code, response.text


def _description(item: dict) -> str:
    description = item.get("redacted_description")
    if isinstance(description, dict):
        text = description.get("text")
        if isinstance(text, str):
            return text
    return ""


def _price_ils(price: Any) -> int | None:
    """ILS-only price in whole shekels; any other currency is skipped."""
    if not isinstance(price, dict):
        return None
    if price.get("currency") != "ILS":
        return None
    amount = price.get("amount")
    try:
        return int(round(float(amount)))
    except (TypeError, ValueError):
        return None


def _photos(item: dict) -> list[str]:
    photos: list[str] = []
    raw_photos = item.get("listing_photos")
    if isinstance(raw_photos, list):
        for photo in raw_photos:
            if not isinstance(photo, dict):
                continue
            image = photo.get("image")
            uri = image.get("uri") if isinstance(image, dict) else None
            if isinstance(uri, str):
                photos.append(uri)
    if not photos:
        primary = item.get("primary_listing_photo_url")
        if isinstance(primary, str):
            photos.append(primary)
    return photos


def _city(item: dict) -> str | None:
    location = item.get("location")
    if isinstance(location, dict):
        for key in ("reverse_geocode_detailed", "reverse_geocode"):
            geo = location.get(key)
            if isinstance(geo, dict) and isinstance(geo.get("city"), str):
                return geo["city"]
    location_text = item.get("location_text")
    if isinstance(location_text, dict) and isinstance(location_text.get("text"), str):
        return location_text["text"]
    return None


def _lat_lon(item: dict) -> tuple[float | None, float | None]:
    location = item.get("location")
    if not isinstance(location, dict):
        return None, None
    lat = location.get("latitude")
    lon = location.get("longitude")
    lat = float(lat) if isinstance(lat, (int, float)) and not isinstance(lat, bool) else None
    lon = float(lon) if isinstance(lon, (int, float)) and not isinstance(lon, bool) else None
    return lat, lon


def _posted_at(item: dict) -> datetime | None:
    timestamp = item.get("creation_time")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _listing_url(item: dict, source_id: str) -> str:
    url = item.get("listingUrl")
    if isinstance(url, str) and url:
        return url
    return f"https://www.facebook.com/marketplace/item/{source_id}"


def parse_marketplace_items(items: list[dict]) -> list[Listing]:
    """Convert Apify dataset items from the FB Marketplace actor into Listings.

    Items missing an "id" are skipped - this also drops the actor's own
    error/sentinel entries (e.g. its free-tier-limit notice), which carry no
    "id" field. Anything the source did not state stays None rather than
    being guessed.
    """
    listings: list[Listing] = []
    if not isinstance(items, list):
        return listings

    for item in items:
        if not isinstance(item, dict):
            continue
        source_id = item.get("id")
        if not source_id:
            continue
        source_id = str(source_id)

        title = item.get("marketplace_listing_title") or item.get("custom_title")
        title = title if isinstance(title, str) else None
        description = _description(item)
        occupancy_text = " ".join(part for part in (title, description) if part)

        city = _city(item)
        lat, lon = _lat_lon(item)

        listings.append(
            Listing(
                source="fb_marketplace",
                source_id=source_id,
                url=_listing_url(item, source_id),
                title=title,
                raw_text=description or None,
                price=_price_ils(item.get("listing_price")),
                city=city,
                address_text=city,
                lat=lat,
                lon=lon,
                photos=_photos(item),
                occupancy=classify_occupancy(occupancy_text),
                posted_at=_posted_at(item),
            )
        )

    return listings


class FbMarketplaceAdapter:
    name = "fb_marketplace"

    def __init__(self, budget: Any) -> None:
        self._budget = budget

    def fetch(self, fetcher: Any, config: dict, since: datetime | None) -> AdapterResult:
        now = datetime.now(timezone.utc)

        if not self._budget.can_spend(self.name, now):
            return AdapterResult(source=self.name, error="budget exhausted")

        token = config.get("token")
        if not token:
            return AdapterResult(source=self.name, error="missing Apify token")

        search_url = config.get("search_url", DEFAULT_SEARCH_URL)
        payload = {
            "urls": [search_url],
            "getListingDetails": True,
            "maxPagesPerUrl": config.get("max_pages_per_url", 1),
        }
        max_items = config.get("max_items", 20)
        run_url = f"{ACTOR_RUN_URL}?token={token}&timeout=280&maxItems={max_items}"

        try:
            status, text = post_json(run_url, payload)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return AdapterResult(source=self.name, error=f"fetch failed: {exc}")

        if status not in (200, 201):
            return AdapterResult(source=self.name, error=f"apify HTTP {status}")

        try:
            items = json.loads(text)
        except json.JSONDecodeError as exc:
            return AdapterResult(source=self.name, error=f"response was not JSON: {exc}")

        try:
            listings = parse_marketplace_items(items)
        except Exception as exc:  # noqa: BLE001 - a shape change must not crash
            return AdapterResult(source=self.name, error=f"parse failed: {exc}")

        # Record budget BEFORE filtering, since we paid for all fetched items.
        self._budget.record(
            self.name, len(listings), len(listings) * COST_PER_ITEM_USD, now
        )

        # Facebook returns a rotating sample of listings—without an age guard,
        # old listings resurface repeatedly as fresh alerts. Filter to keep only
        # recent listings, but retain items with unknown posted_at (fail open).
        max_age_days = config.get("max_age_days", 7)
        filtered = []
        for listing in listings:
            if listing.posted_at is None:
                # Fail open: keep listings with no posted_at timestamp.
                filtered.append(listing)
            else:
                age = now - listing.posted_at
                if age.days <= max_age_days:
                    filtered.append(listing)
        listings = filtered

        limit = config.get("max_results")
        if limit:
            listings = listings[:limit]

        return AdapterResult(source=self.name, listings=listings)
