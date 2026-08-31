from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from ..enrich.occupancy import classify_occupancy
from ..models import Listing
from .base import AdapterResult

BASE_URL = "https://www.prog.co.il"

# Rentals classifieds category (52, "לוח נדל"ן להשכרה"). No RSS controller
# exists for XenForo Classifieds on this install (verified in recon - see
# .superpowers/sdd + scratchpad RECIPE.md), so the board is a plain HTML GET,
# re-fetched and diffed by id on every run.
DEFAULT_BOARD_URL = (
    "https://www.prog.co.il/classifieds/categories/"
    "%D7%9C%D7%95%D7%97-%D7%A0%D7%93%D7%9C-%D7%9F-%D7%9C%D7%94%D7%A9%D7%9B%D7%A8%D7%94.52/"
)

# Trailing ".<digits>/" segment of a listing permalink slug is its id, e.g.
# ".../יחידת-דיור...68815/" -> "68815".
_ID_RE = re.compile(r"\.(\d+)/?$")

_PRICE_DIGITS_RE = re.compile(r"[\d,]+")

_NO_PRICE_SENTINEL = "לא צוין מחיר"


def _absolute_url(href: str) -> str:
    if href.startswith("http"):
        return href
    return f"{BASE_URL}{href}"


def _price_from_text(text: str | None) -> int | None:
    """Parse a "₪N,NNN.00" price label to an int.

    Also normalizes the "לא צוין מחיר" (no price specified) sentinel used at
    both board and detail level to None - it has no digits, so the regex
    simply finds nothing and returns None without a special case.
    """
    if not text:
        return None
    match = _PRICE_DIGITS_RE.search(text)
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    return int(digits) if digits.isdigit() else None


def _to_float(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def _to_int(text: str | None) -> int | None:
    value = _to_float(text)
    return int(value) if value is not None else None


def _posted_at_from_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _board_entry_id(url: str) -> str | None:
    match = _ID_RE.search(url)
    return match.group(1) if match else None


def _parse_board_item(node: Tag) -> dict | None:
    title_div = node.select_one(".structItem-title")
    if title_div is None:
        return None

    # Pitfall: a listing can carry an optional "prefix" city/region badge -
    # `a.labelLink` - as the FIRST <a> in the title block, ahead of the real
    # permalink <a>. Naively taking the first <a> grabs the badge (which
    # links back to the category filter) instead of the listing.
    badge_a = title_div.select_one("a.labelLink")
    city_badge = badge_a.get_text(strip=True) if badge_a else None

    title_a = None
    for a in title_div.find_all("a", recursive=False):
        if a is badge_a:
            continue
        title_a = a
        break
    if title_a is None:
        return None

    href = title_a.get("href")
    if not isinstance(href, str) or not href:
        return None
    listing_id = _board_entry_id(href)
    if not listing_id:
        return None

    title = title_a.get_text(strip=True)

    price_label = title_div.select_one(".label--primary.label--smallest")
    price_text = price_label.get_text(strip=True) if price_label else None

    date_time = node.select_one(".structItem-startDate time")
    date_iso = date_time.get("datetime") if date_time else None

    node_classes = node.get("class") or []
    is_expired = "is-expired" in node_classes

    return {
        "id": listing_id,
        "url": _absolute_url(href),
        "title": title,
        "price_text": price_text,
        "price": _price_from_text(price_text),
        "city_badge": city_badge,
        "date": _posted_at_from_iso(date_iso if isinstance(date_iso, str) else None),
        "is_expired": is_expired,
    }


def parse_prog_board(html: str) -> list[dict]:
    """Convert one prog.co.il classifieds category page into board entries.

    Each listing is `div.structItem.structItem--listing`. Featured/promoted
    listings can appear twice in the DOM (once pinned near the top, once
    again in normal chronological position), so entries are deduped by id,
    first occurrence wins - regardless of expired status, since an
    is-expired duplicate and its active twin share the same id.

    Each entry carries `is_expired: bool`, taken from the `is-expired` class
    on the listing's outer block. This function does not filter expired
    entries out - that's the adapter's job (expired posts must not become
    Listings or alerts); the parse level reports the board as-is.

    Anything missing on an entry stays None rather than defaulting.
    """
    if not isinstance(html, str):
        raise TypeError(f"expected str HTML, got {type(html).__name__}")

    soup = BeautifulSoup(html, "html.parser")
    seen_ids: set[str] = set()
    entries: list[dict] = []

    for node in soup.select("div.structItem.structItem--listing"):
        entry = _parse_board_item(node)
        if entry is None:
            continue
        if entry["id"] in seen_ids:
            continue
        seen_ids.add(entry["id"])
        entries.append(entry)

    return entries


def _detail_price(soup: BeautifulSoup) -> int | None:
    """The price lives in a plain (non-customField) `dl.pairs`, dt == 'מחיר'."""
    for dl in soup.select("dl.pairs"):
        classes = dl.get("class", [])
        if "pairs--customField" in classes:
            continue
        dt = dl.find("dt")
        if dt is not None and dt.get_text(strip=True) == "מחיר":
            dd = dl.find("dd")
            return _price_from_text(dd.get_text(strip=True) if dd else None)
    return None


def _detail_custom_fields(soup: BeautifulSoup) -> dict[str, str | None]:
    """Structured custom fields, keyed by `data-field`.

    The whole custom-fields block is duplicated once in the page (once as
    real content, once inside a "quick view" overlay template), so this
    dedupes by data-field, first occurrence wins.
    """
    fields: dict[str, str | None] = {}
    for dl in soup.select("dl.pairs--customField"):
        field_key = dl.get("data-field")
        if not isinstance(field_key, str) or field_key in fields:
            continue
        dd = dl.find("dd")
        fields[field_key] = dd.get_text(" ", strip=True) if dd else None
    return fields


def parse_prog_detail(html: str, board_entry: dict) -> Listing:
    """Convert one prog.co.il classifieds detail page into a full Listing.

    Price/rooms/size/city are genuine structured "custom fields"
    (`dl.pairs--customField[data-field=...]`) on this board, not something
    that needs regexing out of free text. Any field missing on the page
    (not every property type carries every field) falls back to the
    corresponding board-level value rather than being guessed at.
    """
    if not isinstance(html, str):
        raise TypeError(f"expected str HTML, got {type(html).__name__}")

    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one("h2.listing-title")
    title = title_el.get_text(strip=True) if title_el else None
    title = title or board_entry.get("title")

    fields = _detail_custom_fields(soup)

    price = _detail_price(soup)
    if price is None:
        price = board_entry.get("price")

    city = fields.get("SITI") or board_entry.get("city_badge")
    neighborhood = fields.get("neighborhood")
    address_text = ", ".join(part for part in (neighborhood, city) if part) or None

    rooms = _to_float(fields.get("rooms2"))
    floor = _to_int(fields.get("floor2"))
    size_sqm = _to_float(fields.get("Apartment_size"))

    desc_el = soup.select_one(".listing-description")
    description = desc_el.get_text(" ", strip=True) if desc_el else ""

    occupancy_text = " ".join(
        part
        for part in (
            title,
            fields.get("Property_Type2"),
            fields.get("Apartment_characteristics"),
            description,
        )
        if part
    )

    return Listing(
        source="prog",
        source_id=str(board_entry.get("id") or ""),
        url=str(board_entry.get("url") or ""),
        title=title,
        raw_text=description or None,
        price=price,
        rooms=rooms,
        size_sqm=size_sqm,
        floor=floor,
        city=city,
        address_text=address_text,
        occupancy=classify_occupancy(occupancy_text),
        posted_at=board_entry.get("date"),
    )


def _listing_from_board_entry(entry: dict) -> Listing:
    """A board-only Listing, used when a detail page is skipped or fails.

    Only what the board itself carries (title/price/url) is populated;
    occupancy is classified from the title alone, so UNSURE is the likely
    (and acceptable) outcome absent the detail page's richer text.
    """
    title = entry.get("title")
    return Listing(
        source="prog",
        source_id=str(entry.get("id") or ""),
        url=str(entry.get("url") or ""),
        title=title,
        price=entry.get("price"),
        city=entry.get("city_badge"),
        address_text=entry.get("city_badge"),
        occupancy=classify_occupancy(title),
        posted_at=entry.get("date"),
    )


class ProgAdapter:
    name = "prog"

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        board_url = config.get("board_url", DEFAULT_BOARD_URL)
        min_tier = config.get("min_tier", "http")

        try:
            response = fetcher.get(board_url, min_tier=min_tier)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return AdapterResult(source=self.name, error=f"board fetch failed: {exc}")

        try:
            entries = parse_prog_board(response.text)
        except Exception as exc:  # noqa: BLE001 - a markup change must not crash
            return AdapterResult(source=self.name, error=f"board parse failed: {exc}")

        # Expired posts must never become a Listing or an alert - drop them
        # before sorting/budgeting so they don't consume the detail-fetch cap.
        active_entries = [e for e in entries if not e.get("is_expired")]

        skip_ids = {str(i) for i in config.get("skip_ids", [])}
        max_details = config.get("max_details", 5)

        # Newest first, so the limited detail-fetch budget goes to the
        # freshest listings; entries with no parseable date sort last. A
        # tuple key keeps this from ever comparing a timezone-aware date
        # (parsed from the board's "+0300" offsets) to a naive sentinel,
        # which raises TypeError - dateless entries just sort as "oldest".
        def _sort_key(entry: dict) -> tuple[int, str]:
            moment = entry.get("date")
            return (1, moment.isoformat()) if moment is not None else (0, "")

        sorted_entries = sorted(active_entries, key=_sort_key, reverse=True)

        listings: list[Listing] = []
        details_fetched = 0

        for entry in sorted_entries:
            if entry["id"] in skip_ids or details_fetched >= max_details:
                listings.append(_listing_from_board_entry(entry))
                continue

            details_fetched += 1
            try:
                detail_response = fetcher.get(entry["url"], min_tier=min_tier)
            except Exception:  # noqa: BLE001 - degrade to board-level, don't drop
                listings.append(_listing_from_board_entry(entry))
                continue

            try:
                listings.append(parse_prog_detail(detail_response.text, entry))
            except Exception:  # noqa: BLE001 - a markup change must not crash the run
                listings.append(_listing_from_board_entry(entry))

        return AdapterResult(source=self.name, listings=listings)
