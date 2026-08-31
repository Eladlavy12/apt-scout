from __future__ import annotations

import re

from .text import normalise_text, strip_phones

# A monthly rent outside this range is almost certainly something else on the
# page: a floor number, a building committee fee, or a sale price.
PRICE_MIN = 1000
PRICE_MAX = 50000

_CURRENCY = r'(?:₪|ש"ח|ש״ח|שח|שקל|שקלים|nis)'
_NUMBER = r"\d[\d,]*(?:\.\d+)?"

_PRICE_PATTERNS = [
    re.compile(rf"₪\s*({_NUMBER})"),
    re.compile(rf"({_NUMBER})\s*{_CURRENCY}", re.IGNORECASE),
]
_K_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE)


def _to_int(raw: str) -> int | None:
    cleaned = raw.replace(",", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def parse_price(text: str | None) -> int | None:
    """Extract a monthly rent in shekels from free text.

    Returns the first plausible price found, or None. Phone numbers are removed
    first so a number like 050-1234567 cannot be misread.
    """
    if not text:
        return None
    cleaned = strip_phones(normalise_text(text))

    matches: list[tuple[int, int]] = []
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(cleaned):
            value = _to_int(match.group(1))
            if value is not None:
                matches.append((match.start(), value))
    for match in _K_PATTERN.finditer(cleaned):
        matches.append((match.start(), int(float(match.group(1)) * 1000)))

    for _, value in sorted(matches):
        if PRICE_MIN <= value <= PRICE_MAX:
            return value
    return None
