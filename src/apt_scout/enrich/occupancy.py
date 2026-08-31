from __future__ import annotations

from ..models import Occupancy
from ..normalise.text import normalise_text

# Phrases that mean "no roommates" and therefore indicate a whole apartment,
# despite containing a roommate word. These are removed before matching, so
# order matters: negations are stripped first.
NEGATION_PHRASES = [
    "ללא שותפים",
    "ללא שותף",
    "ללא שותפה",
    "בלי שותפים",
    "בלי שותף",
    "לא שותפים",
    "no roommates",
]

ROOMMATE_TERMS = [
    "שותף",
    "שותפה",
    "שותפים",
    "שותפות",
    "חדר בדירה",
    "חדר בדירת",
    "roommate",
    "flatmate",
    "room in",
]

WHOLE_TERMS = [
    "דירה",
    "דירת",
    "apartment",
    "flat",
]


def classify_occupancy(text: str | None) -> Occupancy:
    """Decide whether a listing is a whole apartment or a room in a shared one.

    Returns UNSURE rather than guessing. Unsure listings are surfaced to the
    user behind a toggle and re-classified later by the daily agent, which is
    preferable to silently discarding a good apartment.
    """
    cleaned = normalise_text(text).lower()
    if not cleaned:
        return Occupancy.UNSURE

    for phrase in NEGATION_PHRASES:
        cleaned = cleaned.replace(phrase, " ")

    if any(term in cleaned for term in ROOMMATE_TERMS):
        return Occupancy.ROOMMATES

    if any(term in cleaned for term in WHOLE_TERMS):
        return Occupancy.WHOLE

    return Occupancy.UNSURE
