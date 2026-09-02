import json
from pathlib import Path

from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy


def default_filters(**overrides) -> Filters:
    base = dict(
        min_price=4000,
        max_price=5500,
        min_rooms=2,
        min_size_sqm=50,
        max_drive_minutes=15,
        max_distance_km=5.0,
        include_price_missing=True,
        include_unsure_occupancy=True,
        exclude_sublets=True,
    )
    base.update(overrides)
    return Filters(**base)


def listing(**overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id="1",
        url="https://y/1",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        drive_minutes=10.0,
        distance_km=3.0,
        occupancy=Occupancy.WHOLE,
    )
    base.update(overrides)
    return Listing(**base)


class TestPrice:
    def test_accepts_in_range(self):
        assert default_filters().matches(listing(price=4800)) is True

    def test_rejects_below_range(self):
        assert default_filters().matches(listing(price=3500)) is False

    def test_rejects_above_range(self):
        assert default_filters().matches(listing(price=6000)) is False

    def test_accepts_boundaries_inclusively(self):
        assert default_filters().matches(listing(price=4000)) is True
        assert default_filters().matches(listing(price=5500)) is True

    def test_missing_price_follows_the_toggle(self):
        assert default_filters().matches(listing(price=None)) is True
        strict = default_filters(include_price_missing=False)
        assert strict.matches(listing(price=None)) is False


class TestRoomsAndSize:
    def test_rejects_too_few_rooms(self):
        assert default_filters().matches(listing(rooms=1.0)) is False

    def test_accepts_minimum_rooms(self):
        assert default_filters().matches(listing(rooms=2.0)) is True

    def test_rejects_too_small(self):
        assert default_filters().matches(listing(size_sqm=40.0)) is False

    def test_unknown_rooms_does_not_disqualify(self):
        # Failing closed on missing data would discard most free-text listings,
        # which is the opposite of what this system is for.
        assert default_filters().matches(listing(rooms=None)) is True

    def test_unknown_size_does_not_disqualify(self):
        assert default_filters().matches(listing(size_sqm=None)) is True


class TestDriveTime:
    def test_rejects_too_far(self):
        assert default_filters().matches(listing(drive_minutes=25.0)) is False

    def test_accepts_within_range(self):
        assert default_filters().matches(listing(drive_minutes=15.0)) is True

    def test_unknown_drive_time_does_not_disqualify(self):
        # Before the enrichment phase runs, nothing has a drive time yet.
        assert default_filters().matches(listing(drive_minutes=None)) is True


class TestDistance:
    def test_rejects_beyond_the_cap(self):
        assert default_filters().matches(listing(distance_km=6.0)) is False

    def test_accepts_within_the_cap(self):
        assert default_filters().matches(listing(distance_km=3.0)) is True

    def test_accepts_the_boundary_inclusively(self):
        assert default_filters().matches(listing(distance_km=5.0)) is True

    def test_unknown_distance_does_not_disqualify(self):
        assert default_filters().matches(listing(distance_km=None)) is True


class TestOccupancy:
    def test_rejects_roommate_ads(self):
        assert default_filters().matches(listing(occupancy=Occupancy.ROOMMATES)) is False

    def test_unsure_follows_the_toggle(self):
        unsure = listing(occupancy=Occupancy.UNSURE)
        assert default_filters().matches(unsure) is True
        strict = default_filters(include_unsure_occupancy=False)
        assert strict.matches(unsure) is False


class TestSublets:
    def test_rejects_sublets_by_default(self):
        assert default_filters().matches(listing(is_sublet=True)) is False

    def test_toggle_off_allows_sublets(self):
        lenient = default_filters(exclude_sublets=False)
        assert lenient.matches(listing(is_sublet=True)) is True

    def test_non_sublet_is_unaffected(self):
        assert default_filters().matches(listing(is_sublet=False)) is True


class TestConfigFile:
    def test_config_json_matches_defaults_and_is_sorted(self):
        # Keeps config/filters.json honest: every default lives there, and
        # the file's own key order is verified sorted (the repo's convention
        # for this file) rather than just re-derived from json.dumps.
        path = Path(__file__).resolve().parent.parent / "config" / "filters.json"
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        assert raw == Filters().to_dict()
        assert json.dumps(raw, sort_keys=True) == json.dumps(raw)


class TestLoading:
    def test_loads_from_json_file(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(
            json.dumps({"min_price": 3000, "max_price": 7000}), encoding="utf-8"
        )
        loaded = Filters.load(path)
        assert loaded.min_price == 3000
        assert loaded.max_price == 7000

    def test_unspecified_keys_take_defaults(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps({"min_price": 3000}), encoding="utf-8")
        assert Filters.load(path).min_rooms == 2

    def test_unknown_keys_are_ignored(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(
            json.dumps({"min_price": 3000, "future_option": True}), encoding="utf-8"
        )
        assert Filters.load(path).min_price == 3000
