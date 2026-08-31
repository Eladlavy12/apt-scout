from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..models import Listing, Occupancy
from .base import AdapterResult

LISTING_URL = "https://www.onmap.co.il/search/homes/{search_option}?property={slug}"


def _get(mapping: Any, *path: str) -> Any:
    """Walk a nested dict, returning None if any step is missing."""
    current = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _address_text(item: dict) -> str | None:
    parts = [
        _get(item, "address", "en", "street_name"),
        _get(item, "address", "en", "house_number"),
        _get(item, "address", "en", "city_name"),
    ]
    joined = " ".join(str(part) for part in parts if part)
    return joined or None


def _listing_url(item: dict, source_id: str) -> str:
    search_option = item.get("search_option") or "rent"
    slug = item.get("slug") or source_id
    return LISTING_URL.format(search_option=search_option, slug=slug)


def _parse_items(items: Any) -> list[Listing]:
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

        images = item.get("images") or []
        if not isinstance(images, list):
            images = []
        photos = [
            img.get("full")
            for img in images
            if isinstance(img, dict) and isinstance(img.get("full"), str)
        ]

        listings.append(
            Listing(
                source="onmap",
                source_id=source_id,
                url=_listing_url(item, source_id),
                price=_as_int(item.get("price")),
                rooms=_as_float(_get(item, "additional_info", "rooms")),
                size_sqm=_as_float(_get(item, "additional_info", "area", "base")),
                floor=_as_int(_get(item, "additional_info", "floor", "on_the")),
                city=_get(item, "address", "en", "city_name"),
                address_text=_address_text(item),
                lat=_as_float(_get(item, "address", "location", "lat")),
                lon=_as_float(_get(item, "address", "location", "lon")),
                photos=photos,
                # onmap's rent/rent-short/buy search only lists whole
                # properties; there is no roommate-ad category here.
                occupancy=Occupancy.WHOLE,
                posted_at=_as_datetime(item.get("created_at")),
            )
        )

    return listings


def parse_onmap_payload(payload: list | dict) -> list[Listing]:
    """Convert an onmap mixed_search response into Listings.

    Accepts either a bare list of items or a Feathers.js-style
    ``{"data": [...]}`` wrapper. Anything missing stays None rather than
    defaulting, so downstream filters can distinguish "not stated" from
    "stated as zero".
    """
    if isinstance(payload, dict):
        items = payload.get("data")
    else:
        items = payload
    return _parse_items(items)


class OnmapAdapter:
    name = "onmap"

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        try:
            url = config["url_template"].format(
                price_min=config.get("price_min", 0),
                price_max=config.get("price_max", 100000),
            )
        except (KeyError, IndexError) as exc:
            return AdapterResult(source=self.name, error=f"bad source config: {exc}")

        try:
            response = fetcher.get(url, min_tier=config.get("min_tier", "http"))
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return AdapterResult(source=self.name, error=f"fetch failed: {exc}")

        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            return AdapterResult(
                source=self.name, error=f"response was not JSON (tier {response.tier}): {exc}"
            )

        try:
            listings = parse_onmap_payload(payload)
        except Exception as exc:  # noqa: BLE001 - a shape change must not crash
            return AdapterResult(source=self.name, error=f"parse failed: {exc}")

        limit = config.get("max_results")
        if limit:
            listings = listings[:limit]
        return AdapterResult(source=self.name, listings=listings)
