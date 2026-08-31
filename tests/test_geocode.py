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

    def test_network_failure_returns_none_and_is_retried(self, tmp_path):
        # A transient outage must not be cached as "address does not exist":
        # the next lookup hits the API again.
        client = FakeClient(raises=RuntimeError("down"))
        geocoder = build(tmp_path, client)
        assert geocoder.geocode("הרצל 10") is None
        assert geocoder.geocode("הרצל 10") is None
        assert len(client.calls) == 2, "a transport failure must not be cached"


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
