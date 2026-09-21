from __future__ import annotations

from ..normalise.price import parse_price
from ..normalise.text import normalise_text

# Group feeds mix offers with "looking for" posts. A seeker post opens with
# one of these and states no price; an offer that merely says "מחפשים
# שוכרים" almost always carries a price, which keeps it.
SEEKER_TERMS = [
    "מחפש דירה", "מחפשת דירה", "מחפשים דירה", "מחפש/ת", "דרושה דירה",
    "מעוניין לשכור", "מעוניינת לשכור",
    "looking for a", "looking for an", "wanted:",
]
_OPENING_CHARS = 200


def is_seeker_text(text: str | None) -> bool:
    cleaned = normalise_text(text).lower()
    if not cleaned:
        return False
    opening = cleaned[:_OPENING_CHARS]
    if not any(term in opening for term in SEEKER_TERMS):
        return False
    return parse_price(text) is None
