from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag

from ..models import Listing, Occupancy
from .base import AdapterResult

BASE_URL = "https://www.homeless.co.il"

# Column keys, in the fixed order they appear in the results table (both the
# header row's `<th orderfield=...>` attributes and each data row's `<td>`
# cells follow this order). Used to build an orderfield -> cell-index map
# from whichever header row is present in the page.
_COLUMN_FIELDS = [
    "vcFileName1",  # image
    "iNumber3",  # type (סוג הנכס)
    "vcTextShort2",  # city (עיר)
    "vcTextShort10",  # neighborhood (שכונה)
    "vcTextShort1",  # street (רחוב)
    "TextNumber4",  # rooms (חדרים)
    "iNumber12",  # floor (קומה)
    "fLong3",  # price (מחיר)
    "dateIn",  # entry date (כניסה)
    "datDatePublish",  # publish date (ת. עידכון)
]

# Positional fallback when no header row with orderfield attributes is
# present: offset by 1 to skip the leading selection/checkbox column.
_POSITIONAL_INDEX_MAP = {field: index + 1 for index, field in enumerate(_COLUMN_FIELDS)}

_ROW_ID_RE = re.compile(r"^ad_(\d+)$")
_ROOMMATE_TYPE_MARKER = "שותפים"


def _price_from_text(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _rooms_from_text(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _floor_from_text(text: str) -> int | None:
    # The floor cell is sometimes non-numeric text ("קרקע" = ground floor);
    # Listing.floor is typed int | None, so anything not a plain digit string
    # stays None rather than being guessed at.
    text = text.strip()
    return int(text) if text.isdigit() else None


def _posted_at_from_text(text: str) -> datetime | None:
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y")
    except ValueError:
        return None


def _occupancy_from_type(text: str) -> Occupancy:
    """Classify occupancy from the "סוג הנכס" (property type) column.

    This is a controlled site vocabulary, not free text, so a simple
    substring check is more reliable here than the generic free-text
    classifier: "שותפים" (roommates) is the only shared-occupancy value;
    every other non-empty type (דירה, פנטהאוז, בית פרטי, ...) is a whole
    property.
    """
    if not text:
        return Occupancy.UNSURE
    if _ROOMMATE_TYPE_MARKER in text:
        return Occupancy.ROOMMATES
    return Occupancy.WHOLE


def _column_index_map(table: Tag | None) -> dict[str, int]:
    """Map each known orderfield key to its cell index in a data row.

    Reads the header row's `<th orderfield=...>` attributes so a reordered
    column doesn't silently corrupt fields. Falls back to the fixed
    positional order when no header row with orderfield attributes is found.
    """
    if table is not None:
        header_row = None
        for tr in table.find_all("tr"):
            if tr.find("th") is not None:
                header_row = tr
                break

        if header_row is not None:
            index_map: dict[str, int] = {}
            for index, th in enumerate(header_row.find_all("th")):
                field = th.get("orderfield")
                if isinstance(field, str) and field in _COLUMN_FIELDS:
                    index_map[field] = index
            if index_map:
                return index_map

    return dict(_POSITIONAL_INDEX_MAP)


def _cell_text(cells: list[Tag], index: int | None) -> str:
    if index is None or index >= len(cells):
        return ""
    return cells[index].get_text(strip=True)


def _listing_url(row: Tag, source_id: str) -> str:
    link = row.select_one('a[href*="viewad,"]')
    href = link.get("href") if link else None
    if isinstance(href, str) and href:
        if href.startswith("http"):
            return href
        return f"{BASE_URL}{href}"
    return f"{BASE_URL}/rent/viewad,{source_id}.aspx"


def _address_text(street: str, neighborhood: str, city: str) -> str | None:
    parts = [part for part in (street, neighborhood, city) if part]
    return ", ".join(parts) or None


def parse_homeless_html(html: str) -> list[Listing]:
    """Convert one homeless.co.il city search-results page into Listings.

    Rows are `<tr id="ad_{id}">` inside the results table; columns are
    resolved via the header's `orderfield` attributes (falling back to
    position when absent). No price/rooms filtering happens here - the
    site does not support it via GET, and the pipeline's filter engine
    handles it downstream. Anything missing on a row stays None rather
    than defaulting.
    """
    if not isinstance(html, str):
        raise TypeError(f"expected str HTML, got {type(html).__name__}")

    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr", id=_ROW_ID_RE)
        if not rows:
            continue
        index_map = _column_index_map(table)

        for row in rows:
            match = _ROW_ID_RE.match(row.get("id", ""))
            if not match:
                continue
            source_id = match.group(1)
            cells = row.find_all("td")

            type_text = _cell_text(cells, index_map.get("iNumber3"))
            city = _cell_text(cells, index_map.get("vcTextShort2")) or None
            neighborhood = _cell_text(cells, index_map.get("vcTextShort10"))
            street = _cell_text(cells, index_map.get("vcTextShort1"))

            listings.append(
                Listing(
                    source="homeless",
                    source_id=source_id,
                    url=_listing_url(row, source_id),
                    price=_price_from_text(_cell_text(cells, index_map.get("fLong3"))),
                    rooms=_rooms_from_text(_cell_text(cells, index_map.get("TextNumber4"))),
                    floor=_floor_from_text(_cell_text(cells, index_map.get("iNumber12"))),
                    city=city,
                    address_text=_address_text(street, neighborhood, city or ""),
                    occupancy=_occupancy_from_type(type_text),
                    posted_at=_posted_at_from_text(
                        _cell_text(cells, index_map.get("datDatePublish"))
                    ),
                )
            )

    return listings


class HomelessAdapter:
    name = "homeless"

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        try:
            url_template = config["url_template"]
        except KeyError as exc:
            return AdapterResult(source=self.name, error=f"bad source config: {exc}")

        cities = config.get("cities") or []
        if not cities:
            return AdapterResult(source=self.name, error="bad source config: 'cities' is required")

        min_tier = config.get("min_tier", "http")

        all_listings: list[Listing] = []
        last_error: str | None = None

        for city in cities:
            try:
                url = url_template.format(city=quote(city, safe=""))
            except (KeyError, IndexError) as exc:
                last_error = f"{city}: bad url_template: {exc}"
                continue

            try:
                response = fetcher.get(url, min_tier=min_tier)
            except Exception as exc:  # noqa: BLE001 - reported, never raised
                last_error = f"{city}: fetch failed: {exc}"
                continue

            try:
                city_listings = parse_homeless_html(response.text)
            except Exception as exc:  # noqa: BLE001 - a markup change must not crash
                last_error = f"{city}: parse failed: {exc}"
                continue

            all_listings.extend(city_listings)

        if not all_listings and last_error is not None:
            return AdapterResult(source=self.name, error=last_error)

        limit = config.get("max_results")
        if limit:
            all_listings = all_listings[:limit]
        return AdapterResult(source=self.name, listings=all_listings)
