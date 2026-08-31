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
