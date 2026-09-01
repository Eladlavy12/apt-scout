from __future__ import annotations

import hashlib
import re
from collections import Counter
from urllib.parse import urlsplit, urlunsplit

from apt_scout.models import Listing
from apt_scout.normalise.text import extract_phone, hash_phone, normalise_text

# Known listing-board hosts whose URLs, when cross-posted into another
# source's raw text, prove the same apartment is being advertised twice.
_EXTURL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:yad2\.co\.il|madlan\.co\.il|onmap\.co\.il)/\S+",
    re.IGNORECASE,
)

# Trailing characters that tend to get glued onto a URL when it is embedded
# in free-form prose (Hebrew punctuation, closing brackets, quotes, etc.).
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}\"'־"

_TOKEN_PATTERN = re.compile(r"\S+")

# The similarity key only kicks in once there is enough text for a handful
# of rare tokens to mean something; short snippets are too noisy.
_MIN_TEXT_LENGTH_FOR_SIMILARITY = 40
_RARE_TOKEN_COUNT = 8
_MIN_TOKEN_LENGTH = 3


def _normalise_exturl(raw_url: str) -> str:
    """Lowercase scheme/host and drop the query string, per the brief."""
    url = raw_url.rstrip(_URL_TRAILING_PUNCTUATION)
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def _extract_exturls(raw_text: str) -> list[str]:
    return [_normalise_exturl(match.group(0)) for match in _EXTURL_PATTERN.finditer(raw_text)]


def _size_bucket(size_sqm: float | None) -> str:
    """10-sqm bucket, e.g. 65 -> "6". Empty string when size is unknown so
    listings that agree on price+rooms but differ only by a missing size
    still get a (looser) struct key instead of none at all. That looser,
    empty-bucket key is only emitted for listings that carry a real address
    (see `fingerprints`): an address-less price+rooms-only match is too weak
    to count as a dedup signal."""
    if size_sqm is None:
        return ""
    return str(int(size_sqm // 10))


def _has_listing_precise_location(listing: Listing) -> bool:
    """Whether this listing's coordinates plausibly point at the listing
    itself rather than at a city centroid.

    Address-less listings are geocoded from their city alone, which lands
    every one of them on the exact same centroid: identical `geo:` keys that
    prove nothing. Coordinates only count as a dedup signal when the listing
    has an address whose normalised form differs from its city name."""
    if not listing.address_text:
        return False
    return normalise_text(listing.address_text) != normalise_text(listing.city)


def _text_similarity_key(raw_text: str) -> str | None:
    """A deterministic key built from the rarest tokens of the text.

    "Rarest" is scoped to this single listing's own text (there is no
    corpus-wide document frequency here): a token is rarer the fewer times
    it repeats in this text, tie-broken by longer tokens first (they carry
    more distinguishing signal) and then alphabetically for determinism.
    Sorting the chosen tokens before hashing makes the key independent of
    word order, so two listings with the same words in a different order
    still produce an identical key.
    """
    normalised = normalise_text(raw_text)
    if len(normalised) < _MIN_TEXT_LENGTH_FOR_SIMILARITY:
        return None
    tokens = [t for t in _TOKEN_PATTERN.findall(normalised) if len(t) >= _MIN_TOKEN_LENGTH]
    if not tokens:
        return None
    counts = Counter(tokens)
    ranked = sorted(set(tokens), key=lambda t: (counts[t], -len(t), t))
    rarest = sorted(ranked[:_RARE_TOKEN_COUNT])
    blob = "|".join(rarest)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def fingerprints(listing: Listing, salt: str) -> dict[str, list[str]]:
    """Strong and weak identity signals for cross-source deduplication.

    Strong signals (phone, external URL) are near-certain proof of the same
    apartment; any single shared strong fingerprint is enough to merge two
    listings. Weak signals (structural stats, geo cell, text similarity) are
    individually circumstantial; the engine merges on two or more distinct
    shared weak fingerprints.

    Address-less listings get extra caution: their coordinates come from
    geocoding the city name alone, so every such listing in a city shares
    the exact same centroid `geo:` key. The `geo:` key is therefore only
    emitted when the listing has an address that differs from its city
    (see _has_listing_precise_location), and the size-less, empty-bucket
    `struct:` key is likewise withheld without an address - otherwise two
    unrelated same-city listings that merely agree on price+rooms would
    share two weak keys and be merged (then permanently marked notified).
    """
    raw_text = listing.raw_text or ""
    strong: list[str] = []
    weak: list[str] = []

    phone = extract_phone(raw_text) or extract_phone(listing.title)
    if phone:
        strong.append(f"phone:{hash_phone(phone, salt)}")

    for exturl in _extract_exturls(raw_text):
        strong.append(f"exturl:{exturl}")

    if listing.price is not None and listing.rooms is not None:
        if listing.size_sqm is not None or listing.address_text:
            weak.append(
                f"struct:{listing.price}|{listing.rooms}|{_size_bucket(listing.size_sqm)}"
            )

    if (
        listing.lat is not None
        and listing.lon is not None
        and _has_listing_precise_location(listing)
    ):
        weak.append(f"geo:{listing.lat:.3f},{listing.lon:.3f}")

    text_key = _text_similarity_key(raw_text)
    if text_key is not None:
        weak.append(f"text:{text_key}")

    return {"strong": strong, "weak": weak}
