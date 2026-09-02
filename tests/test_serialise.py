from datetime import datetime, timezone

from apt_scout.models import Listing, Occupancy
from apt_scout.serialise import deserialise_listing, serialise_listing


def full_listing() -> Listing:
    return Listing(
        source="yad2",
        source_id="123",
        url="https://www.yad2.co.il/realestate/item/123",
        title="דירה יפה",
        raw_text="raw",
        price=5000,
        rooms=3.0,
        size_sqm=70.0,
        floor=2,
        address_text="הרצל 10",
        city="תל אביב יפו",
        lat=32.05,
        lon=34.77,
        drive_minutes=12.5,
        distance_km=3.2,
        photos=["https://img/1.jpg"],
        phone_hash="abc",
        occupancy=Occupancy.WHOLE,
        is_sublet=True,
        posted_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
        first_seen_at=datetime(2026, 9, 2, 8, 30, tzinfo=timezone.utc),
        sources=["yad2", "onmap"],
    )


class TestRoundTrip:
    def test_round_trips_every_field(self):
        listing = full_listing()
        restored = deserialise_listing(serialise_listing(listing))
        assert restored == listing

    def test_round_trips_none_datetimes(self):
        listing = full_listing()
        listing.posted_at = None
        listing.first_seen_at = None
        restored = deserialise_listing(serialise_listing(listing))
        assert restored.posted_at is None
        assert restored.first_seen_at is None

    def test_serialised_form_is_json_safe(self):
        import json

        data = serialise_listing(full_listing())
        # Must not raise - every value is a JSON-native type.
        json.dumps(data)

    def test_occupancy_round_trips_as_enum(self):
        listing = full_listing()
        restored = deserialise_listing(serialise_listing(listing))
        assert restored.occupancy is Occupancy.WHOLE

    def test_sources_list_round_trips(self):
        listing = full_listing()
        restored = deserialise_listing(serialise_listing(listing))
        assert restored.sources == ["yad2", "onmap"]

    def test_is_sublet_round_trips(self):
        listing = full_listing()
        restored = deserialise_listing(serialise_listing(listing))
        assert restored.is_sublet is True

    def test_distance_km_round_trips(self):
        listing = full_listing()
        restored = deserialise_listing(serialise_listing(listing))
        assert restored.distance_km == 3.2
