from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Occupancy(str, Enum):
    """Whether a listing is for a whole apartment or a room in a shared one."""

    WHOLE = "whole"
    ROOMMATES = "roommates"
    UNSURE = "unsure"


@dataclass
class Listing:
    """A single apartment advertisement from one source.

    Every optional field is None when the source did not state it or it could
    not be parsed confidently. Fields are never guessed.
    """

    source: str
    source_id: str
    url: str

    title: str | None = None
    raw_text: str | None = None

    price: int | None = None
    rooms: float | None = None
    size_sqm: float | None = None
    floor: int | None = None

    address_text: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    drive_minutes: float | None = None
    distance_km: float | None = None

    photos: list[str] = field(default_factory=list)
    phone_hash: str | None = None

    occupancy: Occupancy = Occupancy.UNSURE

    posted_at: datetime | None = None
    first_seen_at: datetime | None = None

    # Populated by clustering: every source that advertised this apartment.
    # Empty for a listing that hasn't gone through the cluster stage yet.
    sources: list[str] = field(default_factory=list)

    def stable_id(self) -> str:
        """Identity of this advertisement, unique across sources."""
        return f"{self.source}:{self.source_id}"

    @property
    def price_missing(self) -> bool:
        return self.price is None
