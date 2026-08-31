from apt_scout.enrich.occupancy import classify_occupancy
from apt_scout.models import Occupancy


class TestRoommateDetection:
    def test_looking_for_roommate(self):
        text = "מחפשים שותף לדירה בתל אביב"
        assert classify_occupancy(text) is Occupancy.ROOMMATES

    def test_female_roommate(self):
        assert classify_occupancy("מחפשת שותפה") is Occupancy.ROOMMATES

    def test_room_in_apartment(self):
        assert classify_occupancy("חדר בדירה משותפת") is Occupancy.ROOMMATES

    def test_english_roommate(self):
        assert classify_occupancy("Roommate wanted") is Occupancy.ROOMMATES


class TestNegationHandling:
    def test_no_roommates_is_a_whole_apartment(self):
        # The critical case: this contains the word שותפים but means the
        # opposite. Naive keyword matching gets this exactly backwards.
        text = "דירה 3 חדרים ללא שותפים"
        assert classify_occupancy(text) is Occupancy.WHOLE

    def test_without_roommates_variant(self):
        assert classify_occupancy("דירת 2 חדרים בלי שותפים") is Occupancy.WHOLE


class TestWholeApartment:
    def test_apartment_for_rent(self):
        assert classify_occupancy("דירה להשכרה במרכז") is Occupancy.WHOLE

    def test_apartment_construct_form(self):
        assert classify_occupancy("דירת גן להשכרה") is Occupancy.WHOLE


class TestUnsure:
    def test_ambiguous_text_is_unsure(self):
        assert classify_occupancy("להשכרה 2 חדרים קומה 3") is Occupancy.UNSURE

    def test_empty_is_unsure(self):
        assert classify_occupancy(None) is Occupancy.UNSURE
        assert classify_occupancy("") is Occupancy.UNSURE
