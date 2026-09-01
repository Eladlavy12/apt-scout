from apt_scout.enrich.pipeline_enrichers import build_enrichers
from apt_scout.models import Listing, Occupancy
from apt_scout.state import StateStore


class StubGeocoder:
    def __init__(self, result=(32.07, 34.79)):
        self.result = result
        self.calls = []

    def geocode(self, address):
        self.calls.append(address)
        return self.result


class StubDrive:
    def __init__(self, minutes=12.0):
        self.minutes = minutes
        self.calls = []

    def minutes_from_centre(self, lat, lon):
        self.calls.append((lat, lon))
        return self.minutes


def enrich(listing, tmp_path, geocoder=None, drive=None, salt="s"):
    enrichers = build_enrichers(
        StateStore(tmp_path),
        salt=salt,
        geocoder=geocoder or StubGeocoder(),
        drive=drive or StubDrive(),
    )
    for step in enrichers:
        listing = step(listing)
    return listing


def base(**overrides) -> Listing:
    values = dict(source="yad2", source_id="1", url="https://y/1")
    values.update(overrides)
    return Listing(**values)


class TestGeocoding:
    def test_fills_coordinates_from_the_address(self, tmp_path):
        result = enrich(base(address_text="הרצל 10 תל אביב"), tmp_path)
        assert result.lat == 32.07
        assert result.lon == 34.79

    def test_does_not_re_geocode_when_coordinates_exist(self, tmp_path):
        geocoder = StubGeocoder()
        enrich(
            base(address_text="הרצל 10", lat=32.0, lon=34.0),
            tmp_path,
            geocoder=geocoder,
        )
        assert geocoder.calls == []


class TestDriveTime:
    def test_fills_drive_minutes(self, tmp_path):
        result = enrich(base(lat=32.07, lon=34.79), tmp_path)
        assert result.drive_minutes == 12.0

    def test_skipped_when_there_are_no_coordinates(self, tmp_path):
        drive = StubDrive()
        result = enrich(base(), tmp_path, geocoder=StubGeocoder(result=None), drive=drive)
        assert result.drive_minutes is None
        assert drive.calls == []


class TestDistance:
    def test_fills_straight_line_distance_from_coordinates(self, tmp_path):
        result = enrich(base(lat=32.07, lon=34.79), tmp_path)
        assert result.distance_km is not None
        assert result.distance_km > 0

    def test_skipped_when_there_are_no_coordinates(self, tmp_path):
        result = enrich(base(), tmp_path, geocoder=StubGeocoder(result=None))
        assert result.distance_km is None

    def test_uses_the_coordinates_found_by_geocoding(self, tmp_path):
        result = enrich(
            base(address_text="הרצל 10"),
            tmp_path,
            geocoder=StubGeocoder(result=(32.056581, 34.804087)),
        )
        # Geocoded coordinates equal the centre point exactly.
        assert result.distance_km == 0.0


class TestTextDerivedFields:
    def test_fills_a_missing_price_from_raw_text(self, tmp_path):
        result = enrich(base(raw_text='להשכרה 4800 ש"ח'), tmp_path)
        assert result.price == 4800

    def test_does_not_overwrite_a_price_the_source_stated(self, tmp_path):
        result = enrich(base(price=5000, raw_text='4800 ש"ח'), tmp_path)
        assert result.price == 5000

    def test_fills_missing_rooms_and_size(self, tmp_path):
        result = enrich(base(raw_text='3 חדרים 70 מ"ר'), tmp_path)
        assert result.rooms == 3.0
        assert result.size_sqm == 70.0


class TestOccupancy:
    def test_reclassifies_an_unsure_listing_from_its_text(self, tmp_path):
        result = enrich(
            base(raw_text="מחפשים שותף לדירה", occupancy=Occupancy.UNSURE), tmp_path
        )
        assert result.occupancy is Occupancy.ROOMMATES

    def test_trusts_a_source_that_already_said_whole(self, tmp_path):
        # yad2 categorises for us; text heuristics must not override that.
        result = enrich(
            base(raw_text="מחפשים שותף", occupancy=Occupancy.WHOLE), tmp_path
        )
        assert result.occupancy is Occupancy.WHOLE


class TestPhoneHandling:
    def test_stores_a_hash_never_the_number(self, tmp_path):
        result = enrich(base(raw_text="לפרטים 050-1234567"), tmp_path)
        assert result.phone_hash is not None
        assert "050" not in result.phone_hash
        assert "1234567" not in result.phone_hash

    def test_no_phone_leaves_the_hash_empty(self, tmp_path):
        assert enrich(base(raw_text="דירה יפה"), tmp_path).phone_hash is None
