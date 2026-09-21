from __future__ import annotations

import re

from .text import normalise_text

ROOMS_MIN = 0.5
ROOMS_MAX = 15.0

_ROOM_WORD = r"(?:חדרים|חדרי|חדר|חד['׳\"]?)"

_NUMBER_AND_HALF = re.compile(rf"(\d+)\s*ו?\s*חצי\s*{_ROOM_WORD}")
_NUMBER_THEN_HALF = re.compile(rf"(\d+)\s*{_ROOM_WORD}\s*ו?\s*חצי")
_ONE_AND_HALF = re.compile(rf"{_ROOM_WORD}\s*ו?\s*חצי")
_PLAIN = re.compile(rf"(\d+(?:[.,]\d+)?)\s*{_ROOM_WORD}")

# Wording that means a one-room / studio apartment without stating a digit.
# Checked last, so any explicit count ("דירת סטודיו 3 חדרים") wins. Without
# this, such ads have rooms=None and slip past the minimum-rooms filter,
# which fails open on unknown values. Every alternative is anchored to an
# apartment context: a bare "סטודיו" would also match an art studio in the
# building, and a bare "חדר אחד" a description of one room among several -
# either would silently drop a real multi-room flat. "דירת חדר" must not
# match "דירת חדרים" (a plural, i.e. an unspecified multi-room flat).
_ONE_ROOM = re.compile(
    r"דירת חדר(?![א-ת])"
    r"|דירת חדר אחד"
    r"|דירה של חדר אחד"
    r"|חדר אחד בלבד"
    r"|דירת סטודיו"
    r"|סטודיו (?:להשכרה|למגורים)"
    r"|דירת גלריה"
    r"|\bstudio (?:apartment|apt|flat|unit)\b"
    r"|\bstudio for rent\b"
    r"|\b(?:1|one)[ -]room (?:apartment|apt|flat)\b",
    re.IGNORECASE,
)


def parse_rooms(text: str | None) -> float | None:
    """Extract an Israeli room count, including half-rooms, or None."""
    if not text:
        return None
    cleaned = normalise_text(text)

    match = _NUMBER_AND_HALF.search(cleaned)
    if match:
        return _validate(float(match.group(1)) + 0.5)

    # "3 חדרים וחצי" — a digit before the room word takes precedence over the
    # bare "one and a half" reading.
    match = _NUMBER_THEN_HALF.search(cleaned)
    if match:
        return _validate(float(match.group(1)) + 0.5)

    if _ONE_AND_HALF.search(cleaned):
        return 1.5

    match = _PLAIN.search(cleaned)
    if match:
        return _validate(float(match.group(1).replace(",", ".")))

    if _ONE_ROOM.search(cleaned):
        return 1.0

    return None


def _validate(value: float) -> float | None:
    return value if ROOMS_MIN <= value <= ROOMS_MAX else None
