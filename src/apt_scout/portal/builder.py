from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..filters import Filters
from ..models import Listing
from ..neighborhoods.knowledge import KnowledgeBase
from ..normalise.text import strip_phones

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
    "distance_km",
    "neighborhood",
    "photos",
    "occupancy",
    "is_sublet",
    "sources",
)

_WHITESPACE = re.compile(r"\s+")


def _scrub_free_text(text: str | None) -> str | None:
    """Strip phone numbers and collapse whitespace in free text fields.

    Preserves None as None. Returns None if text is empty after scrubbing.
    """
    if text is None:
        return None
    scrubbed = strip_phones(text)
    collapsed = _WHITESPACE.sub(" ", scrubbed).strip()
    return collapsed if collapsed else None


def listing_to_public_dict(listing: Listing) -> dict:
    """Project a Listing down to the fields safe to publish."""
    data: dict = {}
    for name in PUBLIC_FIELDS:
        value = getattr(listing, name)

        # Scrub phones from free-text fields
        if name in ("title", "address_text"):
            value = _scrub_free_text(value) if isinstance(value, str) else value

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
    knowledge: KnowledgeBase | None = None,
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

    # Profiles are joined client-side by id; notes/sources stay private.
    (output_dir / "data" / "neighborhoods.json").write_text(
        json.dumps(knowledge.public_dict() if knowledge else {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for asset in ("index.html", "app.js", "style.css"):
        shutil.copy(ASSETS / asset, output_dir / asset)

    shutil.copytree(ASSETS / "vendor", output_dir / "vendor", dirs_exist_ok=True)

    return output_dir / "data" / "listings.json"
