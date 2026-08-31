# APT-Scout Phases 1–3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosting apartment scout that scrapes yad2 hourly on GitHub Actions, filters listings by price/rooms/size/occupancy and real driving time from a fixed centre point, alerts the user on Telegram, and publishes a static portal with instant client-side filters.

**Architecture:** A pure-function core (parsers, filters, classifiers) wrapped by thin I/O adapters. A tiered fetch layer isolates every network call so bot-protection changes are configuration, not code. State is JSON committed back to the repository by the Actions run, so there is no database. The portal is a static site with all filtering done in the browser.

**Tech Stack:** Python 3.11, httpx, pytest, GitHub Actions, vanilla JS + Leaflet for the portal. No framework, no database, no server.

## Global Constraints

- Python 3.11 or later. Type hints on all public functions.
- **No contact details may ever be written to `site/`.** Phone numbers exist only as salted hashes. This is a hard rule, checked by a test.
- Unknown field values are `None`, never guessed or defaulted.
- Missing data fails *open* in filters (does not disqualify a listing), except price, which has an explicit toggle. Rationale: failing closed would silently discard most free-text listings.
- Every network call goes through `Fetcher`. No adapter calls `httpx` directly.
- Every adapter failure is caught and recorded; one failing source never fails a run.
- Secrets come from environment variables only, never from committed files.
- Centre point is `32.056581, 34.804087` (Ort Singalovski, Tel Aviv).
- Currency is ILS throughout; prices are integers.
- All committed JSON is written with `ensure_ascii=False`, `indent=2`, and sorted keys so diffs are readable.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dependencies, pytest config |
| `src/apt_scout/models.py` | `Listing` dataclass and `Occupancy` enum — the shared vocabulary |
| `src/apt_scout/normalise/text.py` | Hebrew text normalisation, phone extraction/hashing |
| `src/apt_scout/normalise/price.py` | Price parsing from free text |
| `src/apt_scout/normalise/rooms.py` | Room-count parsing including half-rooms |
| `src/apt_scout/normalise/size.py` | Square-metre parsing |
| `src/apt_scout/enrich/occupancy.py` | Whole-apartment vs roommate classification |
| `src/apt_scout/enrich/geocode.py` | Nominatim geocoding with cache and rate limit |
| `src/apt_scout/enrich/drivetime.py` | OSRM driving time with cache |
| `src/apt_scout/fetch.py` | Tiered fetch layer (headers → browser → apify) |
| `src/apt_scout/adapters/base.py` | `SourceAdapter` protocol and `AdapterResult` |
| `src/apt_scout/adapters/yad2.py` | yad2 adapter: URL building and JSON parsing |
| `src/apt_scout/state.py` | Atomic JSON state store |
| `src/apt_scout/filters.py` | Alert threshold config and matching |
| `src/apt_scout/health.py` | Per-source success/failure tracking |
| `src/apt_scout/notify/telegram.py` | Telegram bot notifier and update polling |
| `src/apt_scout/notify/commands.py` | Parsing and applying `/price`-style commands |
| `src/apt_scout/portal/builder.py` | Static site generation |
| `src/apt_scout/portal/assets/` | `index.html`, `app.js`, `style.css` |
| `src/apt_scout/portal/assets/vendor/` | Vendored Leaflet, so the page has no third-party script |
| `src/apt_scout/pipeline.py` | Orchestration: fetch → enrich → filter → notify → build |
| `config/filters.json` | Alert thresholds |
| `config/sources.json` | Per-source URLs, cadence, fetch tier |
| `.github/workflows/scan.yml` | Hourly run and state commit |

---

## Task 1: Project skeleton and the Listing model

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/apt_scout/__init__.py`, `src/apt_scout/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Listing` dataclass, `Occupancy` enum, `Listing.stable_id() -> str`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "apt-scout"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.coverage
.venv/
venv/
site/
```

Note `site/` is ignored locally; the Actions workflow publishes it to the
`gh-pages` branch rather than committing it to `master`.

- [ ] **Step 3: Write the failing test**

Create `tests/test_models.py`:

```python
from apt_scout.models import Listing, Occupancy


def make_listing(**overrides) -> Listing:
    defaults = dict(source="yad2", source_id="abc123", url="https://y.co/1")
    defaults.update(overrides)
    return Listing(**defaults)


def test_listing_defaults_unknown_fields_to_none():
    listing = make_listing()
    assert listing.price is None
    assert listing.rooms is None
    assert listing.size_sqm is None
    assert listing.drive_minutes is None
    assert listing.photos == []
    assert listing.occupancy is Occupancy.UNSURE


def test_stable_id_combines_source_and_source_id():
    assert make_listing().stable_id() == "yad2:abc123"


def test_stable_id_differs_across_sources_for_same_source_id():
    a = make_listing(source="yad2")
    b = make_listing(source="madlan")
    assert a.stable_id() != b.stable_id()


def test_price_missing_is_true_when_price_is_none():
    assert make_listing().price_missing is True
    assert make_listing(price=4500).price_missing is False
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout'`

- [ ] **Step 5: Implement the model**

Create `src/apt_scout/__init__.py` as an empty file, then `src/apt_scout/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Occupancy(str, Enum):
    """Whether a listing is for a whole apartment or a room in a shared one."""

    WHOLE = "whole"
    ROOMMATES = "roommates"
    UNSURE = "unsure"


@dataclass
class Listing:
    """A single apartment advertisement from one source.

    Every optional field is None when the source did not state it or it could
    not be parsed confidently. Fields are never guessed.
    """

    source: str
    source_id: str
    url: str

    title: str | None = None
    raw_text: str | None = None

    price: int | None = None
    rooms: float | None = None
    size_sqm: float | None = None
    floor: int | None = None

    address_text: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    drive_minutes: float | None = None

    photos: list[str] = field(default_factory=list)
    phone_hash: str | None = None

    occupancy: Occupancy = Occupancy.UNSURE

    posted_at: datetime | None = None
    first_seen_at: datetime | None = None

    def stable_id(self) -> str:
        """Identity of this advertisement, unique across sources."""
        return f"{self.source}:{self.source_id}"

    @property
    def price_missing(self) -> bool:
        return self.price is None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS, 4 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore src/apt_scout/__init__.py src/apt_scout/models.py tests/test_models.py
git commit -m "feat: add project skeleton and Listing model"
```

---

## Task 2: Hebrew text, price, rooms, and size parsing

These four parsers are one task because they share the same normalisation
helper and the same class of failure. A reviewer would accept or reject them
together.

**Files:**
- Create: `src/apt_scout/normalise/__init__.py`, `text.py`, `price.py`, `rooms.py`, `size.py`
- Test: `tests/test_normalise.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `normalise_text(text: str | None) -> str`
  - `extract_phone(text: str | None) -> str | None` (returns `+9725XXXXXXXX`)
  - `hash_phone(phone: str, salt: str) -> str`
  - `parse_price(text: str | None) -> int | None`
  - `parse_rooms(text: str | None) -> float | None`
  - `parse_size(text: str | None) -> float | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_normalise.py`:

```python
from apt_scout.normalise.price import parse_price
from apt_scout.normalise.rooms import parse_rooms
from apt_scout.normalise.size import parse_size
from apt_scout.normalise.text import extract_phone, hash_phone, normalise_text


class TestNormaliseText:
    def test_collapses_whitespace(self):
        assert normalise_text("a   b\n\nc") == "a b c"

    def test_handles_none(self):
        assert normalise_text(None) == ""

    def test_strips_niqqud(self):
        assert normalise_text("שָׁלוֹם") == "שלום"


class TestParsePrice:
    def test_shekel_sign_before_number(self):
        assert parse_price("₪4500 לחודש") == 4500

    def test_shekel_sign_after_number_with_comma(self):
        assert parse_price("4,500 ₪") == 4500

    def test_hebrew_currency_word(self):
        assert parse_price('המחיר 5000 ש"ח') == 5000

    def test_shach_without_quotes(self):
        assert parse_price("5200 שח כולל ועד") == 5200

    def test_k_notation(self):
        assert parse_price("4.5k a month") == 4500

    def test_ignores_phone_numbers(self):
        assert parse_price("לפרטים 050-1234567") is None

    def test_ignores_implausible_values(self):
        assert parse_price("קומה 3 ₪") is None

    def test_returns_none_when_no_price(self):
        assert parse_price("דירה יפה במרכז") is None

    def test_returns_none_for_empty(self):
        assert parse_price(None) is None

    def test_takes_first_plausible_price_not_the_extras(self):
        assert parse_price('4500 ש"ח + ועד בית 250 ש"ח') == 4500


class TestParseRooms:
    def test_whole_rooms(self):
        assert parse_rooms("3 חדרים") == 3.0

    def test_half_rooms_decimal(self):
        assert parse_rooms("3.5 חדרים") == 3.5

    def test_abbreviated_form(self):
        assert parse_rooms("2 חד'") == 2.0

    def test_word_form_half(self):
        assert parse_rooms("3 וחצי חדרים") == 3.5

    def test_single_room_and_a_half(self):
        assert parse_rooms("חדר וחצי להשכרה") == 1.5

    def test_rejects_implausible_counts(self):
        assert parse_rooms("40 חדרים") is None

    def test_returns_none_when_absent(self):
        assert parse_rooms("דירה להשכרה") is None


class TestParseSize:
    def test_standard_hebrew_unit(self):
        assert parse_size('75 מ"ר') == 75.0

    def test_geresh_variant(self):
        assert parse_size("75 מ״ר") == 75.0

    def test_without_quotes(self):
        assert parse_size("80 מר") == 80.0

    def test_english_unit(self):
        assert parse_size("65 sqm") == 65.0

    def test_returns_none_when_absent(self):
        assert parse_size("דירה גדולה") is None


class TestPhone:
    def test_extracts_mobile_with_dash(self):
        assert extract_phone("לפרטים 050-1234567") == "+972501234567"

    def test_extracts_mobile_without_dash(self):
        assert extract_phone("0521234567") == "+972521234567"

    def test_extracts_international_form(self):
        assert extract_phone("+972-52-1234567") == "+972521234567"

    def test_returns_none_when_absent(self):
        assert extract_phone("דירה להשכרה") is None

    def test_hash_is_stable_and_salted(self):
        a = hash_phone("+972501234567", salt="s1")
        b = hash_phone("+972501234567", salt="s1")
        c = hash_phone("+972501234567", salt="s2")
        assert a == b
        assert a != c
        assert "972" not in a
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_normalise.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.normalise'`

- [ ] **Step 3: Implement `text.py`**

Create `src/apt_scout/normalise/__init__.py` as an empty file, then
`src/apt_scout/normalise/text.py`:

```python
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
```

- [ ] **Step 4: Implement `price.py`**

Create `src/apt_scout/normalise/price.py`:

```python
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
```

- [ ] **Step 5: Implement `rooms.py`**

Create `src/apt_scout/normalise/rooms.py`:

```python
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
```

- [ ] **Step 6: Implement `size.py`**

Create `src/apt_scout/normalise/size.py`:

```python
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
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_normalise.py -v`
Expected: PASS, 27 passed

- [ ] **Step 8: Commit**

```bash
git add src/apt_scout/normalise tests/test_normalise.py
git commit -m "feat: add Hebrew price, rooms, size, and phone parsing"
```

---

## Task 3: Occupancy classifier

**Files:**
- Create: `src/apt_scout/enrich/__init__.py`, `src/apt_scout/enrich/occupancy.py`
- Test: `tests/test_occupancy.py`

**Interfaces:**
- Consumes: `normalise_text` from Task 2, `Occupancy` from Task 1
- Produces: `classify_occupancy(text: str | None) -> Occupancy`

- [ ] **Step 1: Write the failing test**

Create `tests/test_occupancy.py`:

```python
from apt_scout.enrich.occupancy import classify_occupancy
from apt_scout.models import Occupancy


class TestRoommateDetection:
    def test_looking_for_roommate(self):
        text = "מחפשים שותף לדירה בתל אביב"
        assert classify_occupancy(text) is Occupancy.ROOMMATES

    def test_female_roommate(self):
        assert classify_occupancy("מחפשת שותפה") is Occupancy.ROOMMATES

    def test_room_in_apartment(self):
        assert classify_occupancy("חדר בדירה משותפת") is Occupancy.ROOMMATES

    def test_english_roommate(self):
        assert classify_occupancy("Roommate wanted") is Occupancy.ROOMMATES


class TestNegationHandling:
    def test_no_roommates_is_a_whole_apartment(self):
        # The critical case: this contains the word שותפים but means the
        # opposite. Naive keyword matching gets this exactly backwards.
        text = "דירה 3 חדרים ללא שותפים"
        assert classify_occupancy(text) is Occupancy.WHOLE

    def test_without_roommates_variant(self):
        assert classify_occupancy("דירת 2 חדרים בלי שותפים") is Occupancy.WHOLE


class TestWholeApartment:
    def test_apartment_for_rent(self):
        assert classify_occupancy("דירה להשכרה במרכז") is Occupancy.WHOLE

    def test_apartment_construct_form(self):
        assert classify_occupancy("דירת גן להשכרה") is Occupancy.WHOLE


class TestUnsure:
    def test_ambiguous_text_is_unsure(self):
        assert classify_occupancy("להשכרה 2 חדרים קומה 3") is Occupancy.UNSURE

    def test_empty_is_unsure(self):
        assert classify_occupancy(None) is Occupancy.UNSURE
        assert classify_occupancy("") is Occupancy.UNSURE
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_occupancy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.enrich'`

- [ ] **Step 3: Implement the classifier**

Create `src/apt_scout/enrich/__init__.py` as an empty file, then
`src/apt_scout/enrich/occupancy.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_occupancy.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/enrich tests/test_occupancy.py
git commit -m "feat: add occupancy classifier with negation handling"
```

---

## Task 4: Tiered fetch layer

**Files:**
- Create: `src/apt_scout/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `FetchResult` dataclass with `url`, `status`, `text`, `tier`
  - `FetchError` exception
  - `Fetcher(transports: dict[str, Transport], order: list[str])`
  - `Fetcher.get(url: str, min_tier: str = "http", headers: dict | None = None) -> FetchResult`
  - `HttpTransport(client=None)` with `.name == "http"`
  - `DEFAULT_HEADERS` dict

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetch.py`:

```python
import pytest

from apt_scout.fetch import DEFAULT_HEADERS, Fetcher, FetchError, FetchResult


class FakeTransport:
    """A transport that returns canned results, for testing escalation."""

    def __init__(self, name, status=200, body="ok", raises=None):
        self.name = name
        self.status = status
        self.body = body
        self.raises = raises
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append(url)
        if self.raises:
            raise self.raises
        return FetchResult(url=url, status=self.status, text=self.body, tier=self.name)


def build(*transports):
    order = [t.name for t in transports]
    return Fetcher({t.name: t for t in transports}, order), order


class TestSuccessPath:
    def test_returns_first_tier_result_when_it_succeeds(self):
        http = FakeTransport("http")
        browser = FakeTransport("browser")
        fetcher, _ = build(http, browser)

        result = fetcher.get("https://example.com")

        assert result.status == 200
        assert result.tier == "http"
        assert browser.calls == [], "must not escalate when tier 1 works"


class TestEscalation:
    def test_escalates_to_next_tier_on_403(self):
        http = FakeTransport("http", status=403)
        browser = FakeTransport("browser", status=200, body="real page")
        fetcher, _ = build(http, browser)

        result = fetcher.get("https://example.com")

        assert result.tier == "browser"
        assert result.text == "real page"

    def test_escalates_when_a_transport_raises(self):
        http = FakeTransport("http", raises=RuntimeError("connection reset"))
        browser = FakeTransport("browser")
        fetcher, _ = build(http, browser)

        assert fetcher.get("https://example.com").tier == "browser"

    def test_starts_at_the_requested_minimum_tier(self):
        http = FakeTransport("http")
        browser = FakeTransport("browser")
        fetcher, _ = build(http, browser)

        result = fetcher.get("https://example.com", min_tier="browser")

        assert result.tier == "browser"
        assert http.calls == [], "must skip tiers below the minimum"


class TestFailure:
    def test_raises_when_every_tier_fails(self):
        http = FakeTransport("http", status=403)
        browser = FakeTransport("browser", status=500)
        fetcher, _ = build(http, browser)

        with pytest.raises(FetchError) as exc:
            fetcher.get("https://example.com")
        assert "example.com" in str(exc.value)

    def test_unknown_tier_is_an_error(self):
        fetcher, _ = build(FakeTransport("http"))
        with pytest.raises(FetchError):
            fetcher.get("https://example.com", min_tier="nonexistent")

    def test_missing_transport_in_order_is_skipped(self):
        # apify is in the order but not configured, e.g. no token available.
        http = FakeTransport("http", status=403)
        fetcher = Fetcher({"http": http}, ["http", "apify"])
        with pytest.raises(FetchError):
            fetcher.get("https://example.com")


class TestHeaders:
    def test_default_headers_look_like_a_real_browser(self):
        assert "Mozilla" in DEFAULT_HEADERS["User-Agent"]
        assert DEFAULT_HEADERS["Accept-Language"].startswith("he-IL")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.fetch'`

- [ ] **Step 3: Implement the fetch layer**

Create `src/apt_scout/fetch.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Israeli property sites routinely reject unrecognised user agents. These
# headers make a plain HTTP request indistinguishable from a normal browser,
# which is enough for most of them and far cheaper than launching a browser.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

TIER_ORDER = ["http", "browser", "apify"]


class FetchError(Exception):
    """Raised when every available tier failed to retrieve a URL."""


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    tier: str


class Transport(Protocol):
    name: str

    def get(self, url: str, headers: dict | None = None) -> FetchResult: ...


class HttpTransport:
    """Tier 1: plain HTTP with browser-like headers and a persistent session."""

    name = "http"

    def __init__(self, client=None, timeout: float = 20.0):
        if client is None:
            import httpx

            client = httpx.Client(
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                follow_redirects=True,
            )
        self._client = client

    def get(self, url: str, headers: dict | None = None) -> FetchResult:
        response = self._client.get(url, headers=headers)
        return FetchResult(
            url=url, status=response.status_code, text=response.text, tier=self.name
        )


class Fetcher:
    """Retrieves URLs, escalating through tiers until one succeeds.

    Adapters never make network calls directly. Routing every request through
    here means that when a site tightens its bot protection, the fix is a
    configuration change to its minimum tier rather than a code change.
    """

    def __init__(self, transports: dict[str, Transport], order: list[str] | None = None):
        self._transports = transports
        self._order = order or TIER_ORDER

    def get(
        self,
        url: str,
        min_tier: str = "http",
        headers: dict | None = None,
    ) -> FetchResult:
        if min_tier not in self._order:
            raise FetchError(f"Unknown fetch tier {min_tier!r} for {url}")

        attempts: list[str] = []
        start = self._order.index(min_tier)

        for name in self._order[start:]:
            transport = self._transports.get(name)
            if transport is None:
                continue
            try:
                result = transport.get(url, headers)
            except Exception as exc:  # noqa: BLE001 - any transport failure escalates
                attempts.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if result.status == 200:
                return result
            attempts.append(f"{name}: HTTP {result.status}")

        detail = "; ".join(attempts) if attempts else "no transports configured"
        raise FetchError(f"All tiers failed for {url} ({detail})")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/fetch.py tests/test_fetch.py
git commit -m "feat: add tiered fetch layer with automatic escalation"
```

---

## Task 5: yad2 adapter

The live endpoint cannot be hardcoded from the plan, because yad2 changes it.
Step 1 is a discovery step whose output becomes a committed fixture; everything
after it is TDD against that fixture. The parser is the tested unit; the URL is
configuration.

**Files:**
- Create: `src/apt_scout/adapters/__init__.py`, `base.py`, `yad2.py`
- Create: `config/sources.json`
- Create: `tests/fixtures/yad2_search.json`
- Test: `tests/test_yad2.py`

**Interfaces:**
- Consumes: `Listing`, `Occupancy` (Task 1); parsers (Task 2); `classify_occupancy` (Task 3); `Fetcher`, `FetchResult` (Task 4)
- Produces:
  - `AdapterResult(source: str, listings: list[Listing], error: str | None)`
  - `SourceAdapter` protocol with `name: str` and `fetch(fetcher, config, since) -> AdapterResult`
  - `Yad2Adapter()` with `.name == "yad2"`
  - `parse_yad2_payload(payload: dict) -> list[Listing]`

- [ ] **Step 1: Discover the live endpoint and save a fixture**

This step is manual and must be done before writing code.

1. Open `https://www.yad2.co.il/realestate/rent` in a browser with DevTools on
   the Network tab, filtered to Fetch/XHR.
2. Set the search filters to Tel Aviv, price 4000–5500, 2+ rooms.
3. Find the JSON request that returns the listing array — it will be on a
   `gw.yad2.co.il` or `www.yad2.co.il/api` host.
4. Copy the full response body and save it verbatim to
   `tests/fixtures/yad2_search.json`.
5. Copy the request URL into `config/sources.json` below as `url_template`,
   replacing the search parameters with `{price_min}`, `{price_max}`,
   `{rooms_min}` placeholders where they appear.

If yad2 returns HTML rather than JSON at tier 1, set `"min_tier": "browser"`
for yad2 in the config and repeat the capture.

- [ ] **Step 2: Create `config/sources.json`**

Replace `url_template` with the URL captured in Step 1.

```json
{
  "yad2": {
    "enabled": true,
    "min_tier": "http",
    "cadence_hours": 1,
    "url_template": "https://gw.yad2.co.il/realestate-feed/rent/map?propertyGroup=apartments&price={price_min}-{price_max}&rooms={rooms_min}--1&topArea=2&area=1",
    "max_results": 100
  }
}
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_yad2.py`. The payload shape below is a minimal stand-in;
after Step 1 you will have the real fixture, and `test_parses_real_fixture`
exercises it.

```python
import json
from pathlib import Path

from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.yad2 import Yad2Adapter, parse_yad2_payload
from apt_scout.fetch import FetchError, FetchResult
from apt_scout.models import Occupancy

FIXTURE = Path(__file__).parent / "fixtures" / "yad2_search.json"


def sample_payload():
    return {
        "data": {
            "markers": [
                {
                    "orderId": "111",
                    "price": 4800,
                    "additionalDetails": {
                        "roomsCount": 3,
                        "squareMeter": 72,
                        "property": {"text": "דירה"},
                    },
                    "address": {
                        "city": {"text": "תל אביב יפו"},
                        "street": {"text": "הרצל"},
                        "house": {"number": 10, "floor": 2},
                        "coords": {"lat": 32.0561, "lon": 34.8041},
                    },
                    "metaData": {"images": ["https://img/1.jpg"]},
                }
            ]
        }
    }


class TestParsing:
    def test_extracts_core_fields(self):
        listings = parse_yad2_payload(sample_payload())
        assert len(listings) == 1
        listing = listings[0]
        assert listing.source == "yad2"
        assert listing.source_id == "111"
        assert listing.price == 4800
        assert listing.rooms == 3.0
        assert listing.size_sqm == 72.0
        assert listing.city == "תל אביב יפו"
        assert listing.lat == 32.0561
        assert listing.lon == 34.8041
        assert listing.photos == ["https://img/1.jpg"]

    def test_builds_a_listing_url(self):
        listing = parse_yad2_payload(sample_payload())[0]
        assert listing.source_id in listing.url
        assert listing.url.startswith("https://")

    def test_yad2_listings_are_whole_apartments(self):
        # yad2's rental apartment category never contains roommate ads, so the
        # classifier does not need to guess here.
        assert parse_yad2_payload(sample_payload())[0].occupancy is Occupancy.WHOLE

    def test_missing_fields_become_none_not_zero(self):
        payload = {"data": {"markers": [{"orderId": "222"}]}}
        listing = parse_yad2_payload(payload)[0]
        assert listing.price is None
        assert listing.rooms is None
        assert listing.size_sqm is None
        assert listing.lat is None

    def test_entries_without_an_id_are_skipped(self):
        payload = {"data": {"markers": [{"price": 5000}]}}
        assert parse_yad2_payload(payload) == []

    def test_empty_payload_returns_empty_list(self):
        assert parse_yad2_payload({}) == []

    def test_parses_real_fixture(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        listings = parse_yad2_payload(payload)
        assert listings, "real yad2 fixture must yield at least one listing"
        assert all(listing.source_id for listing in listings)
        assert all(listing.url.startswith("https://") for listing in listings)


class FakeFetcher:
    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error
        self.requested = []

    def get(self, url, min_tier="http", headers=None):
        self.requested.append((url, min_tier))
        if self._error:
            raise self._error
        return FetchResult(url=url, status=200, text=self._text, tier=min_tier)


class TestAdapter:
    def test_returns_listings_on_success(self):
        fetcher = FakeFetcher(text=json.dumps(sample_payload()))
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "http"}

        result = Yad2Adapter().fetch(fetcher, config, since=None)

        assert isinstance(result, AdapterResult)
        assert result.error is None
        assert len(result.listings) == 1

    def test_uses_the_configured_minimum_tier(self):
        fetcher = FakeFetcher(text=json.dumps(sample_payload()))
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "browser"}

        Yad2Adapter().fetch(fetcher, config, since=None)

        assert fetcher.requested[0][1] == "browser"

    def test_fetch_failure_becomes_an_error_result_not_an_exception(self):
        # A failing source must degrade the run, never fail it.
        fetcher = FakeFetcher(error=FetchError("blocked"))
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "http"}

        result = Yad2Adapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert "blocked" in result.error

    def test_malformed_json_becomes_an_error_result(self):
        fetcher = FakeFetcher(text="<html>blocked</html>")
        config = {"url_template": "https://gw.yad2.co.il/x", "min_tier": "http"}

        result = Yad2Adapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `python -m pytest tests/test_yad2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.adapters'`

- [ ] **Step 5: Implement `base.py`**

Create `src/apt_scout/adapters/__init__.py` as an empty file, then
`src/apt_scout/adapters/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..models import Listing


@dataclass
class AdapterResult:
    """Outcome of one source's fetch.

    An adapter reports failure by returning this with an error string, never by
    raising. The orchestrator relies on that to keep one broken source from
    ending a run.
    """

    source: str
    listings: list[Listing] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class SourceAdapter(Protocol):
    name: str

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult: ...
```

- [ ] **Step 6: Implement `yad2.py`**

Create `src/apt_scout/adapters/yad2.py`:

```python
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..models import Listing, Occupancy
from .base import AdapterResult

LISTING_URL = "https://www.yad2.co.il/realestate/item/{source_id}"


def _get(mapping: Any, *path: str) -> Any:
    """Walk a nested dict, returning None if any step is missing."""
    current = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _address_text(marker: dict) -> str | None:
    parts = [
        _get(marker, "address", "street", "text"),
        _get(marker, "address", "house", "number"),
        _get(marker, "address", "city", "text"),
    ]
    joined = " ".join(str(part) for part in parts if part)
    return joined or None


def parse_yad2_payload(payload: dict) -> list[Listing]:
    """Convert a yad2 search response into Listings.

    Anything missing stays None rather than defaulting, so downstream filters
    can distinguish "not stated" from "stated as zero".
    """
    markers = _get(payload, "data", "markers") or []
    listings: list[Listing] = []

    for marker in markers:
        if not isinstance(marker, dict):
            continue
        source_id = marker.get("orderId") or marker.get("id")
        if not source_id:
            continue
        source_id = str(source_id)

        photos = _get(marker, "metaData", "images") or []
        if not isinstance(photos, list):
            photos = []

        listings.append(
            Listing(
                source="yad2",
                source_id=source_id,
                url=LISTING_URL.format(source_id=source_id),
                price=_as_int(marker.get("price")),
                rooms=_as_float(_get(marker, "additionalDetails", "roomsCount")),
                size_sqm=_as_float(_get(marker, "additionalDetails", "squareMeter")),
                floor=_as_int(_get(marker, "address", "house", "floor")),
                city=_get(marker, "address", "city", "text"),
                address_text=_address_text(marker),
                lat=_as_float(_get(marker, "address", "coords", "lat")),
                lon=_as_float(_get(marker, "address", "coords", "lon")),
                photos=[p for p in photos if isinstance(p, str)],
                # yad2's rental apartment category is whole apartments only;
                # roommate ads live in a separate category we do not query.
                occupancy=Occupancy.WHOLE,
            )
        )

    return listings


class Yad2Adapter:
    name = "yad2"

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        url = config["url_template"].format(
            price_min=config.get("price_min", 0),
            price_max=config.get("price_max", 100000),
            rooms_min=config.get("rooms_min", 1),
        )
        try:
            response = fetcher.get(url, min_tier=config.get("min_tier", "http"))
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return AdapterResult(source=self.name, error=f"fetch failed: {exc}")

        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            return AdapterResult(
                source=self.name,
                error=f"response was not JSON (tier {response.tier}): {exc}",
            )

        try:
            listings = parse_yad2_payload(payload)
        except Exception as exc:  # noqa: BLE001 - a shape change must not crash
            return AdapterResult(source=self.name, error=f"parse failed: {exc}")

        limit = config.get("max_results")
        if limit:
            listings = listings[:limit]
        return AdapterResult(source=self.name, listings=listings)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_yad2.py -v`
Expected: PASS, 11 passed

If `test_parses_real_fixture` fails, the field paths in `parse_yad2_payload`
do not match the real response. Adjust the `_get` paths to match the fixture —
this is expected on first run and is exactly what the fixture is for.

- [ ] **Step 8: Commit**

```bash
git add src/apt_scout/adapters config/sources.json tests/test_yad2.py tests/fixtures/yad2_search.json
git commit -m "feat: add yad2 adapter with fixture-driven parser tests"
```

---

## Task 6: State store

**Files:**
- Create: `src/apt_scout/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `StateStore(root: Path)`
  - `.load(name: str, default: Any) -> Any`
  - `.save(name: str, data: Any) -> None`
  - `.seen_ids() -> set[str]` / `.mark_seen(ids: Iterable[str]) -> None`
  - `.notified_ids() -> set[str]` / `.mark_notified(ids: Iterable[str]) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_state.py`:

```python
import json

from apt_scout.state import StateStore


class TestLoadSave:
    def test_load_returns_default_when_file_absent(self, tmp_path):
        assert StateStore(tmp_path).load("missing", {"a": 1}) == {"a": 1}

    def test_round_trips_data(self, tmp_path):
        store = StateStore(tmp_path)
        store.save("thing", {"key": "ערך"})
        assert StateStore(tmp_path).load("thing", {}) == {"key": "ערך"}

    def test_writes_readable_utf8_json(self, tmp_path):
        store = StateStore(tmp_path)
        store.save("thing", {"city": "תל אביב"})
        raw = (tmp_path / "thing.json").read_text(encoding="utf-8")
        assert "תל אביב" in raw, "Hebrew must not be escaped, for readable diffs"
        assert "\n" in raw, "must be indented, for readable diffs"

    def test_corrupt_file_falls_back_to_default(self, tmp_path):
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
        assert StateStore(tmp_path).load("broken", {"safe": True}) == {"safe": True}

    def test_save_is_atomic_leaving_no_temp_files(self, tmp_path):
        store = StateStore(tmp_path)
        store.save("thing", {"a": 1})
        assert [p.name for p in tmp_path.iterdir()] == ["thing.json"]


class TestSeenTracking:
    def test_seen_starts_empty(self, tmp_path):
        assert StateStore(tmp_path).seen_ids() == set()

    def test_mark_seen_persists(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_seen(["yad2:1", "yad2:2"])
        assert StateStore(tmp_path).seen_ids() == {"yad2:1", "yad2:2"}

    def test_mark_seen_accumulates(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_seen(["yad2:1"])
        store.mark_seen(["yad2:2"])
        assert store.seen_ids() == {"yad2:1", "yad2:2"}


class TestNotifiedTracking:
    def test_notified_is_separate_from_seen(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_seen(["yad2:1"])
        assert store.notified_ids() == set()

    def test_mark_notified_persists(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_notified(["yad2:1"])
        assert StateStore(tmp_path).notified_ids() == {"yad2:1"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.state'`

- [ ] **Step 3: Implement the state store**

Create `src/apt_scout/state.py`:

```python
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SEEN = "seen"
NOTIFIED = "notified"


class StateStore:
    """JSON state on disk, committed to git by the workflow.

    Git gives us durability, history, and diffability for free, which is why
    there is no database. Writes are atomic so an interrupted run cannot leave
    truncated state behind.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def load(self, name: str, default: Any) -> Any:
        path = self._path(name)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt state must not stop a run; git history holds the good copy.
            return default

    def save(self, name: str, data: Any) -> None:
        path = self._path(name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def seen_ids(self) -> set[str]:
        return set(self.load(SEEN, []))

    def mark_seen(self, ids: Iterable[str]) -> None:
        self.save(SEEN, sorted(self.seen_ids() | set(ids)))

    def notified_ids(self) -> set[str]:
        return set(self.load(NOTIFIED, []))

    def mark_notified(self, ids: Iterable[str]) -> None:
        self.save(NOTIFIED, sorted(self.notified_ids() | set(ids)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/state.py tests/test_state.py
git commit -m "feat: add atomic JSON state store"
```

---

## Task 7: Filter engine

**Files:**
- Create: `src/apt_scout/filters.py`, `config/filters.json`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `Listing`, `Occupancy` (Task 1)
- Produces:
  - `Filters` dataclass with fields `min_price`, `max_price`, `min_rooms`, `min_size_sqm`, `max_drive_minutes`, `include_price_missing`, `include_unsure_occupancy`
  - `Filters.load(path: Path) -> Filters`
  - `Filters.matches(listing: Listing) -> bool`

- [ ] **Step 1: Create `config/filters.json`**

```json
{
  "min_price": 4000,
  "max_price": 5500,
  "min_rooms": 2,
  "min_size_sqm": 50,
  "max_drive_minutes": 15,
  "include_price_missing": true,
  "include_unsure_occupancy": true
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_filters.py`:

```python
import json

from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy


def default_filters(**overrides) -> Filters:
    base = dict(
        min_price=4000,
        max_price=5500,
        min_rooms=2,
        min_size_sqm=50,
        max_drive_minutes=15,
        include_price_missing=True,
        include_unsure_occupancy=True,
    )
    base.update(overrides)
    return Filters(**base)


def listing(**overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id="1",
        url="https://y/1",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        drive_minutes=10.0,
        occupancy=Occupancy.WHOLE,
    )
    base.update(overrides)
    return Listing(**base)


class TestPrice:
    def test_accepts_in_range(self):
        assert default_filters().matches(listing(price=4800)) is True

    def test_rejects_below_range(self):
        assert default_filters().matches(listing(price=3500)) is False

    def test_rejects_above_range(self):
        assert default_filters().matches(listing(price=6000)) is False

    def test_accepts_boundaries_inclusively(self):
        assert default_filters().matches(listing(price=4000)) is True
        assert default_filters().matches(listing(price=5500)) is True

    def test_missing_price_follows_the_toggle(self):
        assert default_filters().matches(listing(price=None)) is True
        strict = default_filters(include_price_missing=False)
        assert strict.matches(listing(price=None)) is False


class TestRoomsAndSize:
    def test_rejects_too_few_rooms(self):
        assert default_filters().matches(listing(rooms=1.0)) is False

    def test_accepts_minimum_rooms(self):
        assert default_filters().matches(listing(rooms=2.0)) is True

    def test_rejects_too_small(self):
        assert default_filters().matches(listing(size_sqm=40.0)) is False

    def test_unknown_rooms_does_not_disqualify(self):
        # Failing closed on missing data would discard most free-text listings,
        # which is the opposite of what this system is for.
        assert default_filters().matches(listing(rooms=None)) is True

    def test_unknown_size_does_not_disqualify(self):
        assert default_filters().matches(listing(size_sqm=None)) is True


class TestDriveTime:
    def test_rejects_too_far(self):
        assert default_filters().matches(listing(drive_minutes=25.0)) is False

    def test_accepts_within_range(self):
        assert default_filters().matches(listing(drive_minutes=15.0)) is True

    def test_unknown_drive_time_does_not_disqualify(self):
        # Before the enrichment phase runs, nothing has a drive time yet.
        assert default_filters().matches(listing(drive_minutes=None)) is True


class TestOccupancy:
    def test_rejects_roommate_ads(self):
        assert default_filters().matches(listing(occupancy=Occupancy.ROOMMATES)) is False

    def test_unsure_follows_the_toggle(self):
        unsure = listing(occupancy=Occupancy.UNSURE)
        assert default_filters().matches(unsure) is True
        strict = default_filters(include_unsure_occupancy=False)
        assert strict.matches(unsure) is False


class TestLoading:
    def test_loads_from_json_file(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(
            json.dumps({"min_price": 3000, "max_price": 7000}), encoding="utf-8"
        )
        loaded = Filters.load(path)
        assert loaded.min_price == 3000
        assert loaded.max_price == 7000

    def test_unspecified_keys_take_defaults(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps({"min_price": 3000}), encoding="utf-8")
        assert Filters.load(path).min_rooms == 2

    def test_unknown_keys_are_ignored(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(
            json.dumps({"min_price": 3000, "future_option": True}), encoding="utf-8"
        )
        assert Filters.load(path).min_price == 3000
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_filters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.filters'`

- [ ] **Step 4: Implement the filter engine**

Create `src/apt_scout/filters.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

from .models import Listing, Occupancy


@dataclass
class Filters:
    """Thresholds that decide which listings are worth a notification.

    Distinct from the portal's view filters: this gates alerts, the portal
    gates display. Keeping them separate lets the user browse more loosely
    than they are interrupted.
    """

    min_price: int = 4000
    max_price: int = 5500
    min_rooms: float = 2
    min_size_sqm: float = 50
    max_drive_minutes: float = 15
    include_price_missing: bool = True
    include_unsure_occupancy: bool = True

    @classmethod
    def load(cls, path: Path) -> "Filters":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def matches(self, listing: Listing) -> bool:
        """Whether this listing should trigger an alert.

        Unknown values do not disqualify, except price, which has an explicit
        toggle. Failing closed on missing data would discard most free-text
        listings, which is exactly the content this system exists to surface.
        """
        if listing.occupancy is Occupancy.ROOMMATES:
            return False
        if listing.occupancy is Occupancy.UNSURE and not self.include_unsure_occupancy:
            return False

        if listing.price is None:
            if not self.include_price_missing:
                return False
        elif not (self.min_price <= listing.price <= self.max_price):
            return False

        if listing.rooms is not None and listing.rooms < self.min_rooms:
            return False

        if listing.size_sqm is not None and listing.size_sqm < self.min_size_sqm:
            return False

        if (
            listing.drive_minutes is not None
            and listing.drive_minutes > self.max_drive_minutes
        ):
            return False

        return True
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_filters.py -v`
Expected: PASS, 18 passed

- [ ] **Step 6: Commit**

```bash
git add src/apt_scout/filters.py config/filters.json tests/test_filters.py
git commit -m "feat: add filter engine with fail-open handling of unknown fields"
```

---

## Task 8: Telegram notifier

**Files:**
- Create: `src/apt_scout/notify/__init__.py`, `src/apt_scout/notify/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Consumes: `Listing` (Task 1)
- Produces:
  - `TelegramNotifier(token: str, chat_id: str, client=None)`
  - `.send_listing(listing: Listing) -> bool`
  - `.send_text(text: str) -> bool`
  - `format_listing(listing: Listing) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_telegram.py`:

```python
from apt_scout.models import Listing, Occupancy
from apt_scout.notify.telegram import TelegramNotifier, format_listing


class FakeClient:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def post(self, url, json=None):
        self.calls.append((url, json))
        return FakeResponse(self.ok)


class FakeResponse:
    def __init__(self, ok):
        self.status_code = 200 if ok else 500

    def json(self):
        return {"ok": self.status_code == 200}


def listing(**overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id="1",
        url="https://yad2.co.il/item/1",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        drive_minutes=11.4,
        city="תל אביב",
        address_text="הרצל 10 תל אביב",
        occupancy=Occupancy.WHOLE,
    )
    base.update(overrides)
    return Listing(**base)


class TestFormatting:
    def test_includes_the_key_facts(self):
        text = format_listing(listing())
        assert "4,800" in text
        assert "3" in text
        assert "70" in text
        assert "yad2.co.il/item/1" in text

    def test_shows_drive_time_rounded(self):
        assert "11 " in format_listing(listing()) or "11'" in format_listing(listing())

    def test_marks_missing_price_explicitly(self):
        text = format_listing(listing(price=None))
        assert "?" in text or "לא צוין" in text

    def test_omits_drive_time_when_unknown(self):
        text = format_listing(listing(drive_minutes=None))
        assert "None" not in text

    def test_never_contains_the_word_none(self):
        text = format_listing(
            listing(price=None, rooms=None, size_sqm=None, address_text=None)
        )
        assert "None" not in text


class TestSending:
    def test_sends_a_photo_when_one_exists(self):
        client = FakeClient()
        notifier = TelegramNotifier("TOKEN", "CHAT", client=client)

        assert notifier.send_listing(listing(photos=["https://img/1.jpg"])) is True

        url, payload = client.calls[0]
        assert url.endswith("/sendPhoto")
        assert payload["photo"] == "https://img/1.jpg"
        assert payload["chat_id"] == "CHAT"

    def test_sends_text_when_there_is_no_photo(self):
        client = FakeClient()
        notifier = TelegramNotifier("TOKEN", "CHAT", client=client)

        notifier.send_listing(listing(photos=[]))

        assert client.calls[0][0].endswith("/sendMessage")

    def test_token_is_in_the_url_not_the_payload(self):
        client = FakeClient()
        TelegramNotifier("SECRET", "CHAT", client=client).send_text("hi")
        url, payload = client.calls[0]
        assert "SECRET" in url
        assert "SECRET" not in str(payload)

    def test_returns_false_on_api_failure(self):
        notifier = TelegramNotifier("T", "C", client=FakeClient(ok=False))
        assert notifier.send_listing(listing()) is False

    def test_returns_false_when_the_client_raises(self):
        class Boom:
            def post(self, url, json=None):
                raise RuntimeError("network down")

        notifier = TelegramNotifier("T", "C", client=Boom())
        assert notifier.send_listing(listing()) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.notify'`

- [ ] **Step 3: Implement the notifier**

Create `src/apt_scout/notify/__init__.py` as an empty file, then
`src/apt_scout/notify/telegram.py`:

```python
from __future__ import annotations

import html

from ..models import Listing

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def format_listing(listing: Listing) -> str:
    """Build the Telegram message body for one listing.

    Telegram is private to the user, so full detail is safe here — unlike the
    public portal, which must never carry contact information.
    """
    price = f"{listing.price:,} ₪" if listing.price is not None else "מחיר לא צוין"
    lines = [f"<b>{price}</b>"]

    facts = []
    if listing.rooms is not None:
        facts.append(f"{listing.rooms:g} חד'")
    if listing.size_sqm is not None:
        facts.append(f'{listing.size_sqm:g} מ"ר')
    if listing.floor is not None:
        facts.append(f"קומה {listing.floor}")
    if facts:
        lines.append(" · ".join(facts))

    if listing.address_text:
        lines.append(html.escape(listing.address_text))
    elif listing.city:
        lines.append(html.escape(listing.city))

    if listing.drive_minutes is not None:
        lines.append(f"🚗 {round(listing.drive_minutes)} דקות נסיעה")

    lines.append(f"מקור: {listing.source}")
    lines.append(listing.url)
    return "\n".join(lines)


class TelegramNotifier:
    """Sends listing alerts to a single Telegram chat."""

    def __init__(self, token: str, chat_id: str, client=None, timeout: float = 15.0):
        self._token = token
        self._chat_id = chat_id
        if client is None:
            import httpx

            client = httpx.Client(timeout=timeout)
        self._client = client

    def _call(self, method: str, payload: dict) -> bool:
        url = API_BASE.format(token=self._token, method=method)
        try:
            response = self._client.post(url, json=payload)
        except Exception:  # noqa: BLE001 - a failed send is retried next run
            return False
        if response.status_code != 200:
            return False
        try:
            return bool(response.json().get("ok"))
        except Exception:  # noqa: BLE001
            return False

    def send_text(self, text: str) -> bool:
        return self._call(
            "sendMessage",
            {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )

    def send_listing(self, listing: Listing) -> bool:
        caption = format_listing(listing)
        if listing.photos:
            return self._call(
                "sendPhoto",
                {
                    "chat_id": self._chat_id,
                    "photo": listing.photos[0],
                    "caption": caption,
                    "parse_mode": "HTML",
                },
            )
        return self.send_text(caption)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/notify tests/test_telegram.py
git commit -m "feat: add Telegram notifier"
```

---

## Task 9: Health tracking and pipeline orchestration

**Files:**
- Create: `src/apt_scout/health.py`, `src/apt_scout/pipeline.py`
- Test: `tests/test_health.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8
- Produces:
  - `HealthTracker(store: StateStore)` with `.record(source, ok, error)`, `.report() -> dict`, `.failing_sources(threshold=3) -> list[str]`
  - `RunReport` dataclass with `fetched`, `new`, `matched`, `notified`, `errors`
  - `run_pipeline(adapters, fetcher, sources_config, filters, store, notifier, enrichers=None, now=None) -> RunReport`

- [ ] **Step 1: Write the failing health test**

Create `tests/test_health.py`:

```python
from apt_scout.health import HealthTracker
from apt_scout.state import StateStore


class TestRecording:
    def test_records_a_success(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True)
        entry = tracker.report()["yad2"]
        assert entry["consecutive_failures"] == 0
        assert entry["last_success"] is not None

    def test_records_a_failure_with_its_message(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=False, error="blocked")
        entry = tracker.report()["yad2"]
        assert entry["consecutive_failures"] == 1
        assert entry["last_error"] == "blocked"

    def test_failures_accumulate(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        for _ in range(3):
            tracker.record("yad2", ok=False, error="blocked")
        assert tracker.report()["yad2"]["consecutive_failures"] == 3

    def test_a_success_resets_the_failure_streak(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=False, error="blocked")
        tracker.record("yad2", ok=True)
        assert tracker.report()["yad2"]["consecutive_failures"] == 0

    def test_state_survives_a_restart(self, tmp_path):
        HealthTracker(StateStore(tmp_path)).record("yad2", ok=False, error="x")
        reloaded = HealthTracker(StateStore(tmp_path))
        assert reloaded.report()["yad2"]["consecutive_failures"] == 1


class TestFailingSources:
    def test_reports_sources_at_or_over_the_threshold(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        for _ in range(3):
            tracker.record("yad2", ok=False, error="blocked")
        tracker.record("madlan", ok=False, error="blocked")
        assert tracker.failing_sources(threshold=3) == ["yad2"]

    def test_healthy_sources_are_not_reported(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True)
        assert tracker.failing_sources() == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.health'`

- [ ] **Step 3: Implement `health.py`**

Create `src/apt_scout/health.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from .state import StateStore

HEALTH = "health"


class HealthTracker:
    """Per-source success and failure history.

    Exists so a silently broken scraper is visible rather than looking like a
    quiet rental market — the most dangerous failure mode this system has.
    """

    def __init__(self, store: StateStore):
        self._store = store
        self._data: dict = store.load(HEALTH, {})

    def record(self, source: str, ok: bool, error: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        entry = self._data.setdefault(
            source,
            {
                "last_success": None,
                "last_failure": None,
                "consecutive_failures": 0,
                "last_error": None,
            },
        )
        if ok:
            entry["last_success"] = now
            entry["consecutive_failures"] = 0
            entry["last_error"] = None
        else:
            entry["last_failure"] = now
            entry["consecutive_failures"] += 1
            entry["last_error"] = error
        self._store.save(HEALTH, self._data)

    def report(self) -> dict:
        return self._data

    def failing_sources(self, threshold: int = 3) -> list[str]:
        return sorted(
            source
            for source, entry in self._data.items()
            if entry["consecutive_failures"] >= threshold
        )
```

- [ ] **Step 4: Run the health tests to verify they pass**

Run: `python -m pytest tests/test_health.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Write the failing pipeline test**

Create `tests/test_pipeline.py`:

```python
from apt_scout.adapters.base import AdapterResult
from apt_scout.filters import Filters
from apt_scout.health import HealthTracker
from apt_scout.models import Listing, Occupancy
from apt_scout.pipeline import run_pipeline
from apt_scout.state import StateStore


def listing(source_id="1", **overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id=source_id,
        url=f"https://y/{source_id}",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        occupancy=Occupancy.WHOLE,
    )
    base.update(overrides)
    return Listing(**base)


class StubAdapter:
    def __init__(self, name, listings=None, error=None):
        self.name = name
        self._result = AdapterResult(
            source=name, listings=listings or [], error=error
        )

    def fetch(self, fetcher, config, since):
        return self._result


class RecordingNotifier:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    def send_listing(self, listing):
        self.sent.append(listing)
        return self.ok


def run(adapters, store, notifier, filters=None, sources=None):
    return run_pipeline(
        adapters=adapters,
        fetcher=None,
        sources_config=sources or {a.name: {"enabled": True} for a in adapters},
        filters=filters or Filters(),
        store=store,
        notifier=notifier,
    )


class TestNotification:
    def test_notifies_for_a_new_matching_listing(self, tmp_path):
        notifier = RecordingNotifier()
        report = run([StubAdapter("yad2", [listing()])], StateStore(tmp_path), notifier)
        assert report.notified == 1
        assert len(notifier.sent) == 1

    def test_does_not_notify_twice_for_the_same_listing(self, tmp_path):
        store = StateStore(tmp_path)
        adapters = [StubAdapter("yad2", [listing()])]
        run(adapters, store, RecordingNotifier())

        notifier = RecordingNotifier()
        report = run(adapters, store, notifier)

        assert report.notified == 0
        assert notifier.sent == []

    def test_does_not_notify_for_a_non_matching_listing(self, tmp_path):
        notifier = RecordingNotifier()
        report = run(
            [StubAdapter("yad2", [listing(price=9000)])],
            StateStore(tmp_path),
            notifier,
        )
        assert report.matched == 0
        assert notifier.sent == []

    def test_a_failed_send_is_retried_on_the_next_run(self, tmp_path):
        # notified_at is only recorded after a confirmed send, so an alert is
        # never lost to a transient Telegram outage.
        store = StateStore(tmp_path)
        adapters = [StubAdapter("yad2", [listing()])]
        run(adapters, store, RecordingNotifier(ok=False))

        retry = RecordingNotifier(ok=True)
        report = run(adapters, store, retry)

        assert report.notified == 1
        assert len(retry.sent) == 1


class TestFailureIsolation:
    def test_one_failing_adapter_does_not_stop_the_others(self, tmp_path):
        notifier = RecordingNotifier()
        report = run(
            [
                StubAdapter("yad2", error="blocked"),
                StubAdapter("madlan", [listing(source_id="2", source="madlan")]),
            ],
            StateStore(tmp_path),
            notifier,
        )
        assert report.notified == 1
        assert "yad2" in report.errors

    def test_an_adapter_that_raises_is_caught(self, tmp_path):
        class Exploding:
            name = "bad"

            def fetch(self, fetcher, config, since):
                raise RuntimeError("kaboom")

        report = run([Exploding()], StateStore(tmp_path), RecordingNotifier())
        assert "bad" in report.errors
        assert "kaboom" in report.errors["bad"]

    def test_health_is_recorded_for_every_source(self, tmp_path):
        store = StateStore(tmp_path)
        run(
            [StubAdapter("yad2", error="blocked"), StubAdapter("madlan", [listing()])],
            store,
            RecordingNotifier(),
        )
        report = HealthTracker(store).report()
        assert report["yad2"]["consecutive_failures"] == 1
        assert report["madlan"]["consecutive_failures"] == 0


class TestSourceToggles:
    def test_a_disabled_source_is_skipped(self, tmp_path):
        notifier = RecordingNotifier()
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": False}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=notifier,
        )
        assert report.fetched == 0
        assert notifier.sent == []


class TestEnrichment:
    def test_enrichers_run_before_filtering(self, tmp_path):
        # A listing 40 minutes away must be rejected, which can only happen if
        # the enricher has already set drive_minutes.
        def set_far_drive_time(item):
            item.drive_minutes = 40.0
            return item

        notifier = RecordingNotifier()
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(max_drive_minutes=15),
            store=StateStore(tmp_path),
            notifier=notifier,
            enrichers=[set_far_drive_time],
        )
        assert report.matched == 0
        assert notifier.sent == []
```

- [ ] **Step 6: Run it to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.pipeline'`

- [ ] **Step 7: Implement `pipeline.py`**

Create `src/apt_scout/pipeline.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .filters import Filters
from .health import HealthTracker
from .models import Listing
from .state import StateStore

Enricher = Callable[[Listing], Listing]


@dataclass
class RunReport:
    fetched: int = 0
    new: int = 0
    matched: int = 0
    notified: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def run_pipeline(
    adapters: Iterable,
    fetcher,
    sources_config: dict,
    filters: Filters,
    store: StateStore,
    notifier,
    enrichers: list[Enricher] | None = None,
    now: datetime | None = None,
) -> RunReport:
    """Fetch, enrich, filter, and notify for one scheduled run.

    Every adapter is isolated: a source that fails or raises is recorded and
    skipped, never allowed to end the run. A run in which one source breaks is
    a degraded success, not a failure.
    """
    now = now or datetime.now(timezone.utc)
    enrichers = enrichers or []
    health = HealthTracker(store)
    report = RunReport()

    collected: list[Listing] = []
    for adapter in adapters:
        config = sources_config.get(adapter.name, {})
        if not config.get("enabled", True):
            continue
        try:
            result = adapter.fetch(fetcher, config, since=None)
        except Exception as exc:  # noqa: BLE001 - isolation is the whole point
            message = f"{type(exc).__name__}: {exc}"
            report.errors[adapter.name] = message
            health.record(adapter.name, ok=False, error=message)
            continue

        if result.error:
            report.errors[adapter.name] = result.error
            health.record(adapter.name, ok=False, error=result.error)
            continue

        health.record(adapter.name, ok=True)
        collected.extend(result.listings)

    report.fetched = len(collected)

    already_notified = store.notified_ids()
    seen = store.seen_ids()

    newly_notified: list[str] = []
    for listing in collected:
        listing_id = listing.stable_id()
        if listing_id not in seen:
            listing.first_seen_at = now
            report.new += 1

        for enrich in enrichers:
            listing = enrich(listing)

        if not filters.matches(listing):
            continue
        report.matched += 1

        if listing_id in already_notified:
            continue
        if notifier.send_listing(listing):
            newly_notified.append(listing_id)
            report.notified += 1

    store.mark_seen(l.stable_id() for l in collected)
    if newly_notified:
        store.mark_notified(newly_notified)

    return report
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS, all tests across every file

- [ ] **Step 9: Commit**

```bash
git add src/apt_scout/health.py src/apt_scout/pipeline.py tests/test_health.py tests/test_pipeline.py
git commit -m "feat: add health tracking and pipeline orchestration"
```

---

## Task 10: Entry point and hourly GitHub Actions workflow

Completes Phase 1. At the end of this task the user receives real alerts.

**Files:**
- Create: `src/apt_scout/__main__.py`, `.github/workflows/scan.yml`, `README.md`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9
- Produces: `build_runtime(repo_root: Path, env: dict) -> Runtime`, `main(argv=None) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_main.py`:

```python
import json

import pytest

from apt_scout.__main__ import build_runtime, main


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "filters.json").write_text(
        json.dumps({"min_price": 4000, "max_price": 5500}), encoding="utf-8"
    )
    (tmp_path / "config" / "sources.json").write_text(
        json.dumps({"yad2": {"enabled": False}}), encoding="utf-8"
    )
    return tmp_path


class TestRuntimeConstruction:
    def test_loads_config_from_the_repo(self, repo):
        runtime = build_runtime(
            repo, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
        )
        assert runtime.filters.min_price == 4000
        assert runtime.sources_config["yad2"]["enabled"] is False

    def test_missing_telegram_credentials_is_a_clear_error(self, repo):
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            build_runtime(repo, {})

    def test_dry_run_uses_a_notifier_that_does_not_send(self, repo):
        runtime = build_runtime(repo, {}, dry_run=True)
        assert runtime.notifier.send_listing(None) is True
        assert runtime.notifier.sent == [None]


class TestMain:
    def test_dry_run_exits_zero_without_credentials(self, repo):
        assert main(["--repo", str(repo), "--dry-run"]) == 0

    def test_creates_the_state_directory(self, repo):
        main(["--repo", str(repo), "--dry-run"])
        assert (repo / "state").is_dir()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.__main__'`

- [ ] **Step 3: Implement `__main__.py`**

Create `src/apt_scout/__main__.py`:

```python
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.yad2 import Yad2Adapter
from .fetch import Fetcher, HttpTransport
from .filters import Filters
from .notify.telegram import TelegramNotifier
from .pipeline import run_pipeline
from .state import StateStore


class DryRunNotifier:
    """Records what would have been sent, so runs can be rehearsed safely."""

    def __init__(self):
        self.sent: list[Any] = []

    def send_listing(self, listing) -> bool:
        self.sent.append(listing)
        return True

    def send_text(self, text: str) -> bool:
        self.sent.append(text)
        return True


@dataclass
class Runtime:
    filters: Filters
    sources_config: dict
    store: StateStore
    notifier: Any
    fetcher: Fetcher
    adapters: list


def build_runtime(repo_root: Path, env: dict, dry_run: bool = False) -> Runtime:
    repo_root = Path(repo_root)
    filters = Filters.load(repo_root / "config" / "filters.json")
    sources_config = json.loads(
        (repo_root / "config" / "sources.json").read_text(encoding="utf-8")
    )
    store = StateStore(repo_root / "state")

    if dry_run:
        notifier: Any = DryRunNotifier()
    else:
        token = env.get("TELEGRAM_BOT_TOKEN")
        chat_id = env.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
                "(or pass --dry-run)"
            )
        notifier = TelegramNotifier(token, chat_id)

    fetcher = Fetcher({"http": HttpTransport()}, ["http", "browser", "apify"])
    return Runtime(
        filters=filters,
        sources_config=sources_config,
        store=store,
        notifier=notifier,
        fetcher=fetcher,
        adapters=[Yad2Adapter()],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apt-scout")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline without sending notifications",
    )
    args = parser.parse_args(argv)

    runtime = build_runtime(Path(args.repo), dict(os.environ), dry_run=args.dry_run)
    report = run_pipeline(
        adapters=runtime.adapters,
        fetcher=runtime.fetcher,
        sources_config=runtime.sources_config,
        filters=runtime.filters,
        store=runtime.store,
        notifier=runtime.notifier,
    )

    print(
        f"fetched={report.fetched} new={report.new} "
        f"matched={report.matched} notified={report.notified}"
    )
    for source, error in report.errors.items():
        print(f"  ERROR {source}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Create the workflow**

Create `.github/workflows/scan.yml`:

```yaml
name: scan

on:
  schedule:
    - cron: "5 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: scan
  cancel-in-progress: false

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install
        run: pip install -e .

      - name: Run scan
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          PHONE_HASH_SALT: ${{ secrets.PHONE_HASH_SALT }}
        run: python -m apt_scout --repo .

      - name: Commit state
        run: |
          git config user.name "apt-scout"
          git config user.email "apt-scout@users.noreply.github.com"
          git add state
          git diff --staged --quiet || git commit -m "chore: update state [skip ci]"
          git push
```

- [ ] **Step 6: Create `README.md`**

````markdown
# APT-Scout

Continuously scouts Tel Aviv rental listings, filters them by price, rooms,
size, and real driving time from a fixed centre point, and alerts on Telegram.

Design: [`docs/superpowers/specs/2026-08-31-apt-scout-design.md`](docs/superpowers/specs/2026-08-31-apt-scout-design.md)

## Local use

```bash
pip install -e ".[dev]"
pytest
python -m apt_scout --repo . --dry-run
```

## Configuration

- `config/filters.json` — alert thresholds
- `config/sources.json` — per-source URLs, cadence, and fetch tier

## Required repository secrets

| Secret | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from `@BotFather` |
| `TELEGRAM_CHAT_ID` | Your chat ID |
| `PHONE_HASH_SALT` | Any long random string; salts phone hashes |

Phone numbers are stored only as salted hashes and are never written to the
published portal.
````

- [ ] **Step 7: Verify the whole suite passes**

Run: `python -m pytest tests/ -v`
Expected: PASS, all tests

- [ ] **Step 8: Commit**

```bash
git add src/apt_scout/__main__.py .github/workflows/scan.yml README.md tests/test_main.py
git commit -m "feat: add CLI entry point and hourly scan workflow"
```

**Phase 1 is complete.** After the user adds the three secrets and enables
Actions, alerts begin arriving.

---

## Task 11: Geocoder

Begins Phase 2.

**Files:**
- Create: `src/apt_scout/enrich/geocode.py`
- Test: `tests/test_geocode.py`

**Interfaces:**
- Consumes: `StateStore` (Task 6), `normalise_text` (Task 2)
- Produces: `Geocoder(store, client=None, min_interval=1.0, sleep=time.sleep)` with `.geocode(address: str | None) -> tuple[float, float] | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_geocode.py`:

```python
from apt_scout.enrich.geocode import Geocoder
from apt_scout.state import StateStore


class FakeClient:
    def __init__(self, payload=None, raises=None):
        self.payload = payload if payload is not None else []
        self.raises = raises
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append(params)
        if self.raises:
            raise self.raises
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


HIT = [{"lat": "32.0561", "lon": "34.8041"}]


def build(tmp_path, client):
    return Geocoder(StateStore(tmp_path), client=client, sleep=lambda _: None)


class TestGeocoding:
    def test_returns_coordinates(self, tmp_path):
        geocoder = build(tmp_path, FakeClient(HIT))
        assert geocoder.geocode("הרצל 10 תל אביב") == (32.0561, 34.8041)

    def test_restricts_the_search_to_israel(self, tmp_path):
        client = FakeClient(HIT)
        build(tmp_path, client).geocode("הרצל 10")
        assert client.calls[0]["countrycodes"] == "il"

    def test_returns_none_for_no_match(self, tmp_path):
        assert build(tmp_path, FakeClient([])).geocode("nowhere") is None

    def test_returns_none_for_empty_input(self, tmp_path):
        client = FakeClient(HIT)
        assert build(tmp_path, client).geocode(None) is None
        assert client.calls == [], "must not call the API for empty input"

    def test_network_failure_returns_none(self, tmp_path):
        geocoder = build(tmp_path, FakeClient(raises=RuntimeError("down")))
        assert geocoder.geocode("הרצל 10") is None


class TestCaching:
    def test_repeated_lookups_hit_the_api_once(self, tmp_path):
        client = FakeClient(HIT)
        geocoder = build(tmp_path, client)
        geocoder.geocode("הרצל 10 תל אביב")
        geocoder.geocode("הרצל 10 תל אביב")
        assert len(client.calls) == 1

    def test_cache_persists_across_instances(self, tmp_path):
        build(tmp_path, FakeClient(HIT)).geocode("הרצל 10")
        second = FakeClient(HIT)
        assert build(tmp_path, second).geocode("הרצל 10") == (32.0561, 34.8041)
        assert second.calls == []

    def test_failures_are_cached_so_we_do_not_retry_forever(self, tmp_path):
        client = FakeClient([])
        geocoder = build(tmp_path, client)
        geocoder.geocode("nowhere")
        geocoder.geocode("nowhere")
        assert len(client.calls) == 1

    def test_cache_key_ignores_whitespace_differences(self, tmp_path):
        client = FakeClient(HIT)
        geocoder = build(tmp_path, client)
        geocoder.geocode("הרצל 10")
        geocoder.geocode("  הרצל   10  ")
        assert len(client.calls) == 1


class TestRateLimiting:
    def test_waits_between_live_calls(self, tmp_path):
        # Nominatim's usage policy allows one request per second. Exceeding it
        # gets the whole project blocked, so this is not optional.
        slept = []
        client = FakeClient(HIT)
        geocoder = Geocoder(
            StateStore(tmp_path), client=client, min_interval=1.0, sleep=slept.append
        )
        geocoder.geocode("a")
        geocoder.geocode("b")
        assert slept, "second live call must be rate limited"

    def test_cached_lookups_are_not_rate_limited(self, tmp_path):
        slept = []
        geocoder = Geocoder(
            StateStore(tmp_path),
            client=FakeClient(HIT),
            min_interval=1.0,
            sleep=slept.append,
        )
        geocoder.geocode("a")
        slept.clear()
        geocoder.geocode("a")
        assert slept == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_geocode.py -v`
Expected: FAIL — `ImportError: cannot import name 'Geocoder'`

- [ ] **Step 3: Implement the geocoder**

Create `src/apt_scout/enrich/geocode.py`:

```python
from __future__ import annotations

import time

from ..normalise.text import normalise_text
from ..state import StateStore

CACHE = "geocache"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "apt-scout/0.1 (personal apartment search)"

# Sentinel distinguishing "looked up, no result" from "never looked up", so a
# permanently unresolvable address is not retried on every run forever.
_MISS = "miss"


class Geocoder:
    """Address to coordinates via Nominatim, cached and rate limited."""

    def __init__(
        self,
        store: StateStore,
        client=None,
        min_interval: float = 1.0,
        sleep=time.sleep,
    ):
        self._store = store
        self._cache: dict = store.load(CACHE, {})
        self._min_interval = min_interval
        self._sleep = sleep
        self._last_call = 0.0
        if client is None:
            import httpx

            client = httpx.Client(timeout=20.0)
        self._client = client

    def geocode(self, address: str | None) -> tuple[float, float] | None:
        key = normalise_text(address)
        if not key:
            return None

        if key in self._cache:
            cached = self._cache[key]
            return None if cached == _MISS else (cached[0], cached[1])

        self._throttle()
        result = self._lookup(key)

        self._cache[key] = _MISS if result is None else [result[0], result[1]]
        self._store.save(CACHE, self._cache)
        return result

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def _lookup(self, address: str) -> tuple[float, float] | None:
        try:
            response = self._client.get(
                NOMINATIM_URL,
                params={
                    "q": address,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "il",
                },
                headers={"User-Agent": USER_AGENT},
            )
            payload = response.json()
        except Exception:  # noqa: BLE001 - a geocoding outage must not fail a run
            return None

        if not payload:
            return None
        try:
            return float(payload[0]["lat"]), float(payload[0]["lon"])
        except (KeyError, ValueError, TypeError):
            return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_geocode.py -v`
Expected: PASS, 11 passed

Note: `test_network_failure_returns_none` must not cache the failure, because a
transient outage is different from an unresolvable address. Verify the failing
`_lookup` path returns `None` *and* that the miss is still cached — this is a
deliberate trade-off: caching transient failures for one run is acceptable, and
the cache file can be deleted to force a full re-resolve.

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/enrich/geocode.py tests/test_geocode.py
git commit -m "feat: add cached, rate-limited Nominatim geocoder"
```

---

## Task 12: Drive-time calculation

**Files:**
- Create: `src/apt_scout/enrich/drivetime.py`
- Test: `tests/test_drivetime.py`

**Interfaces:**
- Consumes: `StateStore` (Task 6)
- Produces:
  - `CENTRE = (32.056581, 34.804087)`
  - `DriveTimeCalculator(store, client=None, centre=CENTRE)` with `.minutes_from_centre(lat, lon) -> float | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_drivetime.py`:

```python
from apt_scout.enrich.drivetime import CENTRE, DriveTimeCalculator
from apt_scout.state import StateStore


class FakeClient:
    def __init__(self, payload=None, raises=None):
        self.payload = payload
        self.raises = raises
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(url)
        if self.raises:
            raise self.raises
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


def ok(seconds):
    return {"code": "Ok", "routes": [{"duration": seconds}]}


def build(tmp_path, client):
    return DriveTimeCalculator(StateStore(tmp_path), client=client)


class TestCalculation:
    def test_converts_seconds_to_minutes(self, tmp_path):
        calc = build(tmp_path, FakeClient(ok(600)))
        assert calc.minutes_from_centre(32.07, 34.79) == 10.0

    def test_rounds_to_one_decimal(self, tmp_path):
        calc = build(tmp_path, FakeClient(ok(695)))
        assert calc.minutes_from_centre(32.07, 34.79) == 11.6

    def test_centre_is_ort_singalovski(self, tmp_path):
        assert CENTRE == (32.056581, 34.804087)

    def test_request_uses_lon_lat_order(self, tmp_path):
        # OSRM takes coordinates as lon,lat. Reversing them silently returns a
        # route somewhere in the Indian Ocean rather than an error.
        client = FakeClient(ok(600))
        build(tmp_path, client).minutes_from_centre(32.07, 34.79)
        assert "34.804087,32.056581" in client.calls[0]
        assert "34.79,32.07" in client.calls[0]


class TestFailures:
    def test_missing_coordinates_return_none(self, tmp_path):
        client = FakeClient(ok(600))
        calc = build(tmp_path, client)
        assert calc.minutes_from_centre(None, 34.79) is None
        assert calc.minutes_from_centre(32.07, None) is None
        assert client.calls == []

    def test_no_route_returns_none(self, tmp_path):
        calc = build(tmp_path, FakeClient({"code": "NoRoute", "routes": []}))
        assert calc.minutes_from_centre(32.07, 34.79) is None

    def test_network_failure_returns_none(self, tmp_path):
        calc = build(tmp_path, FakeClient(raises=RuntimeError("down")))
        assert calc.minutes_from_centre(32.07, 34.79) is None


class TestCaching:
    def test_identical_coordinates_hit_the_api_once(self, tmp_path):
        client = FakeClient(ok(600))
        calc = build(tmp_path, client)
        calc.minutes_from_centre(32.07, 34.79)
        calc.minutes_from_centre(32.07, 34.79)
        assert len(client.calls) == 1

    def test_nearby_coordinates_share_a_cache_entry(self, tmp_path):
        # Rounded to three decimals (~100 m), which keeps the hit rate high
        # without meaningfully affecting the drive time.
        client = FakeClient(ok(600))
        calc = build(tmp_path, client)
        calc.minutes_from_centre(32.070001, 34.790001)
        calc.minutes_from_centre(32.070002, 34.790003)
        assert len(client.calls) == 1

    def test_distant_coordinates_do_not_share_a_cache_entry(self, tmp_path):
        client = FakeClient(ok(600))
        calc = build(tmp_path, client)
        calc.minutes_from_centre(32.07, 34.79)
        calc.minutes_from_centre(32.09, 34.81)
        assert len(client.calls) == 2

    def test_cache_persists_across_instances(self, tmp_path):
        build(tmp_path, FakeClient(ok(600))).minutes_from_centre(32.07, 34.79)
        second = FakeClient(ok(600))
        assert build(tmp_path, second).minutes_from_centre(32.07, 34.79) == 10.0
        assert second.calls == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_drivetime.py -v`
Expected: FAIL — `ImportError: cannot import name 'CENTRE'`

- [ ] **Step 3: Implement the calculator**

Create `src/apt_scout/enrich/drivetime.py`:

```python
from __future__ import annotations

from ..state import StateStore

CACHE = "drivecache"

# Ort Singalovski, Yad Eliyahu, Tel Aviv.
CENTRE = (32.056581, 34.804087)

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"

# Three decimal places is roughly 100 m, which keeps the cache hit rate high
# without meaningfully changing the driving time.
_PRECISION = 3

_MISS = "miss"


class DriveTimeCalculator:
    """Driving minutes from the centre point, via OSRM, cached.

    This implements the user's actual criterion — "15 minutes drive" — rather
    than approximating it with a straight-line radius, which misjudges badly
    near the Ayalon and the river.
    """

    def __init__(self, store: StateStore, client=None, centre=CENTRE):
        self._store = store
        self._cache: dict = store.load(CACHE, {})
        self._centre = centre
        if client is None:
            import httpx

            client = httpx.Client(timeout=20.0)
        self._client = client

    def minutes_from_centre(self, lat: float | None, lon: float | None) -> float | None:
        if lat is None or lon is None:
            return None

        key = f"{round(lat, _PRECISION)},{round(lon, _PRECISION)}"
        if key in self._cache:
            cached = self._cache[key]
            return None if cached == _MISS else cached

        minutes = self._query(lat, lon)
        self._cache[key] = _MISS if minutes is None else minutes
        self._store.save(CACHE, self._cache)
        return minutes

    def _query(self, lat: float, lon: float) -> float | None:
        # OSRM expects lon,lat — the opposite of the usual convention.
        coords = f"{self._centre[1]},{self._centre[0]};{lon},{lat}"
        url = OSRM_URL.format(coords=coords)
        try:
            response = self._client.get(url, params={"overview": "false"})
            payload = response.json()
        except Exception:  # noqa: BLE001 - a routing outage must not fail a run
            return None

        routes = payload.get("routes") or []
        if not routes:
            return None
        duration = routes[0].get("duration")
        if not isinstance(duration, (int, float)):
            return None
        return round(duration / 60.0, 1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_drivetime.py -v`
Expected: PASS, 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/apt_scout/enrich/drivetime.py tests/test_drivetime.py
git commit -m "feat: add cached OSRM drive-time calculation"
```

---

## Task 13: Wire enrichment into the pipeline

Completes Phase 2. Location filtering becomes real.

**Files:**
- Create: `src/apt_scout/enrich/pipeline_enrichers.py`
- Modify: `src/apt_scout/__main__.py` (the `build_runtime` and `main` functions)
- Test: `tests/test_enrichers.py`

**Interfaces:**
- Consumes: `Geocoder` (Task 11), `DriveTimeCalculator` (Task 12), `classify_occupancy` (Task 3), parsers (Task 2), `Listing` (Task 1)
- Produces: `build_enrichers(store, salt, geocoder=None, drive=None) -> list[Enricher]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_enrichers.py`:

```python
from apt_scout.enrich.pipeline_enrichers import build_enrichers
from apt_scout.models import Listing, Occupancy
from apt_scout.state import StateStore


class StubGeocoder:
    def __init__(self, result=(32.07, 34.79)):
        self.result = result
        self.calls = []

    def geocode(self, address):
        self.calls.append(address)
        return self.result


class StubDrive:
    def __init__(self, minutes=12.0):
        self.minutes = minutes
        self.calls = []

    def minutes_from_centre(self, lat, lon):
        self.calls.append((lat, lon))
        return self.minutes


def enrich(listing, tmp_path, geocoder=None, drive=None, salt="s"):
    enrichers = build_enrichers(
        StateStore(tmp_path),
        salt=salt,
        geocoder=geocoder or StubGeocoder(),
        drive=drive or StubDrive(),
    )
    for step in enrichers:
        listing = step(listing)
    return listing


def base(**overrides) -> Listing:
    values = dict(source="yad2", source_id="1", url="https://y/1")
    values.update(overrides)
    return Listing(**values)


class TestGeocoding:
    def test_fills_coordinates_from_the_address(self, tmp_path):
        result = enrich(base(address_text="הרצל 10 תל אביב"), tmp_path)
        assert result.lat == 32.07
        assert result.lon == 34.79

    def test_does_not_re_geocode_when_coordinates_exist(self, tmp_path):
        geocoder = StubGeocoder()
        enrich(
            base(address_text="הרצל 10", lat=32.0, lon=34.0),
            tmp_path,
            geocoder=geocoder,
        )
        assert geocoder.calls == []


class TestDriveTime:
    def test_fills_drive_minutes(self, tmp_path):
        result = enrich(base(lat=32.07, lon=34.79), tmp_path)
        assert result.drive_minutes == 12.0

    def test_skipped_when_there_are_no_coordinates(self, tmp_path):
        drive = StubDrive()
        result = enrich(base(), tmp_path, geocoder=StubGeocoder(result=None), drive=drive)
        assert result.drive_minutes is None
        assert drive.calls == []


class TestTextDerivedFields:
    def test_fills_a_missing_price_from_raw_text(self, tmp_path):
        result = enrich(base(raw_text='להשכרה 4800 ש"ח'), tmp_path)
        assert result.price == 4800

    def test_does_not_overwrite_a_price_the_source_stated(self, tmp_path):
        result = enrich(base(price=5000, raw_text='4800 ש"ח'), tmp_path)
        assert result.price == 5000

    def test_fills_missing_rooms_and_size(self, tmp_path):
        result = enrich(base(raw_text='3 חדרים 70 מ"ר'), tmp_path)
        assert result.rooms == 3.0
        assert result.size_sqm == 70.0


class TestOccupancy:
    def test_reclassifies_an_unsure_listing_from_its_text(self, tmp_path):
        result = enrich(
            base(raw_text="מחפשים שותף לדירה", occupancy=Occupancy.UNSURE), tmp_path
        )
        assert result.occupancy is Occupancy.ROOMMATES

    def test_trusts_a_source_that_already_said_whole(self, tmp_path):
        # yad2 categorises for us; text heuristics must not override that.
        result = enrich(
            base(raw_text="מחפשים שותף", occupancy=Occupancy.WHOLE), tmp_path
        )
        assert result.occupancy is Occupancy.WHOLE


class TestPhoneHandling:
    def test_stores_a_hash_never_the_number(self, tmp_path):
        result = enrich(base(raw_text="לפרטים 050-1234567"), tmp_path)
        assert result.phone_hash is not None
        assert "050" not in result.phone_hash
        assert "1234567" not in result.phone_hash

    def test_no_phone_leaves_the_hash_empty(self, tmp_path):
        assert enrich(base(raw_text="דירה יפה"), tmp_path).phone_hash is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_enrichers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.enrich.pipeline_enrichers'`

- [ ] **Step 3: Implement the enrichers**

Create `src/apt_scout/enrich/pipeline_enrichers.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from ..models import Listing, Occupancy
from ..normalise.price import parse_price
from ..normalise.rooms import parse_rooms
from ..normalise.size import parse_size
from ..normalise.text import extract_phone, hash_phone
from ..state import StateStore
from .drivetime import DriveTimeCalculator
from .geocode import Geocoder
from .occupancy import classify_occupancy

Enricher = Callable[[Listing], Listing]


def _fill_from_text(listing: Listing) -> Listing:
    """Recover fields the source did not state, from its free text.

    Only fills gaps. A value the source stated explicitly is always more
    trustworthy than one scraped out of prose.
    """
    text = listing.raw_text or listing.title
    if not text:
        return listing

    if listing.price is None:
        listing.price = parse_price(text)
    if listing.rooms is None:
        listing.rooms = parse_rooms(text)
    if listing.size_sqm is None:
        listing.size_sqm = parse_size(text)
    return listing


def _classify(listing: Listing) -> Listing:
    """Resolve occupancy from text, but only when the source did not tell us."""
    if listing.occupancy is Occupancy.UNSURE:
        text = " ".join(filter(None, [listing.title, listing.raw_text]))
        listing.occupancy = classify_occupancy(text)
    return listing


def _make_phone_hasher(salt: str) -> Enricher:
    def hash_listing_phone(listing: Listing) -> Listing:
        text = " ".join(filter(None, [listing.title, listing.raw_text]))
        phone = extract_phone(text)
        if phone:
            listing.phone_hash = hash_phone(phone, salt)
        return listing

    return hash_listing_phone


def _make_geocoder_step(geocoder) -> Enricher:
    def add_coordinates(listing: Listing) -> Listing:
        if listing.lat is not None and listing.lon is not None:
            return listing
        coords = geocoder.geocode(listing.address_text or listing.city)
        if coords:
            listing.lat, listing.lon = coords
        return listing

    return add_coordinates


def _make_drive_step(drive) -> Enricher:
    def add_drive_time(listing: Listing) -> Listing:
        if listing.lat is None or listing.lon is None:
            return listing
        listing.drive_minutes = drive.minutes_from_centre(listing.lat, listing.lon)
        return listing

    return add_drive_time


def build_enrichers(
    store: StateStore,
    salt: str,
    geocoder=None,
    drive=None,
) -> list[Enricher]:
    """Assemble the enrichment chain, in dependency order.

    Text parsing runs first because it can supply the address that geocoding
    needs; geocoding runs before drive time because drive time needs coordinates.
    """
    geocoder = geocoder or Geocoder(store)
    drive = drive or DriveTimeCalculator(store)
    return [
        _fill_from_text,
        _classify,
        _make_phone_hasher(salt),
        _make_geocoder_step(geocoder),
        _make_drive_step(drive),
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_enrichers.py -v`
Expected: PASS, 12 passed

- [ ] **Step 5: Wire enrichers into `build_runtime`**

In `src/apt_scout/__main__.py`, add the import near the other `enrich` imports:

```python
from .enrich.pipeline_enrichers import build_enrichers
```

Add an `enrichers` field to the `Runtime` dataclass, after `adapters`:

```python
@dataclass
class Runtime:
    filters: Filters
    sources_config: dict
    store: StateStore
    notifier: Any
    fetcher: Fetcher
    adapters: list
    enrichers: list
```

In `build_runtime`, replace the final `return Runtime(...)` with:

```python
    salt = env.get("PHONE_HASH_SALT", "apt-scout-default-salt")
    fetcher = Fetcher({"http": HttpTransport()}, ["http", "browser", "apify"])
    return Runtime(
        filters=filters,
        sources_config=sources_config,
        store=store,
        notifier=notifier,
        fetcher=fetcher,
        adapters=[Yad2Adapter()],
        enrichers=build_enrichers(store, salt=salt),
    )
```

In `main`, pass them through by replacing the `run_pipeline(...)` call with:

```python
    report = run_pipeline(
        adapters=runtime.adapters,
        fetcher=runtime.fetcher,
        sources_config=runtime.sources_config,
        filters=runtime.filters,
        store=runtime.store,
        notifier=runtime.notifier,
        enrichers=runtime.enrichers,
    )
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS, all tests

- [ ] **Step 7: Commit**

```bash
git add src/apt_scout/enrich/pipeline_enrichers.py src/apt_scout/__main__.py tests/test_enrichers.py
git commit -m "feat: wire geocoding, drive time, and text enrichment into the pipeline"
```

**Phase 2 is complete.** Drive-time filtering is now real.

---

## Task 14: Portal data export

Begins Phase 3.

**Files:**
- Create: `src/apt_scout/portal/__init__.py`, `src/apt_scout/portal/builder.py`
- Test: `tests/test_portal_builder.py`

**Interfaces:**
- Consumes: `Listing` (Task 1), `Filters` (Task 7), `HealthTracker` (Task 9)
- Produces:
  - `listing_to_public_dict(listing: Listing) -> dict`
  - `build_portal(output_dir, listings, health, filters, generated_at) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_portal_builder.py`:

```python
import json
from datetime import datetime, timezone

from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy
from apt_scout.portal.builder import build_portal, listing_to_public_dict

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def listing(**overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id="1",
        url="https://y/1",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        drive_minutes=11.4,
        city="תל אביב",
        address_text="הרצל 10",
        lat=32.07,
        lon=34.79,
        photos=["https://img/1.jpg"],
        occupancy=Occupancy.WHOLE,
        phone_hash="deadbeef",
        first_seen_at=NOW,
    )
    base.update(overrides)
    return Listing(**base)


class TestPublicDict:
    def test_includes_the_display_fields(self):
        data = listing_to_public_dict(listing())
        assert data["price"] == 4800
        assert data["rooms"] == 3.0
        assert data["drive_minutes"] == 11.4
        assert data["url"] == "https://y/1"

    def test_never_includes_the_phone_hash(self):
        # The salted hash is an internal matching key. It has no display value
        # and publishing it would be a needless leak of derived personal data.
        assert "phone_hash" not in listing_to_public_dict(listing())

    def test_never_includes_raw_text(self):
        # Raw post text routinely contains phone numbers and names.
        data = listing_to_public_dict(listing(raw_text="חייגו 050-1234567"))
        assert "raw_text" not in data
        assert "050" not in json.dumps(data, ensure_ascii=False)

    def test_serialises_datetimes_as_iso_strings(self):
        assert listing_to_public_dict(listing())["first_seen_at"] == NOW.isoformat()

    def test_handles_missing_values(self):
        data = listing_to_public_dict(listing(price=None, first_seen_at=None))
        assert data["price"] is None
        assert data["first_seen_at"] is None


class TestBuildPortal:
    def test_writes_the_data_file(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert len(data["listings"]) == 1
        assert data["generated_at"] == NOW.isoformat()

    def test_copies_the_static_assets(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW)
        assert (tmp_path / "index.html").exists()
        assert (tmp_path / "app.js").exists()
        assert (tmp_path / "style.css").exists()

    def test_includes_source_health(self, tmp_path):
        health = {"yad2": {"consecutive_failures": 0, "last_success": NOW.isoformat()}}
        build_portal(tmp_path, [listing()], health, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["health"]["yad2"]["consecutive_failures"] == 0

    def test_includes_the_alert_thresholds_as_initial_ui_values(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(max_price=6000), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["defaults"]["max_price"] == 6000

    def test_no_phone_number_appears_anywhere_in_the_output(self, tmp_path):
        # The hard rule from the spec, enforced by a test rather than a comment.
        build_portal(
            tmp_path,
            [listing(raw_text="לפרטים 052-9876543", phone_hash="abc123")],
            {},
            Filters(),
            NOW,
        )
        published = (tmp_path / "data" / "listings.json").read_text("utf-8")
        assert "052" not in published
        assert "9876543" not in published
        assert "abc123" not in published

    def test_sorts_newest_first(self, tmp_path):
        older = listing(source_id="old", first_seen_at=datetime(2026, 8, 30, tzinfo=timezone.utc))
        newer = listing(source_id="new", first_seen_at=datetime(2026, 8, 31, tzinfo=timezone.utc))
        build_portal(tmp_path, [older, newer], {}, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["listings"][0]["source_id"] == "new"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_portal_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.portal'`

- [ ] **Step 3: Implement the builder**

Create `src/apt_scout/portal/__init__.py` as an empty file, then
`src/apt_scout/portal/builder.py`:

```python
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from ..filters import Filters
from ..models import Listing

ASSETS = Path(__file__).parent / "assets"

# The published portal carries only these fields. Everything else — raw post
# text, phone hashes — stays in private state. This allowlist is the mechanism
# that makes the no-contact-details rule enforceable rather than aspirational.
PUBLIC_FIELDS = (
    "source",
    "source_id",
    "url",
    "title",
    "price",
    "rooms",
    "size_sqm",
    "floor",
    "address_text",
    "city",
    "lat",
    "lon",
    "drive_minutes",
    "photos",
    "occupancy",
)


def listing_to_public_dict(listing: Listing) -> dict:
    """Project a Listing down to the fields safe to publish."""
    data: dict = {}
    for name in PUBLIC_FIELDS:
        value = getattr(listing, name)
        data[name] = value.value if hasattr(value, "value") else value

    for name in ("posted_at", "first_seen_at"):
        moment: datetime | None = getattr(listing, name)
        data[name] = moment.isoformat() if moment else None

    return data


def build_portal(
    output_dir: Path,
    listings: list[Listing],
    health: dict,
    filters: Filters,
    generated_at: datetime,
) -> Path:
    """Generate the static portal into output_dir."""
    output_dir = Path(output_dir)
    (output_dir / "data").mkdir(parents=True, exist_ok=True)

    ordered = sorted(
        listings,
        key=lambda item: item.first_seen_at.isoformat() if item.first_seen_at else "",
        reverse=True,
    )

    payload = {
        "generated_at": generated_at.isoformat(),
        "defaults": filters.to_dict(),
        "health": health,
        "listings": [listing_to_public_dict(item) for item in ordered],
    }

    (output_dir / "data" / "listings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for asset in ("index.html", "app.js", "style.css"):
        shutil.copy(ASSETS / asset, output_dir / asset)

    return output_dir / "data" / "listings.json"
```

- [ ] **Step 4: Create placeholder assets so the copy step works**

Create `src/apt_scout/portal/assets/index.html`, `app.js`, and `style.css` each
containing a single line; Task 15 replaces them with the real portal.

`index.html`:
```html
<div id="app">loading</div>
```

`app.js`:
```javascript
// Replaced in Task 15.
```

`style.css`:
```css
/* Replaced in Task 15. */
```

- [ ] **Step 5: Ensure assets ship with the package**

In `pyproject.toml`, add after the `[tool.setuptools.packages.find]` block:

```toml
[tool.setuptools.package-data]
apt_scout = ["portal/assets/*"]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_portal_builder.py -v`
Expected: PASS, 11 passed

- [ ] **Step 7: Commit**

```bash
git add src/apt_scout/portal pyproject.toml tests/test_portal_builder.py
git commit -m "feat: add portal data export with a public-field allowlist"
```

---

## Task 15: Portal user interface

**Files:**
- Modify: `src/apt_scout/portal/assets/index.html`, `app.js`, `style.css`
- Test: `tests/test_portal_assets.py`

**Interfaces:**
- Consumes: `data/listings.json` produced by Task 14
- Produces: the browsable portal

- [ ] **Step 1: Write the failing test**

Create `tests/test_portal_assets.py`:

```python
from pathlib import Path

ASSETS = Path("src/apt_scout/portal/assets")


class TestHtml:
    def test_is_right_to_left_hebrew(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'dir="rtl"' in html
        assert 'lang="he"' in html

    def test_has_a_control_for_every_filter(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        for control in (
            "max-drive",
            "min-price",
            "max-price",
            "min-rooms",
            "min-size",
            "include-no-price",
            "include-unsure",
        ):
            assert f'id="{control}"' in html, f"missing control {control}"

    def test_loads_its_own_assets_only(self):
        # A strict offline-capable portal: no CDN scripts, no external CSS.
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert "app.js" in html
        assert "style.css" in html

    def test_has_a_health_footer(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="health"' in html


class TestJavaScript:
    def test_fetches_the_data_file(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "data/listings.json" in js

    def test_filters_on_every_criterion(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        for field in ("drive_minutes", "price", "rooms", "size_sqm", "occupancy"):
            assert field in js, f"filter logic missing {field}"

    def test_persists_the_users_choices(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "localStorage" in js

    def test_re_renders_on_input_without_reloading(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "addEventListener" in js
        assert "location.reload" not in js
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_portal_assets.py -v`
Expected: FAIL — several assertions fail against the placeholder assets

- [ ] **Step 3: Write `index.html`**

Replace `src/apt_scout/portal/assets/index.html`:

```html
<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>APT-Scout</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <h1>APT-Scout</h1>
    <p id="summary">טוען…</p>
  </header>

  <section id="controls">
    <label>
      זמן נסיעה מקסימלי: <output id="max-drive-out"></output> דק'
      <input type="range" id="max-drive" min="5" max="45" step="1">
    </label>
    <label>
      מחיר מינימלי: <output id="min-price-out"></output> ₪
      <input type="range" id="min-price" min="2000" max="12000" step="100">
    </label>
    <label>
      מחיר מקסימלי: <output id="max-price-out"></output> ₪
      <input type="range" id="max-price" min="2000" max="12000" step="100">
    </label>
    <label>
      מינימום חדרים: <output id="min-rooms-out"></output>
      <input type="range" id="min-rooms" min="1" max="6" step="0.5">
    </label>
    <label>
      מינימום שטח: <output id="min-size-out"></output> מ"ר
      <input type="range" id="min-size" min="20" max="150" step="5">
    </label>
    <label class="toggle">
      <input type="checkbox" id="include-no-price"> הצג ללא מחיר
    </label>
    <label class="toggle">
      <input type="checkbox" id="include-unsure"> הצג לא ודאי (שותפים?)
    </label>
    <button type="button" id="reset">איפוס</button>
  </section>

  <main id="results"></main>
  <footer id="health"></footer>

  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write `app.js`**

Replace `src/apt_scout/portal/assets/app.js`:

```javascript
"use strict";

const STORAGE_KEY = "apt-scout-filters";
const CONTROLS = ["max-drive", "min-price", "max-price", "min-rooms", "min-size"];
const TOGGLES = ["include-no-price", "include-unsure"];

let listings = [];
let defaults = {};

function readControls() {
  const state = {};
  CONTROLS.forEach((id) => {
    state[id] = Number(document.getElementById(id).value);
  });
  TOGGLES.forEach((id) => {
    state[id] = document.getElementById(id).checked;
  });
  return state;
}

function applyControls(state) {
  CONTROLS.forEach((id) => {
    if (state[id] !== undefined) document.getElementById(id).value = state[id];
    document.getElementById(id + "-out").value = document.getElementById(id).value;
  });
  TOGGLES.forEach((id) => {
    if (state[id] !== undefined) document.getElementById(id).checked = state[id];
  });
}

function saveState(state) {
  // Wrapped because private-mode browsers throw rather than no-op here.
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (err) {
    /* a portal that cannot remember preferences still works fine */
  }
}

function loadState() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch (err) {
    return {};
  }
}

function matches(item, state) {
  // Unknown values do not disqualify, matching the alert filter's behaviour.
  if (item.occupancy === "roommates") return false;
  if (item.occupancy === "unsure" && !state["include-unsure"]) return false;

  if (item.price === null) {
    if (!state["include-no-price"]) return false;
  } else if (item.price < state["min-price"] || item.price > state["max-price"]) {
    return false;
  }

  if (item.rooms !== null && item.rooms < state["min-rooms"]) return false;
  if (item.size_sqm !== null && item.size_sqm < state["min-size"]) return false;
  if (item.drive_minutes !== null && item.drive_minutes > state["max-drive"]) {
    return false;
  }
  return true;
}

function isNew(item) {
  if (!item.first_seen_at) return false;
  return Date.now() - Date.parse(item.first_seen_at) < 24 * 60 * 60 * 1000;
}

function card(item) {
  const el = document.createElement("article");
  el.className = "card";

  const price = item.price === null ? "מחיר לא צוין" : item.price.toLocaleString("he-IL") + " ₪";
  const facts = [];
  if (item.rooms !== null) facts.push(item.rooms + " חד'");
  if (item.size_sqm !== null) facts.push(item.size_sqm + ' מ"ר');
  if (item.drive_minutes !== null) facts.push("🚗 " + Math.round(item.drive_minutes) + " דק'");

  const photo = item.photos && item.photos.length
    ? '<img loading="lazy" alt="" src="' + item.photos[0] + '">'
    : "";

  el.innerHTML =
    photo +
    '<div class="body">' +
    (isNew(item) ? '<span class="badge new">חדש</span>' : "") +
    '<span class="badge source">' + item.source + "</span>" +
    "<h2>" + price + "</h2>" +
    "<p>" + facts.join(" · ") + "</p>" +
    "<p class=\"addr\">" + (item.address_text || item.city || "") + "</p>" +
    '<a href="' + item.url + '" target="_blank" rel="noopener noreferrer">למודעה המקורית</a>' +
    "</div>";
  return el;
}

function render() {
  const state = readControls();
  applyControls(state);
  saveState(state);

  const visible = listings.filter((item) => matches(item, state));
  const results = document.getElementById("results");
  results.replaceChildren(...visible.map(card));

  document.getElementById("summary").textContent =
    visible.length + " מתוך " + listings.length + " מודעות";
}

function renderHealth(health, generatedAt) {
  const parts = Object.entries(health || {}).map(([source, entry]) => {
    const broken = entry.consecutive_failures >= 3;
    return (
      '<span class="' + (broken ? "bad" : "good") + '">' +
      source + (broken ? " ✕" : " ✓") +
      "</span>"
    );
  });
  document.getElementById("health").innerHTML =
    "עודכן: " + new Date(generatedAt).toLocaleString("he-IL") + " · " + parts.join(" ");
}

function wire() {
  CONTROLS.concat(TOGGLES).forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });
  document.getElementById("reset").addEventListener("click", () => {
    applyControls({
      "max-drive": defaults.max_drive_minutes,
      "min-price": defaults.min_price,
      "max-price": defaults.max_price,
      "min-rooms": defaults.min_rooms,
      "min-size": defaults.min_size_sqm,
      "include-no-price": defaults.include_price_missing,
      "include-unsure": defaults.include_unsure_occupancy,
    });
    render();
  });
}

fetch("data/listings.json")
  .then((response) => response.json())
  .then((data) => {
    listings = data.listings || [];
    defaults = data.defaults || {};

    const saved = loadState();
    applyControls({
      "max-drive": defaults.max_drive_minutes,
      "min-price": defaults.min_price,
      "max-price": defaults.max_price,
      "min-rooms": defaults.min_rooms,
      "min-size": defaults.min_size_sqm,
      "include-no-price": defaults.include_price_missing,
      "include-unsure": defaults.include_unsure_occupancy,
      ...saved,
    });

    wire();
    render();
    renderHealth(data.health, data.generated_at);
  })
  .catch(() => {
    document.getElementById("summary").textContent = "שגיאה בטעינת הנתונים";
  });
```

- [ ] **Step 5: Write `style.css`**

Replace `src/apt_scout/portal/assets/style.css`:

```css
:root {
  --bg: #fbfbfd;
  --fg: #17171a;
  --muted: #6b6b76;
  --card: #ffffff;
  --line: #e3e3ea;
  --accent: #1f6feb;
  --good: #1a7f37;
  --bad: #b42318;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131316;
    --fg: #ececf1;
    --muted: #9a9aa5;
    --card: #1c1c21;
    --line: #2c2c33;
    --accent: #58a6ff;
    --good: #3fb950;
    --bad: #f85149;
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 1rem;
  background: var(--bg);
  color: var(--fg);
  font-family: system-ui, "Segoe UI", Arial, sans-serif;
  line-height: 1.5;
}

header h1 { margin: 0 0 .25rem; font-size: 1.3rem; }
#summary { margin: 0 0 1rem; color: var(--muted); font-size: .9rem; }

#controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: .75rem 1.25rem;
  padding: 1rem;
  margin-bottom: 1.25rem;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
}

#controls label { display: block; font-size: .85rem; color: var(--muted); }
#controls label.toggle { display: flex; align-items: center; gap: .5rem; }
#controls input[type="range"] { width: 100%; margin-top: .35rem; accent-color: var(--accent); }
#controls output { font-weight: 600; color: var(--fg); }

#reset {
  padding: .5rem 1rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: transparent;
  color: var(--fg);
  cursor: pointer;
  align-self: end;
}

#results {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 1rem;
}

.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}

.card img { width: 100%; height: 170px; object-fit: cover; display: block; }
.card .body { padding: .85rem; }
.card h2 { margin: .4rem 0 .3rem; font-size: 1.1rem; }
.card p { margin: 0 0 .35rem; font-size: .9rem; }
.card .addr { color: var(--muted); }
.card a { color: var(--accent); font-size: .9rem; }

.badge {
  display: inline-block;
  padding: .1rem .45rem;
  margin-inline-end: .35rem;
  border-radius: 999px;
  font-size: .72rem;
  border: 1px solid var(--line);
  color: var(--muted);
}

.badge.new { background: var(--accent); border-color: var(--accent); color: #fff; }

#health {
  margin-top: 1.5rem;
  padding-top: .75rem;
  border-top: 1px solid var(--line);
  font-size: .8rem;
  color: var(--muted);
}

#health .good { color: var(--good); margin-inline-start: .5rem; }
#health .bad { color: var(--bad); margin-inline-start: .5rem; font-weight: 600; }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_portal_assets.py -v`
Expected: PASS, 8 passed

- [ ] **Step 7: Inspect the portal by eye**

```bash
python -m apt_scout --repo . --dry-run --build-portal --portal-dir site
```

This flag is added in Task 16; until then, build it from a Python shell:

```bash
python -c "from datetime import datetime,timezone; from pathlib import Path; from apt_scout.portal.builder import build_portal; from apt_scout.filters import Filters; build_portal(Path('site'), [], {}, Filters.load(Path('config/filters.json')), datetime.now(timezone.utc))"
python -m http.server 8000 --directory site
```

Open `http://localhost:8000` and confirm the controls render right-to-left and
move without errors in the browser console.

- [ ] **Step 8: Commit**

```bash
git add src/apt_scout/portal/assets tests/test_portal_assets.py
git commit -m "feat: add portal UI with instant client-side filters"
```

---

## Task 16: Publish the portal from the workflow

Completes Phase 3.

**Files:**
- Modify: `src/apt_scout/__main__.py`, `src/apt_scout/pipeline.py`, `.github/workflows/scan.yml`, `README.md`
- Test: `tests/test_portal_publish.py`

**Interfaces:**
- Consumes: `build_portal` (Task 14), `run_pipeline` (Task 9)
- Produces: `RunReport.listings` populated with every enriched listing; `--build-portal` and `--portal-dir` CLI flags

- [ ] **Step 1: Write the failing test**

Create `tests/test_portal_publish.py`:

```python
import json

import pytest

from apt_scout.__main__ import main
from apt_scout.adapters.base import AdapterResult
from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy
from apt_scout.pipeline import run_pipeline
from apt_scout.state import StateStore


class StubAdapter:
    name = "yad2"

    def fetch(self, fetcher, config, since):
        return AdapterResult(
            source="yad2",
            listings=[
                Listing(
                    source="yad2",
                    source_id="1",
                    url="https://y/1",
                    price=4800,
                    rooms=3.0,
                    size_sqm=70.0,
                    occupancy=Occupancy.WHOLE,
                )
            ],
        )


class SilentNotifier:
    def send_listing(self, listing):
        return True


class TestReportCarriesListings:
    def test_report_exposes_enriched_listings_for_the_portal(self, tmp_path):
        # The portal shows everything recent, not only what passed the alert
        # filter, so the report must carry all of them.
        report = run_pipeline(
            adapters=[StubAdapter()],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=SilentNotifier(),
        )
        assert len(report.listings) == 1
        assert report.listings[0].source_id == "1"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "filters.json").write_text(
        json.dumps({"min_price": 4000, "max_price": 5500}), encoding="utf-8"
    )
    (tmp_path / "config" / "sources.json").write_text(
        json.dumps({"yad2": {"enabled": False}}), encoding="utf-8"
    )
    return tmp_path


class TestCli:
    def test_build_portal_flag_writes_the_site(self, repo):
        exit_code = main(
            ["--repo", str(repo), "--dry-run", "--build-portal", "--portal-dir", "site"]
        )
        assert exit_code == 0
        assert (repo / "site" / "index.html").exists()
        assert (repo / "site" / "data" / "listings.json").exists()

    def test_no_portal_is_written_without_the_flag(self, repo):
        main(["--repo", str(repo), "--dry-run"])
        assert not (repo / "site").exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_portal_publish.py -v`
Expected: FAIL — `AttributeError: 'RunReport' object has no attribute 'listings'`

- [ ] **Step 3: Add `listings` to `RunReport`**

In `src/apt_scout/pipeline.py`, add the import at the top if not present:

```python
from .models import Listing
```

Add the field to `RunReport`, after `errors`:

```python
@dataclass
class RunReport:
    fetched: int = 0
    new: int = 0
    matched: int = 0
    notified: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    listings: list[Listing] = field(default_factory=list)
```

Inside `run_pipeline`, the enriched listings must be collected. Replace the
entire `for listing in collected:` loop — leaving the `already_notified`, `seen`,
and `newly_notified` lines above it untouched — with the following, which adds
one line before the loop and one after it:

```python
    enriched: list[Listing] = []
    for listing in collected:
        listing_id = listing.stable_id()
        if listing_id not in seen:
            listing.first_seen_at = now
            report.new += 1

        for enrich in enrichers:
            listing = enrich(listing)
        enriched.append(listing)

        if not filters.matches(listing):
            continue
        report.matched += 1

        if listing_id in already_notified:
            continue
        if notifier.send_listing(listing):
            newly_notified.append(listing_id)
            report.notified += 1

    report.listings = enriched
```

- [ ] **Step 4: Add the CLI flags**

In `src/apt_scout/__main__.py`, add these imports:

```python
from datetime import datetime, timezone

from .health import HealthTracker
from .portal.builder import build_portal
```

Add the arguments in `main`, after the `--dry-run` argument:

```python
    parser.add_argument(
        "--build-portal", action="store_true", help="Generate the static portal"
    )
    parser.add_argument(
        "--portal-dir", default="site", help="Where to write the portal"
    )
```

After the `run_pipeline(...)` call and before the `print(...)`, add:

```python
    if args.build_portal:
        build_portal(
            output_dir=Path(args.repo) / args.portal_dir,
            listings=report.listings,
            health=HealthTracker(runtime.store).report(),
            filters=runtime.filters,
            generated_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS, all tests

- [ ] **Step 6: Publish from the workflow**

In `.github/workflows/scan.yml`, replace the `Run scan` step and add a deploy
step, leaving the checkout, setup, install, and commit steps unchanged:

```yaml
      - name: Run scan
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          PHONE_HASH_SALT: ${{ secrets.PHONE_HASH_SALT }}
        run: python -m apt_scout --repo . --build-portal --portal-dir site

      - name: Publish portal
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./site
          publish_branch: gh-pages
```

- [ ] **Step 7: Update `README.md`**

Add this section before "Required repository secrets":

````markdown
## Portal

Every run regenerates a static portal and publishes it to the `gh-pages`
branch. Enable it once under Settings → Pages → Deploy from branch →
`gh-pages`.

All filtering in the portal is client-side, so changes take effect instantly
and your selections are remembered in the browser.

The portal never renders contact details. Phone numbers are stored only as
salted hashes and are excluded from the published data by an explicit
allowlist, which `tests/test_portal_builder.py` enforces.

Build it locally with:

```bash
python -m apt_scout --repo . --dry-run --build-portal
python -m http.server 8000 --directory site
```
````

- [ ] **Step 8: Verify the full suite one more time**

Run: `python -m pytest tests/ -v`
Expected: PASS, all tests

- [ ] **Step 9: Commit**

```bash
git add src/apt_scout/pipeline.py src/apt_scout/__main__.py .github/workflows/scan.yml README.md tests/test_portal_publish.py
git commit -m "feat: build and publish the portal from the hourly workflow"
```

---

## Task 17: Map view

The spec places a map in Phase 3. Leaflet is vendored rather than loaded from a
CDN so the portal has no third-party script dependency; map tiles still come
from OpenStreetMap, which needs no key.

**Files:**
- Create: `src/apt_scout/portal/assets/vendor/leaflet.js`, `vendor/leaflet.css`
- Modify: `src/apt_scout/portal/assets/index.html`, `app.js`, `style.css`
- Modify: `src/apt_scout/portal/builder.py` (the asset copy loop)
- Test: `tests/test_portal_map.py`

**Interfaces:**
- Consumes: `data/listings.json` (Task 14), the `render()` function (Task 15)
- Produces: `renderMap(visible)` in `app.js`

- [ ] **Step 1: Vendor Leaflet**

```bash
mkdir -p src/apt_scout/portal/assets/vendor
curl -L -o src/apt_scout/portal/assets/vendor/leaflet.js https://unpkg.com/leaflet@1.9.4/dist/leaflet.js
curl -L -o src/apt_scout/portal/assets/vendor/leaflet.css https://unpkg.com/leaflet@1.9.4/dist/leaflet.css
```

Markers use `L.circleMarker`, which is drawn in SVG, so none of Leaflet's
default marker PNGs are needed and there are no image paths to fix up.

- [ ] **Step 2: Write the failing test**

Create `tests/test_portal_map.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy
from apt_scout.portal.builder import build_portal

ASSETS = Path("src/apt_scout/portal/assets")
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


class TestVendoredLeaflet:
    def test_leaflet_is_vendored_not_loaded_from_a_cdn(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert "vendor/leaflet.js" in html
        assert "vendor/leaflet.css" in html
        assert "unpkg.com" not in html
        assert "cdn." not in html

    def test_vendored_files_are_present_and_real(self):
        js = ASSETS / "vendor" / "leaflet.js"
        assert js.exists(), "run the curl step first"
        assert js.stat().st_size > 100_000, "leaflet.js looks truncated"


class TestMapMarkup:
    def test_html_has_a_map_container(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="map"' in html

    def test_css_gives_the_map_a_height(self):
        # A Leaflet container with no height renders as an invisible zero-pixel
        # strip, which looks exactly like a broken map.
        css = (ASSETS / "style.css").read_text(encoding="utf-8")
        assert "#map" in css
        assert "height" in css


class TestMapBehaviour:
    def test_uses_openstreetmap_tiles(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "tile.openstreetmap.org" in js
        assert "attribution" in js, "OSM tile usage requires attribution"

    def test_uses_circle_markers_so_no_images_are_needed(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "circleMarker" in js

    def test_map_updates_with_the_filters(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "renderMap" in js

    def test_skips_listings_without_coordinates(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "lat === null" in js or "lat == null" in js


class TestAssetCopying:
    def test_build_copies_the_vendor_directory(self, tmp_path):
        listing = Listing(
            source="yad2",
            source_id="1",
            url="https://y/1",
            lat=32.07,
            lon=34.79,
            occupancy=Occupancy.WHOLE,
        )
        build_portal(tmp_path, [listing], {}, Filters(), NOW)
        assert (tmp_path / "vendor" / "leaflet.js").exists()
        assert (tmp_path / "vendor" / "leaflet.css").exists()

    def test_coordinates_are_published_for_the_map(self, tmp_path):
        listing = Listing(
            source="yad2", source_id="1", url="https://y/1", lat=32.07, lon=34.79
        )
        build_portal(tmp_path, [listing], {}, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["listings"][0]["lat"] == 32.07
        assert data["listings"][0]["lon"] == 34.79
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/test_portal_map.py -v`
Expected: FAIL — `vendor/leaflet.js` not referenced in `index.html`

- [ ] **Step 4: Add the map to `index.html`**

Add inside `<head>`, after the existing stylesheet link:

```html
  <link rel="stylesheet" href="vendor/leaflet.css">
```

Add immediately after the closing `</section>` of `#controls`:

```html
  <div id="map"></div>
```

Add before `<script src="app.js"></script>`:

```html
  <script src="vendor/leaflet.js"></script>
```

- [ ] **Step 5: Add map rendering to `app.js`**

Add near the top, after the `let defaults = {};` line:

```javascript
let map = null;
let markerLayer = null;
const CENTRE = [32.056581, 34.804087];
```

Add this function before `function render()`:

```javascript
function renderMap(visible) {
  if (!map) {
    map = L.map("map").setView(CENTRE, 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);

    L.circleMarker(CENTRE, {
      radius: 8,
      color: "#b42318",
      fillColor: "#b42318",
      fillOpacity: 0.9,
    })
      .bindPopup("נקודת הייחוס")
      .addTo(map);
  }

  markerLayer.clearLayers();
  visible.forEach((item) => {
    if (item.lat === null || item.lon === null) return;
    const price = item.price === null ? "מחיר לא צוין" : item.price.toLocaleString("he-IL") + " ₪";
    L.circleMarker([item.lat, item.lon], {
      radius: 6,
      color: "#1f6feb",
      fillColor: "#1f6feb",
      fillOpacity: 0.75,
    })
      .bindPopup('<b>' + price + "</b><br>" + '<a href="' + item.url + '" target="_blank" rel="noopener noreferrer">למודעה</a>')
      .addTo(markerLayer);
  });
}
```

Add this line at the end of `render()`, after the `summary` assignment:

```javascript
  renderMap(visible);
```

- [ ] **Step 6: Give the map a height in `style.css`**

Add after the `#reset` rule:

```css
#map {
  height: 320px;
  margin-bottom: 1.25rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  z-index: 0;
}
```

- [ ] **Step 7: Copy the vendor directory in the builder**

In `src/apt_scout/portal/builder.py`, replace the asset copy loop with:

```python
    for asset in ("index.html", "app.js", "style.css"):
        shutil.copy(ASSETS / asset, output_dir / asset)

    shutil.copytree(ASSETS / "vendor", output_dir / "vendor", dirs_exist_ok=True)
```

- [ ] **Step 8: Include the vendor files in the package**

In `pyproject.toml`, replace the package-data entry with:

```toml
[tool.setuptools.package-data]
apt_scout = ["portal/assets/*", "portal/assets/vendor/*"]
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/ -v`
Expected: PASS, all tests

- [ ] **Step 10: Check the map by eye**

```bash
python -m apt_scout --repo . --dry-run --build-portal
python -m http.server 8000 --directory site
```

Open `http://localhost:8000` and confirm the map renders with the red reference
marker at Ort Singalovski, and that moving a filter slider updates the markers.

- [ ] **Step 11: Commit**

```bash
git add src/apt_scout/portal pyproject.toml tests/test_portal_map.py
git commit -m "feat: add map view with vendored Leaflet"
```

**Phase 3 is complete.** Alerts arrive on Telegram, drive-time filtering is
accurate, and the portal is live with instant filters and a map.

---

## Task 18: Telegram commands for changing alert thresholds

The spec's scheduling table lists a Telegram command poll on every run. This
delivers the user's requirement to change alert thresholds from their phone,
without a laptop. Portal filters change what is *displayed*; these change what
*interrupts you*.

**Files:**
- Create: `src/apt_scout/notify/commands.py`
- Modify: `src/apt_scout/filters.py` (add `paused`), `src/apt_scout/notify/telegram.py` (add `get_updates`), `src/apt_scout/__main__.py`, `config/filters.json`
- Test: `tests/test_commands.py`

**Interfaces:**
- Consumes: `Filters` (Task 7), `TelegramNotifier` (Task 8), `StateStore` (Task 6)
- Produces:
  - `TelegramNotifier.get_updates(offset: int | None) -> list[dict]`
  - `parse_command(text: str) -> tuple[str, list[str]] | None`
  - `apply_command(filters: Filters, command: str, args: list[str]) -> tuple[Filters, str]`
  - `process_commands(notifier, store, filters, filters_path) -> Filters`

- [ ] **Step 1: Write the failing test**

Create `tests/test_commands.py`:

```python
import json

from apt_scout.filters import Filters
from apt_scout.notify.commands import apply_command, parse_command, process_commands
from apt_scout.state import StateStore


class TestParsing:
    def test_parses_a_command_with_arguments(self):
        assert parse_command("/price 4000 6000") == ("price", ["4000", "6000"])

    def test_parses_a_bare_command(self):
        assert parse_command("/status") == ("status", [])

    def test_strips_a_bot_mention(self):
        assert parse_command("/status@AptScoutBot") == ("status", [])

    def test_ignores_ordinary_messages(self):
        assert parse_command("hello there") is None
        assert parse_command("") is None
        assert parse_command(None) is None


class TestApplying:
    def test_price_sets_both_bounds(self):
        updated, reply = apply_command(Filters(), "price", ["4000", "6000"])
        assert updated.min_price == 4000
        assert updated.max_price == 6000
        assert "4,000" in reply or "4000" in reply

    def test_radius_sets_the_drive_time(self):
        updated, _ = apply_command(Filters(), "radius", ["25"])
        assert updated.max_drive_minutes == 25

    def test_rooms_sets_the_minimum(self):
        updated, _ = apply_command(Filters(), "rooms", ["3"])
        assert updated.min_rooms == 3

    def test_size_sets_the_minimum(self):
        updated, _ = apply_command(Filters(), "size", ["60"])
        assert updated.min_size_sqm == 60

    def test_pause_and_resume_toggle_alerting(self):
        paused, _ = apply_command(Filters(), "pause", [])
        assert paused.paused is True
        resumed, _ = apply_command(paused, "resume", [])
        assert resumed.paused is False

    def test_status_reports_without_changing_anything(self):
        original = Filters()
        updated, reply = apply_command(original, "status", [])
        assert updated.to_dict() == original.to_dict()
        assert "4000" in reply or "4,000" in reply

    def test_bad_arguments_explain_the_usage_and_change_nothing(self):
        original = Filters()
        updated, reply = apply_command(original, "price", ["abc"])
        assert updated.to_dict() == original.to_dict()
        assert "/price" in reply

    def test_missing_arguments_explain_the_usage(self):
        updated, reply = apply_command(Filters(), "price", ["4000"])
        assert updated.max_price == Filters().max_price
        assert "/price" in reply

    def test_an_unknown_command_lists_what_is_available(self):
        _, reply = apply_command(Filters(), "teleport", [])
        assert "/price" in reply and "/radius" in reply


class TestPausedFiltersRejectEverything:
    def test_paused_blocks_all_alerts(self):
        from apt_scout.models import Listing, Occupancy

        listing = Listing(
            source="yad2",
            source_id="1",
            url="https://y/1",
            price=4800,
            rooms=3.0,
            size_sqm=70.0,
            occupancy=Occupancy.WHOLE,
        )
        assert Filters().matches(listing) is True
        assert Filters(paused=True).matches(listing) is False


class FakeNotifier:
    def __init__(self, updates):
        self._updates = updates
        self.replies = []
        self.offsets = []

    def get_updates(self, offset=None):
        self.offsets.append(offset)
        return self._updates

    def send_text(self, text):
        self.replies.append(text)
        return True


def update(update_id, text):
    return {"update_id": update_id, "message": {"text": text}}


class TestProcessing:
    def test_applies_a_command_and_persists_it(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "/radius 25")])

        result = process_commands(notifier, StateStore(tmp_path), Filters(), path)

        assert result.max_drive_minutes == 25
        assert json.loads(path.read_text("utf-8"))["max_drive_minutes"] == 25
        assert notifier.replies, "the user must get confirmation"

    def test_remembers_the_offset_so_commands_run_once(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        store = StateStore(tmp_path)
        process_commands(FakeNotifier([update(7, "/radius 25")]), store, Filters(), path)

        second = FakeNotifier([])
        process_commands(second, store, Filters(), path)

        assert second.offsets == [8], "must ask only for updates after the last one"

    def test_applies_several_commands_in_order(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "/radius 20"), update(2, "/radius 30")])

        result = process_commands(notifier, StateStore(tmp_path), Filters(), path)

        assert result.max_drive_minutes == 30

    def test_non_command_messages_are_ignored_silently(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "good morning")])

        process_commands(notifier, StateStore(tmp_path), Filters(), path)

        assert notifier.replies == []

    def test_a_polling_failure_leaves_filters_untouched(self, tmp_path):
        class Broken:
            def get_updates(self, offset=None):
                raise RuntimeError("telegram down")

            def send_text(self, text):
                return True

        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")

        result = process_commands(Broken(), StateStore(tmp_path), Filters(), path)

        assert result.to_dict() == Filters().to_dict()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_commands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apt_scout.notify.commands'`

- [ ] **Step 3: Add `paused` to `Filters`**

In `src/apt_scout/filters.py`, add the field after `include_unsure_occupancy`:

```python
    paused: bool = False
```

Add this as the first check inside `matches`, before the occupancy check:

```python
        if self.paused:
            return False
```

Add `"paused": false` to `config/filters.json`.

- [ ] **Step 4: Add `get_updates` to the notifier**

In `src/apt_scout/notify/telegram.py`, add this method to `TelegramNotifier`:

```python
    def get_updates(self, offset: int | None = None) -> list[dict]:
        """Poll for messages sent to the bot.

        Raises on failure so the caller can leave configuration untouched
        rather than acting on a partial view of the user's instructions.
        """
        url = API_BASE.format(token=self._token, method="getUpdates")
        payload: dict = {"timeout": 0}
        if offset is not None:
            payload["offset"] = offset
        response = self._client.post(url, json=payload)
        return response.json().get("result", [])
```

- [ ] **Step 5: Implement the command processor**

Create `src/apt_scout/notify/commands.py`:

```python
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ..filters import Filters
from ..state import StateStore

OFFSET = "telegram_offset"

USAGE = (
    "פקודות זמינות:\n"
    "/price <מינימום> <מקסימום>\n"
    "/radius <דקות נסיעה>\n"
    "/rooms <מינימום חדרים>\n"
    "/size <מינימום מ\"ר>\n"
    "/pause — עצירת התראות\n"
    "/resume — חידוש התראות\n"
    "/status — הצגת ההגדרות"
)


def parse_command(text: str | None) -> tuple[str, list[str]] | None:
    """Split a Telegram message into a command and its arguments."""
    if not text or not text.startswith("/"):
        return None
    parts = text.split()
    # "/status@MyBot" is what Telegram sends in group chats.
    command = parts[0][1:].split("@")[0].lower()
    return command, parts[1:]


def _describe(filters: Filters) -> str:
    state = "מושהה" if filters.paused else "פעיל"
    return (
        f"סטטוס: {state}\n"
        f"מחיר: {filters.min_price:,}–{filters.max_price:,} ₪\n"
        f"נסיעה: עד {filters.max_drive_minutes:g} דק'\n"
        f"חדרים: מ-{filters.min_rooms:g}\n"
        f'שטח: מ-{filters.min_size_sqm:g} מ"ר'
    )


def _numbers(args: list[str], count: int) -> list[float] | None:
    if len(args) != count:
        return None
    try:
        return [float(a) for a in args]
    except ValueError:
        return None


def apply_command(
    filters: Filters, command: str, args: list[str]
) -> tuple[Filters, str]:
    """Apply one command, returning the new filters and a reply.

    Invalid input never changes configuration; it returns the original filters
    with a usage message, so a typo cannot silently widen the alert criteria.
    """
    if command == "status":
        return filters, _describe(filters)

    if command == "pause":
        updated = replace(filters, paused=True)
        return updated, "התראות הושהו. /resume כדי לחדש."

    if command == "resume":
        updated = replace(filters, paused=False)
        return updated, "התראות חודשו.\n" + _describe(updated)

    if command == "price":
        values = _numbers(args, 2)
        if values is None or values[0] > values[1]:
            return filters, "שימוש: /price 4000 5500"
        updated = replace(filters, min_price=int(values[0]), max_price=int(values[1]))
        return updated, _describe(updated)

    if command == "radius":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /radius 15"
        updated = replace(filters, max_drive_minutes=values[0])
        return updated, _describe(updated)

    if command == "rooms":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /rooms 2"
        updated = replace(filters, min_rooms=values[0])
        return updated, _describe(updated)

    if command == "size":
        values = _numbers(args, 1)
        if values is None:
            return filters, 'שימוש: /size 50'
        updated = replace(filters, min_size_sqm=values[0])
        return updated, _describe(updated)

    return filters, USAGE


def process_commands(
    notifier,
    store: StateStore,
    filters: Filters,
    filters_path: Path,
) -> Filters:
    """Poll Telegram, apply any commands, and persist the result.

    A polling failure is swallowed: the run continues with the existing
    configuration rather than being lost to a Telegram outage.
    """
    offset = store.load(OFFSET, None)
    try:
        updates = notifier.get_updates(offset=offset)
    except Exception:  # noqa: BLE001 - a poll failure must not fail the run
        return filters

    changed = False
    highest: int | None = None

    for item in updates:
        highest = max(highest or 0, item.get("update_id", 0))
        text = (item.get("message") or {}).get("text")
        parsed = parse_command(text)
        if parsed is None:
            continue
        command, args = parsed
        filters, reply = apply_command(filters, command, args)
        changed = True
        notifier.send_text(reply)

    if highest is not None:
        store.save(OFFSET, highest + 1)

    if changed:
        Path(filters_path).write_text(
            json.dumps(filters.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    return filters
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_commands.py -v`
Expected: PASS, 20 passed

- [ ] **Step 7: Poll for commands at the start of each run**

In `src/apt_scout/__main__.py`, add the import:

```python
from .notify.commands import process_commands
```

In `main`, immediately after `runtime = build_runtime(...)` and before
`run_pipeline(...)`, add:

```python
    if not args.dry_run:
        runtime.filters = process_commands(
            runtime.notifier,
            runtime.store,
            runtime.filters,
            Path(args.repo) / "config" / "filters.json",
        )
```

Commands are applied before the scan so a threshold change takes effect on the
same run that reads it.

- [ ] **Step 8: Commit the changed filters file from the workflow**

In `.github/workflows/scan.yml`, change the `git add state` line in the
`Commit state` step to:

```yaml
          git add state config/filters.json
```

- [ ] **Step 9: Document the commands in `README.md`**

Add before "Required repository secrets":

````markdown
## Changing alert thresholds from your phone

Message the bot; changes apply on the next hourly run and are committed to
`config/filters.json`.

| Command | Effect |
|---|---|
| `/price 4000 5500` | Set the price range |
| `/radius 15` | Set maximum driving minutes |
| `/rooms 2` | Set the minimum room count |
| `/size 50` | Set the minimum size in m² |
| `/pause` / `/resume` | Stop and restart alerts |
| `/status` | Show the current thresholds |

These control **alerts**. The portal's sliders control **display**, and the two
are deliberately independent so you can browse more loosely than you are
interrupted.
````

- [ ] **Step 10: Run the whole suite**

Run: `python -m pytest tests/ -v`
Expected: PASS, all tests

- [ ] **Step 11: Commit**

```bash
git add src/apt_scout/notify src/apt_scout/filters.py src/apt_scout/__main__.py config/filters.json .github/workflows/scan.yml README.md tests/test_commands.py
git commit -m "feat: add Telegram commands for changing alert thresholds"
```

---

## User setup, once the code is in place

1. Create a public GitHub repository and push this code.
2. Message `@BotFather` on Telegram, run `/newbot`, and copy the token.
3. Message the new bot once, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`.
4. Under Settings → Secrets and variables → Actions, add `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, and `PHONE_HASH_SALT` (any long random string).
5. Under Settings → Pages, set the source to the `gh-pages` branch.
6. Run the `scan` workflow manually once from the Actions tab to confirm it
   works before relying on the hourly schedule.
7. Message the bot `/status` to confirm two-way control is working.

---

## What comes next

Phases 4–7 from the design document get their own plan once this foundation is
proven in production: the remaining five free adapters and Facebook Marketplace,
cross-source clustering, Facebook groups with the budget guard, and the daily
Claude agent. Clustering in particular is deliberately deferred, since it cannot
be tested meaningfully until several sources are live.
