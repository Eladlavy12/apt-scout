from apt_scout.enrich.distance import distance_from_centre_km, haversine_km
from apt_scout.enrich.drivetime import CENTRE

# Dizengoff Center, Tel Aviv.
DIZENGOFF = (32.0753, 34.7752)


class TestHaversine:
    def test_known_pair_is_within_tolerance(self):
        km = haversine_km(CENTRE[0], CENTRE[1], DIZENGOFF[0], DIZENGOFF[1])
        assert abs(km - 3.4) < 0.3

    def test_zero_distance_for_the_same_point(self):
        assert haversine_km(CENTRE[0], CENTRE[1], CENTRE[0], CENTRE[1]) == 0.0


class TestDistanceFromCentre:
    def test_matches_haversine_from_the_default_centre(self):
        km = distance_from_centre_km(DIZENGOFF[0], DIZENGOFF[1])
        assert abs(km - 3.4) < 0.3

    def test_rounds_to_two_decimals(self):
        km = distance_from_centre_km(DIZENGOFF[0], DIZENGOFF[1])
        assert km == round(km, 2)

    def test_none_lat_passes_through_as_none(self):
        assert distance_from_centre_km(None, 34.7752) is None

    def test_none_lon_passes_through_as_none(self):
        assert distance_from_centre_km(32.0753, None) is None

    def test_accepts_a_custom_centre(self):
        km = distance_from_centre_km(1.0, 1.0, centre=(1.0, 1.0))
        assert km == 0.0
