from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..models import Listing, Occupancy
from ..normalise.price import parse_price
from ..normalise.rooms import parse_rooms
from ..normalise.size import parse_size
from ..normalise.text import extract_phone, hash_phone
from ..state import StateStore
from .distance import distance_from_centre_km
from .drivetime import DriveTimeCalculator
from .geocode import Geocoder
from .occupancy import classify_occupancy

Enricher = Callable[[Listing], Listing]


def _fill_from_text(listing: Listing) -> Listing:
    """Recover fields the source did not state, from its free text.

    Only fills gaps. A value the source stated explicitly is always more
    trustworthy than one scraped out of prose.
    """
    text = listing.raw_text or listing.title
    if not text:
        return listing

    if listing.price is None:
        listing.price = parse_price(text)
    if listing.rooms is None:
        listing.rooms = parse_rooms(text)
    if listing.size_sqm is None:
        listing.size_sqm = parse_size(text)
    return listing


def _classify(listing: Listing) -> Listing:
    """Resolve occupancy from text, but only when the source did not tell us."""
    if listing.occupancy is Occupancy.UNSURE:
        text = " ".join(filter(None, [listing.title, listing.raw_text]))
        listing.occupancy = classify_occupancy(text)
    return listing


def _make_phone_hasher(salt: str) -> Enricher:
    def hash_listing_phone(listing: Listing) -> Listing:
        text = " ".join(filter(None, [listing.title, listing.raw_text]))
        phone = extract_phone(text)
        if phone:
            listing.phone_hash = hash_phone(phone, salt)
        return listing

    return hash_listing_phone


def _make_geocoder_step(geocoder: Any) -> Enricher:
    def add_coordinates(listing: Listing) -> Listing:
        if listing.lat is not None and listing.lon is not None:
            return listing
        coords = geocoder.geocode(listing.address_text or listing.city)
        if coords:
            listing.lat, listing.lon = coords
        return listing

    return add_coordinates


def _make_drive_step(drive: Any) -> Enricher:
    def add_drive_time(listing: Listing) -> Listing:
        if listing.lat is None or listing.lon is None:
            return listing
        listing.drive_minutes = drive.minutes_from_centre(listing.lat, listing.lon)
        return listing

    return add_drive_time


def _add_distance(listing: Listing) -> Listing:
    """Straight-line distance from the centre point, as a hard cap.

    OSRM's drive time is free-flow (no traffic), which can let distant
    addresses slide under the minutes threshold. This is cheap, local math
    that runs regardless of that.
    """
    listing.distance_km = distance_from_centre_km(listing.lat, listing.lon)
    return listing


def build_enrichers(
    store: StateStore,
    salt: str,
    geocoder: Any = None,
    drive: Any = None,
) -> list[Enricher]:
    """Assemble the enrichment chain, in dependency order.

    Text parsing runs first because it can supply the address that geocoding
    needs; geocoding runs before drive time because drive time needs coordinates.
    """
    geocoder = geocoder or Geocoder(store)
    drive = drive or DriveTimeCalculator(store)
    return [
        _fill_from_text,
        _classify,
        _make_phone_hasher(salt),
        _make_geocoder_step(geocoder),
        _add_distance,
        _make_drive_step(drive),
    ]
