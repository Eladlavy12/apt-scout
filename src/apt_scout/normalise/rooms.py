from __future__ import annotations

import re

from .text import normalise_text

ROOMS_MIN = 0.5
ROOMS_MAX = 15.0

_ROOM_WORD = r"(?:חדרים|חדרי|חדר|חד['׳\"]?)"

_NUMBER_AND_HALF = re.compile(rf"(\d+)\s*ו?\s*חצי\s*{_ROOM_WORD}")
_ONE_AND_HALF = re.compile(rf"{_ROOM_WORD}\s*ו?\s*חצי")
_PLAIN = re.compile(rf"(\d+(?:[.,]\d+)?)\s*{_ROOM_WORD}")


def parse_rooms(text: str | None) -> float | None:
    """Extract an Israeli room count, including half-rooms, or None."""
    if not text:
        return None
    cleaned = normalise_text(text)

    match = _NUMBER_AND_HALF.search(cleaned)
    if match:
        return _validate(float(match.group(1)) + 0.5)

    if _ONE_AND_HALF.search(cleaned):
        return 1.5

    match = _PLAIN.search(cleaned)
    if match:
        return _validate(float(match.group(1).replace(",", ".")))

    return None


def _validate(value: float) -> float | None:
    return value if ROOMS_MIN <= value <= ROOMS_MAX else None
