from pathlib import Path

from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.prog import (
    BASE_URL,
    DEFAULT_BOARD_URL,
    ProgAdapter,
    parse_prog_board,
    parse_prog_detail,
)
from apt_scout.fetch import FetchError, FetchResult
from apt_scout.models import Occupancy

BOARD_FIXTURE = Path(__file__).parent / "fixtures" / "prog_board.html"
DETAIL_FIXTURE = Path(__file__).parent / "fixtures" / "prog_detail.html"

# Known board-level "prefix" badge city names that appear in the real fixture
# (see RECIPE.md). Used to assert the title-link-vs-badge-link pitfall is
# handled: a naively-selected first <a> would grab one of these instead of
# the real listing title.
KNOWN_BADGE_CITIES = {"ירושלים", "בני ברק", "ביתר עילית", "אזור הדרום"}


def structitem_html(
    listing_id,
    title="דירת 3 חדרים להשכרה",
    price_label="₪5,000.00",
    city_badge=None,
    date_iso="2026-08-20T10:00:00+0300",
    featured=False,
    expired=False,
):
    classes = ["structItem", "structItem--listing"]
    if expired:
        classes.append("is-expired")
    if featured:
        classes.append("PFeaturedListing")
    badge_html = (
        f'<a class="labelLink" href="/classifieds/categories/x.52/?prefix_id=1">{city_badge}</a>'
        if city_badge
        else ""
    )
    return f"""
    <div class="{' '.join(classes)}">
      <div class="structItem-title">
        {badge_html}
        <a href="/classifieds/listing-slug.{listing_id}/">{title}</a>
        <span class="label--primary label--smallest">{price_label}</span>
      </div>
      <div class="structItem-startDate"><time datetime="{date_iso}">x</time></div>
    </div>
    """


def board_html(*items):
    return f'<html><body><div class="structItemContainer">{"".join(items)}</div></body></html>'


def _detail_url(listing_id):
    return f"{BASE_URL}/classifieds/listing-slug.{listing_id}/"


def _detail_html(rooms="2", floor="3", size="40", city="פתח תקווה", price="₪4,000.00", title="כותרת מפורטת"):
    return f"""
    <html><body>
    <h2 class="listing-title">{title}</h2>
    <dl class="pairs pairs--justified"><dt>מחיר</dt><dd>{price}</dd></dl>
    <dl class="pairs pairs--customField" data-field="SITI"><dt>עיר</dt><dd>{city}</dd></dl>
    <dl class="pairs pairs--customField" data-field="rooms2"><dt>מספר חדרים</dt><dd>{rooms}</dd></dl>
    <dl class="pairs pairs--customField" data-field="floor2"><dt>קומה</dt><dd>{floor}</dd></dl>
    <dl class="pairs pairs--customField" data-field="Apartment_size"><dt>גודל הדירה (במ"ר)</dt><dd>{size}</dd></dl>
    </body></html>
    """


class TestBoardParsing:
    def test_parses_real_fixture_dedupes_and_extracts_core_fields(self):
        html = BOARD_FIXTURE.read_text(encoding="utf-8")
        entries = parse_prog_board(html)

        assert len(entries) >= 10
        ids = [e["id"] for e in entries]
        assert len(ids) == len(set(ids))  # deduped: no duplicate ids

        badge_cities = {e["city_badge"] for e in entries if e["city_badge"]}
        assert badge_cities  # the fixture does carry some badges
        # title-link-vs-badge pitfall: no title should equal a badge city name
        assert not any(e["title"] in badge_cities for e in entries)
        assert not any(e["title"] in KNOWN_BADGE_CITIES for e in entries)

        priced = [e for e in entries if e["price"] is not None]
        assert priced
        for e in priced:
            assert isinstance(e["price"], int)
            assert e["price"] > 0
        # the "no price specified" sentinel is present in the fixture
        assert any(e["price"] is None and e["price_text"] for e in entries)

        assert all(e["url"].startswith("https://www.prog.co.il") for e in entries)
        assert all(e["id"].isdigit() for e in entries)

    def test_dedupes_by_id_first_occurrence_wins(self):
        html = board_html(
            structitem_html("111", title="First copy", featured=True),
            structitem_html("111", title="Second copy", featured=False),
        )
        entries = parse_prog_board(html)
        assert len(entries) == 1
        assert entries[0]["title"] == "First copy"

    def test_expired_duplicate_entry_still_deduped(self):
        html = board_html(
            structitem_html("222", title="Active copy", expired=False),
            structitem_html("222", title="Expired copy", expired=True),
        )
        entries = parse_prog_board(html)
        assert len(entries) == 1
        assert entries[0]["id"] == "222"

    def test_price_sentinel_becomes_none(self):
        html = board_html(structitem_html("333", price_label="לא צוין מחיר"))
        entry = parse_prog_board(html)[0]
        assert entry["price"] is None
        assert entry["price_text"] == "לא צוין מחיר"

    def test_price_with_currency_and_decimal_parses_to_int(self):
        html = board_html(structitem_html("444", price_label="₪7,500.00"))
        entry = parse_prog_board(html)[0]
        assert entry["price"] == 7500

    def test_city_badge_present_and_not_mistaken_for_title(self):
        html = board_html(structitem_html("555", title="דירת 3 חדרים", city_badge="ירושלים"))
        entry = parse_prog_board(html)[0]
        assert entry["city_badge"] == "ירושלים"
        assert entry["title"] == "דירת 3 חדרים"
        assert "555" in entry["url"]

    def test_no_city_badge_defaults_to_none(self):
        html = board_html(structitem_html("666", city_badge=None))
        entry = parse_prog_board(html)[0]
        assert entry["city_badge"] is None

    def test_date_parses_to_datetime(self):
        html = board_html(structitem_html("777", date_iso="2026-08-20T10:00:00+0300"))
        entry = parse_prog_board(html)[0]
        assert entry["date"] is not None
        assert entry["date"].year == 2026
        assert entry["date"].month == 8
        assert entry["date"].day == 20

    def test_empty_page_returns_empty_list(self):
        assert parse_prog_board("<html><body></body></html>") == []

    def test_non_str_input_raises_type_error(self):
        try:
            parse_prog_board(None)
        except TypeError:
            pass
        else:
            raise AssertionError("expected TypeError")


class TestDetailParsing:
    def test_parses_real_fixture_structured_fields(self):
        html = DETAIL_FIXTURE.read_text(encoding="utf-8")
        board_entry = {
            "id": "12345",
            "url": "https://www.prog.co.il/classifieds/x.12345/",
            "title": "fallback title",
            "price_text": None,
            "price": None,
            "city_badge": None,
            "date": None,
        }

        listing = parse_prog_detail(html, board_entry)

        assert listing.source == "prog"
        assert listing.source_id == "12345"
        assert listing.url == board_entry["url"]
        assert listing.title == "יחידת דיור להשכרה במרכז העיר פתח תקוה"
        assert listing.price == 3500
        assert listing.rooms == 2.0
        assert listing.floor == 4
        assert listing.size_sqm == 35.0
        assert listing.city == "פתח תקווה"
        assert listing.address_text is not None
        assert "רוטשילד" in listing.address_text
        assert listing.occupancy is Occupancy.UNSURE

    def test_missing_custom_fields_become_none_and_fall_back_to_board_entry(self):
        html = "<html><body><h2 class='listing-title'>כותרת</h2></body></html>"
        board_entry = {
            "id": "1",
            "url": "https://x/1",
            "title": "fallback",
            "price_text": "₪1,000.00",
            "price": 1000,
            "city_badge": "עיר לדוגמה",
            "date": None,
        }

        listing = parse_prog_detail(html, board_entry)

        assert listing.rooms is None
        assert listing.floor is None
        assert listing.size_sqm is None
        # price/city missing on the detail page: fall back to board data
        assert listing.price == 1000
        assert listing.city == "עיר לדוגמה"

    def test_price_sentinel_on_detail_falls_back_to_board_price(self):
        html = """<html><body>
        <dl class="pairs pairs--justified"><dt>מחיר</dt><dd>לא צוין מחיר</dd></dl>
        </body></html>"""
        board_entry = {
            "id": "2",
            "url": "https://x/2",
            "title": "t",
            "price_text": "₪2,000.00",
            "price": 2000,
            "city_badge": None,
            "date": None,
        }

        listing = parse_prog_detail(html, board_entry)
        assert listing.price == 2000

    def test_duplicate_customfield_blocks_first_occurrence_wins(self):
        html = """
        <html><body>
        <dl class="pairs pairs--customField" data-field="rooms2"><dt>מספר חדרים</dt><dd>3</dd></dl>
        <dl class="pairs pairs--customField" data-field="rooms2"><dt>מספר חדרים</dt><dd>99</dd></dl>
        </body></html>
        """
        board_entry = {
            "id": "3",
            "url": "https://x/3",
            "title": "t",
            "price_text": None,
            "price": None,
            "city_badge": None,
            "date": None,
        }

        listing = parse_prog_detail(html, board_entry)
        assert listing.rooms == 3.0

    def test_non_str_input_raises_type_error(self):
        board_entry = {
            "id": "1",
            "url": "u",
            "title": "t",
            "price_text": None,
            "price": None,
            "city_badge": None,
            "date": None,
        }
        try:
            parse_prog_detail(None, board_entry)
        except TypeError:
            pass
        else:
            raise AssertionError("expected TypeError")


TEST_BOARD_URL = "https://example.com/board"


class CapturingFetcher:
    """Serves board_text at board_url, and per-URL detail responses/errors."""

    def __init__(self, board_url=TEST_BOARD_URL, board_text=None, board_error=None, detail_map=None, detail_errors=None):
        self.board_url = board_url
        self.board_text = board_text
        self.board_error = board_error
        self.detail_map = detail_map or {}
        self.detail_errors = detail_errors or set()
        self.requested = []

    def get(self, url, min_tier="http", headers=None):
        self.requested.append(url)
        if url == self.board_url:
            if self.board_error:
                raise self.board_error
            return FetchResult(url=url, status=200, text=self.board_text, tier=min_tier)
        if url in self.detail_errors:
            raise FetchError("detail blocked")
        text = self.detail_map.get(url)
        if text is None:
            raise AssertionError(f"unexpected detail fetch for {url}")
        return FetchResult(url=url, status=200, text=text, tier=min_tier)


def _board_html_from_specs(specs):
    """specs: iterable of (id, date_iso) -> board HTML with one entry each."""
    items = [structitem_html(id_, date_iso=date_iso) for id_, date_iso in specs]
    return board_html(*items)


class TestAdapter:
    def test_board_fetch_failure_becomes_error_result(self):
        fetcher = CapturingFetcher(board_error=FetchError("blocked"))
        config = {"board_url": TEST_BOARD_URL}

        result = ProgAdapter().fetch(fetcher, config, since=None)

        assert isinstance(result, AdapterResult)
        assert result.listings == []
        assert result.error is not None
        assert "blocked" in result.error

    def test_board_unparseable_response_becomes_error_result(self):
        fetcher = CapturingFetcher(board_text=None)
        config = {"board_url": TEST_BOARD_URL}

        result = ProgAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None

    def test_board_ok_all_details_fetched_when_under_cap(self):
        specs = [("111", "2026-08-20T10:00:00+0300"), ("222", "2026-08-21T10:00:00+0300")]
        html = _board_html_from_specs(specs)
        detail_map = {
            _detail_url("111"): _detail_html(rooms="2"),
            _detail_url("222"): _detail_html(rooms="3"),
        }
        fetcher = CapturingFetcher(board_text=html, detail_map=detail_map)
        config = {"board_url": TEST_BOARD_URL, "max_details": 5}

        result = ProgAdapter().fetch(fetcher, config, since=None)

        assert result.error is None
        assert len(result.listings) == 2
        rooms_seen = {l.rooms for l in result.listings}
        assert rooms_seen == {2.0, 3.0}
        detail_requests = [u for u in fetcher.requested if u != TEST_BOARD_URL]
        assert len(detail_requests) == 2

    def test_detail_fetch_failure_falls_back_to_board_level_listing(self):
        specs = [("333", "2026-08-20T10:00:00+0300")]
        html = _board_html_from_specs(specs)
        fetcher = CapturingFetcher(board_text=html, detail_errors={_detail_url("333")})
        config = {"board_url": TEST_BOARD_URL}

        result = ProgAdapter().fetch(fetcher, config, since=None)

        assert result.error is None
        assert len(result.listings) == 1
        listing = result.listings[0]
        assert listing.source == "prog"
        assert listing.source_id == "333"
        assert listing.url == _detail_url("333")
        assert listing.price == 5000  # from board price_label default "₪5,000.00"
        assert listing.rooms is None  # detail never fetched successfully
        # classified from the board title alone ("דירת 3 חדרים..." contains
        # the whole-apartment marker "דירת"), which is exactly the
        # board-level fallback behavior being tested here.
        assert listing.occupancy is Occupancy.WHOLE

    def test_skip_ids_respected_no_detail_fetch_but_board_listing_emitted(self):
        specs = [("444", "2026-08-20T10:00:00+0300"), ("555", "2026-08-21T10:00:00+0300")]
        html = _board_html_from_specs(specs)
        detail_map = {_detail_url("555"): _detail_html(rooms="4")}
        fetcher = CapturingFetcher(board_text=html, detail_map=detail_map)
        config = {"board_url": TEST_BOARD_URL, "skip_ids": ["444"]}

        result = ProgAdapter().fetch(fetcher, config, since=None)

        assert result.error is None
        assert len(result.listings) == 2
        assert _detail_url("444") not in fetcher.requested
        assert _detail_url("555") in fetcher.requested
        by_id = {l.source_id: l for l in result.listings}
        assert by_id["444"].rooms is None  # board-level only, not fetched
        assert by_id["555"].rooms == 4.0

    def test_max_details_cap_honored_newest_first(self):
        specs = [(str(100 + i), f"2026-08-{20 + i:02d}T10:00:00+0300") for i in range(5)]
        html = _board_html_from_specs(specs)
        detail_map = {_detail_url(id_): _detail_html(rooms="2") for id_, _ in specs}
        fetcher = CapturingFetcher(board_text=html, detail_map=detail_map)
        config = {"board_url": TEST_BOARD_URL, "max_details": 2}

        result = ProgAdapter().fetch(fetcher, config, since=None)

        assert result.error is None
        assert len(result.listings) == 5
        detail_requests = [u for u in fetcher.requested if u != TEST_BOARD_URL]
        assert len(detail_requests) == 2
        # newest first: the two latest-dated ids (104, 103) are the ones detail-fetched
        assert _detail_url("104") in detail_requests
        assert _detail_url("103") in detail_requests
        assert _detail_url("100") not in detail_requests

    def test_uses_default_board_url_when_not_configured(self):
        html = _board_html_from_specs([("1", "2026-08-01T00:00:00+0300")])
        fetcher = CapturingFetcher(board_url=DEFAULT_BOARD_URL, board_text=html)

        result = ProgAdapter().fetch(fetcher, {}, since=None)

        assert result.error is None
        assert DEFAULT_BOARD_URL in fetcher.requested

    def test_name_is_prog(self):
        assert ProgAdapter().name == "prog"
