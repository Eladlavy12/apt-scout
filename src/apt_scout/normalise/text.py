from __future__ import annotations

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")

# Hebrew vowel points and cantillation marks. Stripping them makes keyword
# matching reliable regardless of how the poster typed the text.
_NIQQUD = re.compile(r"[֑-ׇ]")

_PHONE_PATTERNS = [
    re.compile(r"\+972[-\s]?(\d{1,2})[-\s]?(\d{3})[-\s]?(\d{4})"),
    re.compile(r"\b0(\d{1,2})[-\s]?(\d{3})[-\s]?(\d{4})\b"),
]


def normalise_text(text: str | None) -> str:
    """Collapse whitespace and strip Hebrew diacritics."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = _NIQQUD.sub("", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


def strip_phones(text: str) -> str:
    """Blank out phone numbers so they cannot be mistaken for prices."""
    for pattern in _PHONE_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def extract_phone(text: str | None) -> str | None:
    """Return the first Israeli phone number as +972XXXXXXXXX, or None."""
    if not text:
        return None
    for pattern in _PHONE_PATTERNS:
        match = pattern.search(text)
        if match:
            return "+972" + "".join(match.groups())
    return None


def hash_phone(phone: str, salt: str) -> str:
    """Salted hash of a phone number.

    Phone numbers are used for cross-source matching but must never reach the
    public portal, so only this hash is ever stored.
    """
    return hashlib.sha256(f"{salt}:{phone}".encode()).hexdigest()[:32]
