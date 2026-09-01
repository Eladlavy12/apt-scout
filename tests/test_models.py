from apt_scout.models import Listing, Occupancy


def make_listing(**overrides) -> Listing:
    defaults = dict(source="yad2", source_id="abc123", url="https://y.co/1")
    defaults.update(overrides)
    return Listing(**defaults)


def test_listing_defaults_unknown_fields_to_none():
    listing = make_listing()
    assert listing.price is None
    assert listing.rooms is None
    assert listing.size_sqm is None
    assert listing.drive_minutes is None
    assert listing.distance_km is None
    assert listing.photos == []
    assert listing.occupancy is Occupancy.UNSURE


def test_stable_id_combines_source_and_source_id():
    assert make_listing().stable_id() == "yad2:abc123"


def test_stable_id_differs_across_sources_for_same_source_id():
    a = make_listing(source="yad2")
    b = make_listing(source="madlan")
    assert a.stable_id() != b.stable_id()


def test_price_missing_is_true_when_price_is_none():
    assert make_listing().price_missing is True
    assert make_listing(price=4500).price_missing is False
