from __future__ import annotations

import dataclasses
from datetime import datetime

from .models import Listing, Occupancy


def serialise_listing(listing: Listing) -> dict:
    """Listing -> JSON-safe dict.

    Shared by the pipeline's carry-forward cache and the local yad2 feed file
    - both need the exact same round-trip.
    """
    data = dataclasses.asdict(listing)
    for key in ("posted_at", "first_seen_at"):
        value = data[key]
        data[key] = value.isoformat() if value is not None else None
    data["occupancy"] = listing.occupancy.value
    return data


def deserialise_listing(data: dict) -> Listing:
    """Inverse of serialise_listing; raises on a malformed entry."""
    values = dict(data)
    for key in ("posted_at", "first_seen_at"):
        raw = values.get(key)
        values[key] = datetime.fromisoformat(raw) if raw else None
    values["occupancy"] = Occupancy(values.get("occupancy", Occupancy.UNSURE.value))
    return Listing(**values)
