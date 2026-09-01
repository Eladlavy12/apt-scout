from apt_scout.cluster.fingerprints import fingerprints
from apt_scout.models import Listing
from apt_scout.normalise.text import hash_phone

SALT = "test-salt"


def make_listing(**overrides) -> Listing:
    defaults = dict(source="yad2", source_id="abc123", url="https://y.co/1")
    defaults.update(overrides)
    return Listing(**defaults)


class TestPhoneFingerprint:
    def test_extracted_from_raw_text(self):
        listing = make_listing(raw_text="דירה יפה, לפרטים 050-1234567")
        fp = fingerprints(listing, SALT)
        expected = hash_phone("+972501234567", SALT)
        assert f"phone:{expected}" in fp["strong"]

    def test_extracted_from_title_when_raw_text_has_none(self):
        listing = make_listing(title="התקשרו 052-1234567", raw_text="דירה יפה")
        fp = fingerprints(listing, SALT)
        expected = hash_phone("+972521234567", SALT)
        assert f"phone:{expected}" in fp["strong"]

    def test_absent_when_no_phone(self):
        listing = make_listing(raw_text="דירה יפה במרכז העיר")
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("phone:") for k in fp["strong"])

    def test_raw_phone_number_never_appears_in_fingerprint(self):
        listing = make_listing(raw_text="לפרטים 050-1234567")
        fp = fingerprints(listing, SALT)
        blob = " ".join(fp["strong"] + fp["weak"])
        assert "501234567" not in blob
        assert "0501234567" not in blob


class TestExturlFingerprint:
    def test_found_inside_facebook_prose(self):
        listing = make_listing(
            source="fb_marketplace",
            raw_text="דירה מדהימה! לפרטים נוספים: https://www.yad2.co.il/realestate/item/abc123 מוזמנים",
        )
        fp = fingerprints(listing, SALT)
        assert "exturl:https://www.yad2.co.il/realestate/item/abc123" in fp["strong"]

    def test_normalises_scheme_and_host_case_and_strips_query(self):
        listing = make_listing(
            raw_text="ראה כאן HTTPS://WWW.Yad2.co.il/realestate/item/abc123?utm_source=fb&ref=1"
        )
        fp = fingerprints(listing, SALT)
        assert "exturl:https://www.yad2.co.il/realestate/item/abc123" in fp["strong"]

    def test_absent_when_no_url(self):
        listing = make_listing(raw_text="דירה יפה במרכז העיר, בלי לינק")
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("exturl:") for k in fp["strong"])

    def test_recognises_onmap_and_madlan_hosts(self):
        listing = make_listing(raw_text="https://www.onmap.co.il/search/homes/rent?property=xyz")
        fp = fingerprints(listing, SALT)
        assert any(k.startswith("exturl:https://www.onmap.co.il/") for k in fp["strong"])


class TestStructFingerprint:
    def test_present_when_price_and_rooms_given(self):
        listing = make_listing(price=4800, rooms=3.0, size_sqm=65.0)
        fp = fingerprints(listing, SALT)
        assert "struct:4800|3.0|6" in fp["weak"]

    def test_absent_when_price_missing(self):
        listing = make_listing(price=None, rooms=3.0, size_sqm=65.0)
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("struct:") for k in fp["weak"])

    def test_absent_when_rooms_missing(self):
        listing = make_listing(price=4800, rooms=None, size_sqm=65.0)
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("struct:") for k in fp["weak"])

    def test_absent_when_size_missing_and_no_address(self):
        # An address-less price+rooms-only match is too weak: two unrelated
        # same-city listings that merely agree on 4800/3 must not share it.
        listing = make_listing(price=4800, rooms=3.0, size_sqm=None)
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("struct:") for k in fp["weak"])

    def test_loose_empty_bucket_key_kept_when_an_address_is_present(self):
        listing = make_listing(
            price=4800, rooms=3.0, size_sqm=None, address_text="רחוב הרצל 5"
        )
        fp = fingerprints(listing, SALT)
        assert "struct:4800|3.0|" in fp["weak"]


class TestGeoFingerprint:
    def test_present_when_coords_and_street_address_given(self):
        listing = make_listing(
            lat=32.0801, lon=34.7806, address_text="רחוב הרצל 5", city="תל אביב"
        )
        fp = fingerprints(listing, SALT)
        assert "geo:32.080,34.781" in fp["weak"]

    def test_rounding_equates_nearby_coords(self):
        a = make_listing(lat=32.0801, lon=34.7806, address_text="רחוב הרצל 5")
        b = make_listing(lat=32.0803, lon=34.7806, address_text="רחוב הרצל 5")
        fp_a = fingerprints(a, SALT)
        fp_b = fingerprints(b, SALT)
        geo_a = [k for k in fp_a["weak"] if k.startswith("geo:")]
        geo_b = [k for k in fp_b["weak"] if k.startswith("geo:")]
        assert geo_a == geo_b

    def test_absent_when_coords_missing(self):
        listing = make_listing(lat=None, lon=None, address_text="רחוב הרצל 5")
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("geo:") for k in fp["weak"])

    def test_absent_when_no_address(self):
        # Address-less listings geocode to the city centroid: an identical
        # geo: key on every such listing proves nothing.
        listing = make_listing(lat=32.0801, lon=34.7806, city="תל אביב")
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("geo:") for k in fp["weak"])

    def test_absent_when_the_address_is_just_the_city_name(self):
        listing = make_listing(
            lat=32.0801, lon=34.7806, address_text="תל אביב", city="תל אביב"
        )
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("geo:") for k in fp["weak"])

    def test_city_comparison_ignores_whitespace_differences(self):
        listing = make_listing(
            lat=32.0801, lon=34.7806, address_text="  תל אביב ", city="תל אביב"
        )
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("geo:") for k in fp["weak"])


class TestTextFingerprint:
    LONG_TEXT = (
        "דירת גן מרווחת ומוארת ברחוב הרצל עם מרפסת שמש גדולה ומטבח משודרג "
        "וחניה פרטית צמודה קרובה מאוד לתחבורה ציבורית ולבתי ספר"
    )

    def test_present_for_long_text(self):
        listing = make_listing(raw_text=self.LONG_TEXT)
        fp = fingerprints(listing, SALT)
        assert any(k.startswith("text:") for k in fp["weak"])

    def test_identical_for_reordered_same_words(self):
        words = self.LONG_TEXT.split()
        reordered = " ".join(reversed(words))
        a = make_listing(raw_text=self.LONG_TEXT)
        b = make_listing(raw_text=reordered)
        fp_a = fingerprints(a, SALT)
        fp_b = fingerprints(b, SALT)
        text_a = [k for k in fp_a["weak"] if k.startswith("text:")]
        text_b = [k for k in fp_b["weak"] if k.startswith("text:")]
        assert text_a == text_b
        assert text_a != []

    def test_absent_for_short_text(self):
        listing = make_listing(raw_text="דירה יפה")
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("text:") for k in fp["weak"])

    def test_absent_when_raw_text_is_none(self):
        listing = make_listing(raw_text=None)
        fp = fingerprints(listing, SALT)
        assert not any(k.startswith("text:") for k in fp["weak"])
