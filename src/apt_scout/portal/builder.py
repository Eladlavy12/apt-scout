from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from ..filters import Filters
from ..models import Listing

ASSETS = Path(__file__).parent / "assets"

# The published portal carries only these fields. Everything else — raw post
# text, phone hashes — stays in private state. This allowlist is the mechanism
# that makes the no-contact-details rule enforceable rather than aspirational.
PUBLIC_FIELDS = (
    "source",
    "source_id",
    "url",
    "title",
    "price",
    "rooms",
    "size_sqm",
    "floor",
    "address_text",
    "city",
    "lat",
    "lon",
    "drive_minutes",
    "photos",
    "occupancy",
)


def listing_to_public_dict(listing: Listing) -> dict:
    """Project a Listing down to the fields safe to publish."""
    data: dict = {}
    for name in PUBLIC_FIELDS:
        value = getattr(listing, name)
        data[name] = value.value if hasattr(value, "value") else value

    for name in ("posted_at", "first_seen_at"):
        moment: datetime | None = getattr(listing, name)
        data[name] = moment.isoformat() if moment else None

    return data


def build_portal(
    output_dir: Path,
    listings: list[Listing],
    health: dict,
    filters: Filters,
    generated_at: datetime,
) -> Path:
    """Generate the static portal into output_dir."""
    output_dir = Path(output_dir)
    (output_dir / "data").mkdir(parents=True, exist_ok=True)

    ordered = sorted(
        listings,
        key=lambda item: item.first_seen_at.isoformat() if item.first_seen_at else "",
        reverse=True,
    )

    payload = {
        "generated_at": generated_at.isoformat(),
        "defaults": filters.to_dict(),
        "health": health,
        "listings": [listing_to_public_dict(item) for item in ordered],
    }

    (output_dir / "data" / "listings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for asset in ("index.html", "app.js", "style.css"):
        shutil.copy(ASSETS / asset, output_dir / asset)

    shutil.copytree(ASSETS / "vendor", output_dir / "vendor", dirs_exist_ok=True)

    return output_dir / "data" / "listings.json"
