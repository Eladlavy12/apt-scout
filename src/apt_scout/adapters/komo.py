from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from ..models import Listing, Occupancy
from .base import AdapterResult

BASE_URL = "https://www.komo.co.il"

# Field-path notes (verified against the real captured fixture; see
# .superpowers/sdd + scratchpad RECIPE.md for how it was recon'd):
# - organic listing cards are `div.modaaRowAd` with `id="modaaRowDv{ID}"` and a
#   `key="{ID}"` attribute.
# - the single sponsored/PPC card per page (`modaaPPC__box`) has neither a
#   `modaaRowDv*` id nor a `key` attribute, so scoping on both filters it out.
_ROOMS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*חדרים")
_SIZE_RE = re.compile(r'\((\d+)\s*מ"ר\)')
_FLOOR_RE = re.compile(r"קומה:\s*(\S+)\s*מתוך\s*(\d+)")
_MODAA_NUM_RE = re.compile(r"modaaNum=(\d+)")


def _price_from_text(text: str) -> int | None:
    match = re.search(r"[\d,]+", text)
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    return int(digits) if digits.isdigit() else None


def _listing_id(card: Tag) -> str | None:
    key = card.get("key")
    if isinstance(key, str) and key:
        return key
    card_id = card.get("id")
    if isinstance(card_id, str) and card_id.startswith("modaaRowDv"):
        return card_id[len("modaaRowDv") :] or None
    return None


def _listing_url(card: Tag, source_id: str) -> str:
    link = card.select_one("a[href]")
    href = link.get("href") if link else None
    if isinstance(href, str) and href:
        if href.startswith("http"):
            return href
        return f"{BASE_URL}{href}"
    return f"{BASE_URL}/code/nadlan/details/?modaaNum={source_id}"

def _price(card: Tag) -> int | None:
    price_div = card.select_one("div.price")
    if price_div is None:
        return None
    return _price_from_text(price_div.get_text())


def _title_parts(card: Tag) -> list[str]:
    title = card.select_one("h2.title")
    if title is None:
        return []
    text = re.sub(r"\s+", " ", title.get_text()).strip()
    return [part.strip() for part in text.split(",") if part.strip()]


def _rooms_and_size(card: Tag) -> tuple[float | None, float | None, int | None]:
    desc = card.select_one("div.description")
    if desc is None:
        return None, None, None
    text = desc.get_text()

    rooms_match = _ROOMS_RE.search(text)
    rooms = float(rooms_match.group(1)) if rooms_match else None

    size_match = _SIZE_RE.search(text)
    size = float(size_match.group(1)) if size_match else None

    floor_match = _FLOOR_RE.search(text)
    floor: int | None = None
    if floor_match and floor_match.group(1).isdigit():
        floor = int(floor_match.group(1))

    return rooms, size, floor


def parse_komo_html(html: str) -> list[Listing]:
    """Convert one komo.co.il search-results page into Listings.

    Scoped to organic `div.modaaRowAd` cards only; the sponsored/PPC card
    that appears once per page has no `key`/`modaaRowDv*` id and is skipped.
    Anything missing on a card stays None rather than defaulting.
    """
    if not isinstance(html, str):
        raise TypeError(f"expected str HTML, got {type(html).__name__}")

    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []

    for card in soup.select("div.modaaRowAd"):
        source_id = _listing_id(card)
        if not source_id:
            continue

        title_parts = _title_parts(card)
        city = title_parts[0] if title_parts else None
        rooms, size_sqm, floor = _rooms_and_size(card)

        listings.append(
            Listing(
                source="komo",
                source_id=source_id,
                url=_listing_url(card, source_id),
                price=_price(card),
                rooms=rooms,
                size_sqm=size_sqm,
                floor=floor,
                city=city,
                address_text=", ".join(title_parts) or None,
                # komo's apartments-for-rent search lists whole properties
                # only; there is no roommate-ad category on this path.
                occupancy=Occupancy.WHOLE,
            )
        )

    return listings


class KomoAdapter:
    name = "komo"

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        try:
            base_url = config["url_template"].format(
                city=config.get("city", ""),
                price_min=config.get("price_min", 0),
                price_max=config.get("price_max", 100000),
                rooms_min=config.get("rooms_min", 1),
            )
        except (KeyError, IndexError) as exc:
            return AdapterResult(source=self.name, error=f"bad source config: {exc}")

        min_tier = config.get("min_tier", "http")
        max_pages = config.get("max_pages", 2)
        separator = "&" if "?" in base_url else "?"

        all_listings: list[Listing] = []
        for page in range(1, max_pages + 1):
            url = f"{base_url}{separator}currPage={page}"

            try:
                response = fetcher.get(url, min_tier=min_tier)
            except Exception as exc:  # noqa: BLE001 - reported, never raised
                if page == 1:
                    return AdapterResult(source=self.name, error=f"fetch failed: {exc}")
                break  # a later page failing degrades the run, not fails it

            try:
                page_listings = parse_komo_html(response.text)
            except Exception as exc:  # noqa: BLE001 - a markup change must not crash
                if page == 1:
                    return AdapterResult(source=self.name, error=f"parse failed: {exc}")
                break

            if not page_listings:
                break  # server signalled "no more results" for this filter

            all_listings.extend(page_listings)

        limit = config.get("max_results")
        if limit:
            all_listings = all_listings[:limit]
        return AdapterResult(source=self.name, listings=all_listings)
