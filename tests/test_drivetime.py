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

    def test_network_failure_returns_none_and_is_retried(self, tmp_path):
        # A transient outage must not be cached as "unreachable": the next
        # lookup hits the API again.
        client = FakeClient(raises=RuntimeError("down"))
        calc = build(tmp_path, client)
        assert calc.minutes_from_centre(32.07, 34.79) is None
        assert calc.minutes_from_centre(32.07, 34.79) is None
        assert len(client.calls) == 2, "a transport failure must not be cached"

    def test_a_genuine_no_route_is_cached(self, tmp_path):
        client = FakeClient({"code": "NoRoute", "routes": []})
        calc = build(tmp_path, client)
        assert calc.minutes_from_centre(32.07, 34.79) is None
        assert calc.minutes_from_centre(32.07, 34.79) is None
        assert len(client.calls) == 1

    def test_malformed_payload_shapes_return_none(self, tmp_path):
        for payload in (None, [], {"routes": [None]}, {"routes": "bad"}):
            calc = build(tmp_path, FakeClient(payload))
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
