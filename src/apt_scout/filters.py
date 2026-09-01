from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

from .models import Listing, Occupancy


@dataclass
class Filters:
    """Thresholds that decide which listings are worth a notification.

    Distinct from the portal's view filters: this gates alerts, the portal
    gates display. Keeping them separate lets the user browse more loosely
    than they are interrupted.
    """

    min_price: int = 4000
    max_price: int = 5500
    min_rooms: float = 2
    min_size_sqm: float = 50
    max_drive_minutes: float = 15
    max_distance_km: float = 5.0
    include_price_missing: bool = True
    include_unsure_occupancy: bool = True
    paused: bool = False

    @classmethod
    def load(cls, path: Path) -> "Filters":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def matches(self, listing: Listing) -> bool:
        """Whether this listing should trigger an alert.

        Unknown values do not disqualify, except price, which has an explicit
        toggle. Failing closed on missing data would discard most free-text
        listings, which is exactly the content this system exists to surface.
        """
        if self.paused:
            return False

        if listing.occupancy is Occupancy.ROOMMATES:
            return False
        if listing.occupancy is Occupancy.UNSURE and not self.include_unsure_occupancy:
            return False

        if listing.price is None:
            if not self.include_price_missing:
                return False
        elif not (self.min_price <= listing.price <= self.max_price):
            return False

        if listing.rooms is not None and listing.rooms < self.min_rooms:
            return False

        if listing.size_sqm is not None and listing.size_sqm < self.min_size_sqm:
            return False

        if (
            listing.drive_minutes is not None
            and listing.drive_minutes > self.max_drive_minutes
        ):
            return False

        if (
            listing.distance_km is not None
            and listing.distance_km > self.max_distance_km
        ):
            return False

        return True
