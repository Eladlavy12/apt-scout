from __future__ import annotations

import re

from .text import normalise_text

SIZE_MIN = 10.0
SIZE_MAX = 1000.0

_SIZE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:מ"ר|מ״ר|מ\'\'ר|מר\b|מטר\s*רבוע|sqm|sq\.?m|m2|מ2)',
    re.IGNORECASE,
)


def parse_size(text: str | None) -> float | None:
    """Extract apartment size in square metres, or None."""
    if not text:
        return None
    match = _SIZE.search(normalise_text(text))
    if not match:
        return None
    value = float(match.group(1))
    return value if SIZE_MIN <= value <= SIZE_MAX else None
