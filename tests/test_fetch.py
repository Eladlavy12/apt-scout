import pytest

from apt_scout.fetch import CurlTransport, DEFAULT_HEADERS, Fetcher, FetchError, FetchResult


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

    def test_no_accept_encoding_is_advertised(self):
        # httpx has no brotli package installed; advertising "br" support
        # makes onmap respond with brotli and httpx yields undecodable text.
        # Leaving this header out lets httpx negotiate (and decode) gzip.
        assert "Accept-Encoding" not in DEFAULT_HEADERS


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class RecordingRunner:
    """Stands in for subprocess.run, recording the argv it was called with."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return self.result


class TestCurlTransport:
    def test_parses_body_and_status_on_success(self):
        runner = RecordingRunner(FakeCompletedProcess(stdout="hello world\n200"))
        transport = CurlTransport(runner=runner)

        result = transport.get("https://example.com")

        assert result.status == 200
        assert result.text == "hello world"
        assert result.tier == "curl"

    def test_non_200_status_passes_through_as_a_result(self):
        # Escalation on non-200 is the Fetcher's job, not the transport's.
        runner = RecordingRunner(FakeCompletedProcess(stdout="forbidden\n403"))
        transport = CurlTransport(runner=runner)

        result = transport.get("https://example.com")

        assert result.status == 403
        assert result.text == "forbidden"

    def test_nonzero_exit_raises(self):
        runner = RecordingRunner(
            FakeCompletedProcess(stdout="", stderr="curl: (6) Could not resolve host", returncode=6)
        )
        transport = CurlTransport(runner=runner)

        with pytest.raises(RuntimeError, match="curl exited 6"):
            transport.get("https://example.com")

    def test_unparsable_status_tail_raises(self):
        runner = RecordingRunner(FakeCompletedProcess(stdout="not a status line"))
        transport = CurlTransport(runner=runner)

        with pytest.raises(RuntimeError):
            transport.get("https://example.com")

    def test_headers_are_passed_as_dash_h_arguments(self):
        runner = RecordingRunner(FakeCompletedProcess(stdout="ok\n200"))
        transport = CurlTransport(runner=runner)

        transport.get("https://example.com", headers={"X-Custom": "value"})

        argv = runner.calls[0]
        assert "-H" in argv
        assert "User-Agent: " + DEFAULT_HEADERS["User-Agent"] in argv
        assert "X-Custom: value" in argv
        assert argv[-1] == "https://example.com"

    def test_default_headers_used_when_no_override_given(self):
        runner = RecordingRunner(FakeCompletedProcess(stdout="ok\n200"))
        transport = CurlTransport(runner=runner)

        transport.get("https://example.com")

        argv = runner.calls[0]
        assert "Accept-Language: " + DEFAULT_HEADERS["Accept-Language"] in argv


@pytest.mark.skip(
    reason="hits the real network; run manually to sanity-check the curl "
    "subprocess plumbing end to end (unit tests must not depend on network)"
)
class TestCurlTransportRealSmoke:
    def test_real_curl_fetches_a_known_url(self):
        transport = CurlTransport()
        result = transport.get("https://httpbin.org/get")
        assert result.status == 200
        assert result.tier == "curl"
