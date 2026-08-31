from pathlib import Path

from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.homeless import HomelessAdapter, parse_homeless_html
from apt_scout.fetch import FetchError, FetchResult
from apt_scout.models import Occupancy

FIXTURE = Path(__file__).parent / "fixtures" / "homeless_search.html"

HEADER_ROW = (
    "<tr>"
    "<th>סימון</th>"
    '<th orderfield="vcFileName1">תמונה</th>'
    '<th orderfield="iNumber3">סוג הנכס</th>'
    '<th orderfield="vcTextShort2">עיר</th>'
    '<th orderfield="vcTextShort10">שכונה</th>'
    '<th orderfield="vcTextShort1">רחוב</th>'
    '<th orderfield="TextNumber4">חדרים</th>'
    '<th orderfield="iNumber12">קומה</th>'
    '<th orderfield="fLong3">מחיר</th>'
    '<th orderfield="dateIn">כניסה</th>'
    '<th orderfield="datDatePublish">ת. עידכון</th>'
    "<th>לפרטים</th>"
    "</tr>"
)


def row_html(
    listing_id="98765",
    type_text="דירה",
    city="תל אביב",
    neighborhood="שכונה לדוגמה",
    street="רחוב הרצל 5",
    rooms="3",
    floor="2",
    price_cell="<td>4,800 ₪</td>",
    entry="מיידי",
    publish="15/03/2026",
    with_header=True,
):
    header = HEADER_ROW if with_header else ""
    return f"""
    <table id="mainresults">
    {header}
    <tr id="ad_{listing_id}" type="ad" class="light">
        <td class="selectionarea"><input type="checkbox" /></td>
        <td><div><img src="/pic.jpg" /></div></td>
        <td>{type_text}</td>
        <td>{city}</td>
        <td>{neighborhood}</td>
        <td>{street}</td>
        <td>{rooms}</td>
        <td>{floor}</td>
        {price_cell}
        <td>{entry}</td>
        <td><span class="newmessage">{publish}</span></td>
        <td class="details"><a href="/rent/viewad,{listing_id}.aspx">לפרטים</a></td>
    </tr>
    </table>
    """


class TestParsing:
    def test_extracts_core_fields(self):
        listing = parse_homeless_html(row_html())[0]
        assert listing.source == "homeless"
        assert listing.source_id == "98765"
        assert listing.rooms == 3.0
        assert listing.floor == 2
        assert listing.price == 4800
        assert listing.address_text == "רחוב הרצל 5, שכונה לדוגמה, תל אביב"
        assert listing.url.startswith("https://")
        assert "viewad,98765.aspx" in listing.url

    def test_roommate_type_classified_as_roommates(self):
        listing = parse_homeless_html(row_html(type_text="שותפים"))[0]
        assert listing.occupancy is Occupancy.ROOMMATES

    def test_ordinary_apartment_type_classified_as_whole(self):
        listing = parse_homeless_html(row_html(type_text="דירה"))[0]
        assert listing.occupancy is Occupancy.WHOLE

    def test_price_with_comma_is_parsed_to_int(self):
        listing = parse_homeless_html(row_html(price_cell="<td>4,800 ₪</td>"))[0]
        assert listing.price == 4800

    def test_missing_price_cell_has_none_price(self):
        listing = parse_homeless_html(row_html(price_cell="<td></td>"))[0]
        assert listing.price is None

    def test_publish_date_parses_to_posted_at(self):
        listing = parse_homeless_html(row_html(publish="15/03/2026"))[0]
        assert listing.posted_at is not None
        assert listing.posted_at.year == 2026
        assert listing.posted_at.month == 3
        assert listing.posted_at.day == 15

    def test_unparseable_publish_date_has_none_posted_at(self):
        listing = parse_homeless_html(row_html(publish="גמיש"))[0]
        assert listing.posted_at is None

    def test_falls_back_to_positional_columns_without_header(self):
        listing = parse_homeless_html(row_html(with_header=False))[0]
        assert listing.price == 4800
        assert listing.rooms == 3.0

    def test_empty_page_returns_empty_list(self):
        assert parse_homeless_html("<html><body></body></html>") == []

    def test_non_str_input_raises_type_error(self):
        try:
            parse_homeless_html(None)
        except TypeError:
            pass
        else:
            raise AssertionError("expected TypeError")

    def test_parses_real_fixture(self):
        html = FIXTURE.read_text(encoding="utf-8")
        listings = parse_homeless_html(html)
        assert len(listings) >= 20
        assert all(l.source_id.isdigit() for l in listings)
        priced = [l for l in listings if l.price is not None]
        assert priced
        for l in priced:
            assert 500 <= l.price <= 100000


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


class CitySequenceFetcher:
    """Serves one canned response per successive call, one call per city.

    Each item is either ("text", html) or ("error", exception).
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.requested = []

    def get(self, url, min_tier="http", headers=None):
        self.requested.append((url, min_tier))
        kind, payload = self._responses.pop(0) if self._responses else ("text", "")
        if kind == "error":
            raise payload
        return FetchResult(url=url, status=200, text=payload, tier=min_tier)


BASE_CONFIG = {
    "url_template": "https://www.homeless.co.il/rent/city={city}",
    "min_tier": "http",
    "cities": ["תל אביב", "גבעתיים", "רמת גן"],
}


class TestAdapter:
    def test_returns_listings_on_success(self):
        fetcher = FakeFetcher(text=row_html())
        config = dict(BASE_CONFIG)

        result = HomelessAdapter().fetch(fetcher, config, since=None)

        assert isinstance(result, AdapterResult)
        assert result.error is None
        # one row per city, three cities
        assert len(result.listings) == 3
        assert len(fetcher.requested) == 3

    def test_fetches_each_configured_city_with_encoded_url(self):
        fetcher = FakeFetcher(text=row_html())
        config = dict(BASE_CONFIG)

        HomelessAdapter().fetch(fetcher, config, since=None)

        urls = [url for url, _tier in fetcher.requested]
        assert any("%D7%AA%D7%9C%20%D7%90%D7%91%D7%99%D7%91" in u for u in urls)
        assert not any("תל אביב" in u for u in urls)

    def test_uses_the_configured_minimum_tier(self):
        fetcher = FakeFetcher(text=row_html())
        config = dict(BASE_CONFIG, min_tier="browser")

        HomelessAdapter().fetch(fetcher, config, since=None)

        assert fetcher.requested[0][1] == "browser"

    def test_fetch_failure_becomes_an_error_result_not_an_exception(self):
        fetcher = FakeFetcher(error=FetchError("blocked"))
        config = dict(BASE_CONFIG)

        result = HomelessAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert "blocked" in result.error

    def test_unparseable_response_becomes_an_error_result(self):
        fetcher = FakeFetcher(text=None)
        config = dict(BASE_CONFIG)

        result = HomelessAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None

    def test_missing_url_template_becomes_an_error_result(self):
        result = HomelessAdapter().fetch(FakeFetcher(text="{}"), {"cities": ["תל אביב"]}, since=None)
        assert result.listings == []
        assert "url_template" in result.error

    def test_one_city_failing_degrades_to_partial_results(self):
        fetcher = CitySequenceFetcher(
            [
                ("text", row_html("1")),
                ("error", FetchError("blocked")),
                ("text", row_html("3")),
            ]
        )
        config = dict(BASE_CONFIG)

        result = HomelessAdapter().fetch(fetcher, config, since=None)

        assert result.error is None
        assert sorted(l.source_id for l in result.listings) == ["1", "3"]
        assert len(fetcher.requested) == 3

    def test_all_cities_failing_becomes_an_error_result(self):
        fetcher = CitySequenceFetcher(
            [
                ("error", FetchError("blocked 1")),
                ("error", FetchError("blocked 2")),
                ("error", FetchError("blocked 3")),
            ]
        )
        config = dict(BASE_CONFIG)

        result = HomelessAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None
