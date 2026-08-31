from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..models import Listing, Occupancy
from .base import AdapterResult

LISTING_URL = "https://www.yad2.co.il/realestate/item/{source_id}"


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


def _address_text(marker: dict) -> str | None:
    parts = [
        _get(marker, "address", "street", "text"),
        _get(marker, "address", "house", "number"),
        _get(marker, "address", "city", "text"),
    ]
    joined = " ".join(str(part) for part in parts if part)
    return joined or None


def _parse_markers(markers: Any) -> list[Listing]:
    listings: list[Listing] = []
    if not isinstance(markers, list):
        return listings

    for marker in markers:
        if not isinstance(marker, dict):
            continue
        # token is yad2's real listing identity (used in listing URLs); older
        # or degraded payloads may only carry orderId or id, so fall back.
        source_id = marker.get("token") or marker.get("orderId") or marker.get("id")
        if not source_id:
            continue
        source_id = str(source_id)

        photos = _get(marker, "metaData", "images") or []
        if not isinstance(photos, list):
            photos = []

        listings.append(
            Listing(
                source="yad2",
                source_id=source_id,
                url=LISTING_URL.format(source_id=source_id),
                price=_as_int(marker.get("price")),
                rooms=_as_float(_get(marker, "additionalDetails", "roomsCount")),
                size_sqm=_as_float(_get(marker, "additionalDetails", "squareMeter")),
                floor=_as_int(_get(marker, "address", "house", "floor")),
                city=_get(marker, "address", "city", "text"),
                address_text=_address_text(marker),
                lat=_as_float(_get(marker, "address", "coords", "lat")),
                lon=_as_float(_get(marker, "address", "coords", "lon")),
                photos=[p for p in photos if isinstance(p, str)],
                # yad2's rental apartment category is whole apartments only;
                # roommate ads live in a separate category we do not query.
                occupancy=Occupancy.WHOLE,
            )
        )

    return listings


def parse_yad2_payload(payload: dict) -> list[Listing]:
    """Convert a yad2 search response into Listings.

    Anything missing stays None rather than defaulting, so downstream filters
    can distinguish "not stated" from "stated as zero". Both `data.markers`
    (organic results) and `data.agencyPromotions` (paid agency listings) are
    real inventory and are concatenated, markers first. `clusters`,
    `grayMarkers`, `yad1Markers`, and `yad1Promotions` are ignored: clusters
    are map-zoom aggregations with no single listing identity, grayMarkers are
    yad2's own "already seen" markers, and the yad1* entries belong to a
    different (non-yad2) listing pool.
    """
    markers = _get(payload, "data", "markers")
    agency_promotions = _get(payload, "data", "agencyPromotions")
    return _parse_markers(markers) + _parse_markers(agency_promotions)


class Yad2Adapter:
    name = "yad2"

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        url = config["url_template"].format(
            price_min=config.get("price_min", 0),
            price_max=config.get("price_max", 100000),
            rooms_min=config.get("rooms_min", 1),
        )
        try:
            response = fetcher.get(url, min_tier=config.get("min_tier", "http"))
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return AdapterResult(source=self.name, error=f"fetch failed: {exc}")

        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            return AdapterResult(
                source=self.name,
                error=f"response was not JSON (tier {response.tier}): {exc}",
            )

        try:
            listings = parse_yad2_payload(payload)
        except Exception as exc:  # noqa: BLE001 - a shape change must not crash
            return AdapterResult(source=self.name, error=f"parse failed: {exc}")

        limit = config.get("max_results")
        if limit:
            listings = listings[:limit]
        return AdapterResult(source=self.name, listings=listings)
