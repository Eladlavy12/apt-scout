from apt_scout.normalise.price import parse_price
from apt_scout.normalise.rooms import parse_rooms
from apt_scout.normalise.size import parse_size
from apt_scout.normalise.text import extract_phone, hash_phone, normalise_text


class TestNormaliseText:
    def test_collapses_whitespace(self):
        assert normalise_text("a   b\n\nc") == "a b c"

    def test_handles_none(self):
        assert normalise_text(None) == ""

    def test_strips_niqqud(self):
        assert normalise_text("שָׁלוֹם") == "שלום"


class TestParsePrice:
    def test_shekel_sign_before_number(self):
        assert parse_price("₪4500 לחודש") == 4500

    def test_shekel_sign_after_number_with_comma(self):
        assert parse_price("4,500 ₪") == 4500

    def test_hebrew_currency_word(self):
        assert parse_price('המחיר 5000 ש"ח') == 5000

    def test_shach_without_quotes(self):
        assert parse_price("5200 שח כולל ועד") == 5200

    def test_k_notation(self):
        assert parse_price("4.5k a month") == 4500

    def test_ignores_phone_numbers(self):
        assert parse_price("לפרטים 050-1234567") is None

    def test_ignores_implausible_values(self):
        assert parse_price("קומה 3 ₪") is None

    def test_returns_none_when_no_price(self):
        assert parse_price("דירה יפה במרכז") is None

    def test_returns_none_for_empty(self):
        assert parse_price(None) is None

    def test_takes_first_plausible_price_not_the_extras(self):
        assert parse_price('4500 ש"ח + ועד בית 250 ש"ח') == 4500


class TestParseRooms:
    def test_whole_rooms(self):
        assert parse_rooms("3 חדרים") == 3.0

    def test_half_rooms_decimal(self):
        assert parse_rooms("3.5 חדרים") == 3.5

    def test_abbreviated_form(self):
        assert parse_rooms("2 חד'") == 2.0

    def test_word_form_half(self):
        assert parse_rooms("3 וחצי חדרים") == 3.5

    def test_word_form_half_after_the_room_word(self):
        # The digit before the room word must win over the bare "one and a
        # half" reading, which used to swallow this as 1.5.
        assert parse_rooms("3 חדרים וחצי") == 3.5

    def test_single_room_and_a_half(self):
        assert parse_rooms("חדר וחצי להשכרה") == 1.5

    def test_rejects_implausible_counts(self):
        assert parse_rooms("40 חדרים") is None

    def test_returns_none_when_absent(self):
        assert parse_rooms("דירה להשכרה") is None


class TestParseSize:
    def test_standard_hebrew_unit(self):
        assert parse_size('75 מ"ר') == 75.0

    def test_geresh_variant(self):
        assert parse_size("75 מ״ר") == 75.0

    def test_without_quotes(self):
        assert parse_size("80 מר") == 80.0

    def test_english_unit(self):
        assert parse_size("65 sqm") == 65.0

    def test_returns_none_when_absent(self):
        assert parse_size("דירה גדולה") is None


class TestPhone:
    def test_extracts_mobile_with_dash(self):
        assert extract_phone("לפרטים 050-1234567") == "+972501234567"

    def test_extracts_mobile_without_dash(self):
        assert extract_phone("0521234567") == "+972521234567"

    def test_extracts_international_form(self):
        assert extract_phone("+972-52-1234567") == "+972521234567"

    def test_returns_none_when_absent(self):
        assert extract_phone("דירה להשכרה") is None

    def test_hash_is_stable_and_salted(self):
        a = hash_phone("+972501234567", salt="s1")
        b = hash_phone("+972501234567", salt="s1")
        c = hash_phone("+972501234567", salt="s2")
        assert a == b
        assert a != c
        assert "972" not in a
