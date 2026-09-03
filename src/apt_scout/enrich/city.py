from __future__ import annotations

import re

# The three cities the user cares about, in preference order. Every other
# city keeps whatever string the source supplied.
CANONICAL_CITIES = ("תל אביב יפו", "גבעתיים", "רמת גן")

# Sources spell the same city many ways (hyphens, Yafo suffix, English,
# a trailing ", TA" region code from Facebook Marketplace). Everything is
# lower-cased, punctuation-stripped and whitespace-collapsed before lookup,
# so this table lists the *normalised* spellings.
_ALIASES = {
    "תל אביב יפו": CANONICAL_CITIES[0],
    "תל אביב": CANONICAL_CITIES[0],
    "ת א": CANONICAL_CITIES[0],
    "תא": CANONICAL_CITIES[0],
    "יפו": CANONICAL_CITIES[0],
    "tel aviv yafo": CANONICAL_CITIES[0],
    "tel aviv jaffa": CANONICAL_CITIES[0],
    "tel aviv": CANONICAL_CITIES[0],
    "גבעתיים": CANONICAL_CITIES[1],
    "givatayim": CANONICAL_CITIES[1],
    "giv atayim": CANONICAL_CITIES[1],
    "givataim": CANONICAL_CITIES[1],
    "רמת גן": CANONICAL_CITIES[2],
    "ramat gan": CANONICAL_CITIES[2],
}

_REGION_SUFFIX = re.compile(r",\s*[A-Za-z]{1,3}\s*$")
_PUNCTUATION = re.compile(r"[\-–—'\"׳״.]+")
_WHITESPACE = re.compile(r"\s+")


def _key(text: str) -> str:
    cleaned = _REGION_SUFFIX.sub("", text)
    cleaned = _PUNCTUATION.sub(" ", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip().lower()


def normalise_city(text: str | None) -> str | None:
    """Map a source's city spelling to one of CANONICAL_CITIES, else None."""
    if not text:
        return None
    return _ALIASES.get(_key(text))
