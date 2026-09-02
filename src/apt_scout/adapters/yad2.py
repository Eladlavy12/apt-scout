from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..fetch_browser import sniff_json
from ..models import Listing, Occupancy
from ..serialise import deserialise_listing
from .base import AdapterResult

# How long a local feed file is trusted before a fetch falls back to the
# network, when the source config doesn't override it.
DEFAULT_FEED_MAX_AGE_HOURS = 6

LISTING_URL = "https://www.yad2.co.il/realestate/item/{source_id}"

# Substring identifying the JSON API call the search page's frontend makes;
# used to pick that response out of everything else the page loads.
_API_CAPTURE_SUBSTRING = "realestate-feed/rent/map"

# Module-level reference so tests can monkeypatch the browser dependency
# without needing to fake playwright itself.
_sniff = sniff_json


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

    def _load_feed(self, config: dict) -> tuple[list[Listing], str] | None:
        """Read `config["feed_file"]` if it is present and fresh enough.

        The feed is produced by a PC-side job (yad2 blocks GitHub's IPs at
        every tier, but works from a real Chrome on the user's machine) and
        committed to the repo. Returns None for anything that should fall
        back to the normal network fetch: no feed configured, the file is
        missing, unreadable, or its `fetched_at` is too old.
        """
        feed_file = config.get("feed_file")
        if not feed_file:
            return None

        repo_root = Path(config.get("repo_root", "."))
        path = repo_root / feed_file
        if not path.exists():
            return None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None

        fetched_at_str = raw.get("fetched_at")
        if not isinstance(fetched_at_str, str):
            return None
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
        except ValueError:
            return None
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)

        max_age_hours = config.get("feed_max_age_hours", DEFAULT_FEED_MAX_AGE_HOURS)
        if datetime.now(timezone.utc) - fetched_at > timedelta(hours=max_age_hours):
            return None

        entries = raw.get("listings")
        if not isinstance(entries, list):
            return None

        listings: list[Listing] = []
        for entry in entries:
            try:
                listings.append(deserialise_listing(entry))
            except (TypeError, ValueError, KeyError):
                continue  # one corrupt entry must not discard the whole feed

        return listings, fetched_at_str

    def _browser_fallback(self, config: dict) -> tuple[dict | None, bool]:
        """Tier 2: drive a real browser through the search page and sniff the
        JSON it requests.

        Returns (payload, attempted). `attempted` is False when the fallback
        was skipped outright (disabled, or no usable page_url_template) so the
        caller can tell "we didn't try" from "we tried and it still failed" -
        only the latter should change the error message reported upstream.
        """
        if not config.get("browser_fallback", True):
            return None, False

        template = config.get("page_url_template")
        if not template:
            return None, False
        try:
            page_url = template.format(
                price_min=config.get("price_min", 0),
                price_max=config.get("price_max", 100000),
                rooms_min=config.get("rooms_min", 1),
            )
        except (KeyError, IndexError):
            return None, False

        text = _sniff(page_url, _API_CAPTURE_SUBSTRING)
        if text is None:
            return None, True
        try:
            return json.loads(text), True
        except json.JSONDecodeError:
            return None, True

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        feed = self._load_feed(config)
        if feed is not None:
            listings, fetched_at_str = feed
            limit = config.get("max_results")
            if limit:
                listings = listings[:limit]
            return AdapterResult(
                source=self.name,
                listings=listings,
                detail=f"local feed from {fetched_at_str}",
            )

        try:
            url = config["url_template"].format(
                price_min=config.get("price_min", 0),
                price_max=config.get("price_max", 100000),
                rooms_min=config.get("rooms_min", 1),
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
            tier1_error = f"response was not JSON (tier {response.tier}): {exc}"
            payload, attempted = self._browser_fallback(config)
            if payload is None:
                error = f"{tier1_error}; browser fallback also failed" if attempted else tier1_error
                return AdapterResult(source=self.name, error=error)

        try:
            listings = parse_yad2_payload(payload)
        except Exception as exc:  # noqa: BLE001 - a shape change must not crash
            return AdapterResult(source=self.name, error=f"parse failed: {exc}")

        limit = config.get("max_results")
        if limit:
            listings = listings[:limit]
        return AdapterResult(source=self.name, listings=listings)
