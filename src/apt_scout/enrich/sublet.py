from __future__ import annotations

from ..normalise.text import normalise_text

# The user wants a long-term home, not a short-term or sublet arrangement.
# Sublet ads (סאבלט) show up regularly in the same feeds as ordinary rentals,
# so they need their own detector rather than being left to slip through the
# occupancy classifier, which answers a different question (whole apartment
# vs. a room in one).
#
# Substring matching means the shortest stem suffices: "סבלט" already covers
# מסבלט/מסבלטת/מסבלטים, and "טווח קצר" covers לטווח קצר.
SUBLET_TERMS = [
    "סאבלט",
    "סבלט",
    "sublet",
    "sub-let",
    "sublease",
    "השכרת משנה",
    "לתקופה קצרה",
    "טווח קצר",
]


def is_sublet_text(text: str | None) -> bool:
    """Whether free text reads as a sublet or short-term rental ad.

    Simple substring matching over normalised text, deliberately without
    negation handling (contrast with ``classify_occupancy``): a false
    positive here only routes the listing behind the ``/sublets`` toggle
    rather than discarding it, so the risk of over-flagging is low and does
    not justify the extra complexity.
    """
    cleaned = normalise_text(text).lower()
    if not cleaned:
        return False
    return any(term in cleaned for term in SUBLET_TERMS)
