from pathlib import Path

from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.komo import KomoAdapter, parse_komo_html
from apt_scout.fetch import FetchError, FetchResult
from apt_scout.models import Occupancy

FIXTURE = Path(__file__).parent / "fixtures" / "komo_search.html"


def card_html(
    listing_id="12345",
    price_html='<div class="price">4,500&nbsp;&#8362;</div>',
    description='&nbsp;דירה&nbsp;3.0 חדרים (65 מ&quot;ר) <br> קומה:2 מתוך 4',
    title="תל אביב יפו, התקווה, בועז",
):
    return f"""
    <div id="modaaRowDv{listing_id}" class="modaaRowAd View_Ad_Details modaa__box" key="{listing_id}">
      <div class="image__wrapper">
        <img loading="lazy" src="/api/modaot/tmunot/showPic/list/?picNum=999&luachNum=2&picSize=1">
      </div>
      <div class="contant">
        <a href="/code/nadlan/details/?modaaNum={listing_id}">
          <h2 class="title">{title}</h2>
        </a>
        {price_html}
        <div class="description">
          {description}
          <span id="modaaComment{listing_id}"></span>
        </div>
      </div>
    </div>
    """


def ppc_card_html(listing_id="99999"):
    # Sponsored card: no modaaRowDv id, no key attribute, different class.
    return f"""
    <div id="modaaPPC{listing_id}" class="View_Ad_Details modaaPPC__box">
      <div class="contant">
        <a href="/code/nadlan/details/?modaaNum={listing_id}">
          <h2 class="title">תל אביב יפו, יפו, שדרה 1</h2>
        </a>
        <div class="price">9,999&nbsp;&#8362;</div>
        <div class="description">
          &nbsp;דירה&nbsp;5.0 חדרים (100 מ&quot;ר) <br> קומה:1 מתוך 2
        </div>
      </div>
    </div>
    """


class TestParsing:
    def test_extracts_core_fields(self):
        listing = parse_komo_html(card_html())[0]
        assert listing.source == "komo"
        assert listing.source_id == "12345"
        assert listing.price == 4500
        assert listing.rooms == 3.0
        assert listing.size_sqm == 65.0
        assert listing.url.startswith("https://")
        assert "modaaNum=12345" in listing.url
        assert listing.occupancy is Occupancy.WHOLE

    def test_extracts_photo_url(self):
        listing = parse_komo_html(card_html())[0]
        assert listing.photos == [
            "https://www.komo.co.il/api/modaot/tmunot/showPic/list/?picNum=999&luachNum=2&picSize=1"
        ]

    def test_photo_url_missing_returns_empty_list(self):
        # Card with no image__wrapper
        html_no_img = """
        <div id="modaaRowDv12345" class="modaaRowAd View_Ad_Details modaa__box" key="12345">
          <div class="contant">
            <a href="/code/nadlan/details/?modaaNum=12345">
              <h2 class="title">תל אביב יפו, התקווה, בועז</h2>
            </a>
            <div class="price">4,500&nbsp;&#8362;</div>
            <div class="description">
              &nbsp;דירה&nbsp;3.0 חדרים (65 מ&quot;ר) <br> קומה:2 מתוך 4
            </div>
          </div>
        </div>
        """
        listing = parse_komo_html(html_no_img)[0]
        assert listing.photos == []

    def test_city_parsed_from_title(self):
        listing = parse_komo_html(card_html())[0]
        assert listing.city == "תל אביב יפו"

    def test_card_without_price_has_none_price(self):
        listing = parse_komo_html(card_html(price_html=""))[0]
        assert listing.price is None

    def test_sponsored_card_without_row_dv_id_is_skipped(self):
        html = ppc_card_html() + card_html()
        listings = parse_komo_html(html)
        ids = [l.source_id for l in listings]
        assert "99999" not in ids
        assert "12345" in ids

    def test_empty_page_returns_empty_list(self):
        assert parse_komo_html("<html><body></body></html>") == []

    def test_parses_real_fixture(self):
        html = FIXTURE.read_text(encoding="utf-8")
        listings = parse_komo_html(html)
        assert len(listings) >= 10
        assert all(l.source_id for l in listings)
        priced = [l for l in listings if l.price is not None]
        assert priced
        for l in priced:
            assert 1000 <= l.price <= 50000
        # Verify that photos are extracted from the fixture
        assert any(l.photos for l in listings)


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


class SequenceFetcher:
    """Returns a different response text on each successive call."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.requested = []

    def get(self, url, min_tier="http", headers=None):
        self.requested.append((url, min_tier))
        text = self._texts.pop(0) if self._texts else ""
        return FetchResult(url=url, status=200, text=text, tier=min_tier)


class FailAfterFirstPageFetcher:
    """Serves one good page, then raises FetchError on every call after."""

    def __init__(self, first_page_text):
        self._first_page_text = first_page_text
        self.requested = []

    def get(self, url, min_tier="http", headers=None):
        self.requested.append((url, min_tier))
        if len(self.requested) == 1:
            return FetchResult(url=url, status=200, text=self._first_page_text, tier=min_tier)
        raise FetchError("page 2 blocked")


BASE_CONFIG = {
    "url_template": (
        "https://www.komo.co.il/code/nadlan/apartments-for-rent.asp"
        "?nehes=1&cityName={city}&fromPrice={price_min}&toPrice={price_max}"
        "&fromRooms={rooms_min}"
    ),
    "min_tier": "http",
    "city": "תל אביב יפו",
}


class TestAdapter:
    def test_returns_listings_on_success(self):
        fetcher = FakeFetcher(text=card_html())
        config = dict(BASE_CONFIG, max_pages=1)

        result = KomoAdapter().fetch(fetcher, config, since=None)

        assert isinstance(result, AdapterResult)
        assert result.error is None
        assert len(result.listings) == 1

    def test_uses_the_configured_minimum_tier(self):
        fetcher = FakeFetcher(text=card_html())
        config = dict(BASE_CONFIG, max_pages=1, min_tier="browser")

        KomoAdapter().fetch(fetcher, config, since=None)

        assert fetcher.requested[0][1] == "browser"

    def test_fetch_failure_becomes_an_error_result_not_an_exception(self):
        fetcher = FakeFetcher(error=FetchError("blocked"))
        config = dict(BASE_CONFIG, max_pages=1)

        result = KomoAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert "blocked" in result.error

    def test_unparseable_response_becomes_an_error_result(self):
        # A non-string body (e.g. a transport hiccup) must not raise; it must
        # degrade to an error result on the first page.
        fetcher = FakeFetcher(text=None)
        config = dict(BASE_CONFIG, max_pages=1)

        result = KomoAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None

    def test_missing_url_template_becomes_an_error_result(self):
        result = KomoAdapter().fetch(FakeFetcher(text="{}"), {}, since=None)
        assert result.listings == []
        assert "url_template" in result.error

    def test_paginates_until_an_empty_page_or_max_pages(self):
        fetcher = SequenceFetcher([card_html("1"), card_html("2"), ""])
        config = dict(BASE_CONFIG, max_pages=5)

        result = KomoAdapter().fetch(fetcher, config, since=None)

        assert result.error is None
        assert [l.source_id for l in result.listings] == ["1", "2"]
        # Stopped after the empty 3rd page rather than fetching all 5.
        assert len(fetcher.requested) == 3

    def test_respects_max_pages_even_without_an_empty_page(self):
        fetcher = SequenceFetcher([card_html("1"), card_html("2"), card_html("3")])
        config = dict(BASE_CONFIG, max_pages=2)

        result = KomoAdapter().fetch(fetcher, config, since=None)

        assert len(result.listings) == 2
        assert len(fetcher.requested) == 2

    def test_page_two_failure_degrades_to_partial_results(self):
        fetcher = FailAfterFirstPageFetcher(first_page_text=card_html("1"))
        config = dict(BASE_CONFIG, max_pages=2)

        result = KomoAdapter().fetch(fetcher, config, since=None)

        assert result.error is None
        assert len(result.listings) == 1
        assert len(fetcher.requested) == 2

    def test_page_one_failure_is_an_error_result(self):
        fetcher = FakeFetcher(error=FetchError("page 1 blocked"))
        config = dict(BASE_CONFIG, max_pages=2)

        result = KomoAdapter().fetch(fetcher, config, since=None)

        assert result.listings == []
        assert result.error is not None
