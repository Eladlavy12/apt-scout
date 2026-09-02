from apt_scout.enrich.sublet import is_sublet_text


class TestHebrewTerms:
    def test_sublet_hebrew(self):
        assert is_sublet_text("דירה לסאבלט לחודשיים") is True

    def test_sublet_hebrew_short_spelling(self):
        assert is_sublet_text("מסבלטת את הדירה שלי") is True

    def test_sublet_hebrew_prefix_form(self):
        assert is_sublet_text("סבלט לחודש ימים") is True

    def test_sublet_hebrew_plural_prefix(self):
        assert is_sublet_text("אנחנו מסבלטים את החדר") is True

    def test_short_term_rental_hebrew(self):
        assert is_sublet_text("להשכרה לטווח קצר בלבד") is True

    def test_short_period_hebrew(self):
        assert is_sublet_text("הדירה מושכרת לתקופה קצרה") is True

    def test_bare_short_range_hebrew(self):
        assert is_sublet_text("דירה טווח קצר בלבד") is True

    def test_sublease_hebrew(self):
        assert is_sublet_text("השכרת משנה לחודש") is True


class TestEnglishTerms:
    def test_sublet_english(self):
        assert is_sublet_text("Subletting my apartment for 2 months") is True

    def test_sub_let_hyphenated(self):
        assert is_sublet_text("Looking for a sub-let tenant") is True

    def test_sublease_english(self):
        assert is_sublet_text("Sublease available starting June") is True

    def test_is_case_insensitive(self):
        assert is_sublet_text("SUBLET AVAILABLE") is True


class TestOrdinaryListings:
    def test_ordinary_listing_is_not_a_sublet(self):
        text = "דירה 3 חדרים להשכרה בתל אביב, קומה 2"
        assert is_sublet_text(text) is False

    def test_ordinary_english_listing_is_not_a_sublet(self):
        assert is_sublet_text("Nice 3 room apartment for rent, floor 2") is False


class TestEmptyInput:
    def test_none_is_not_a_sublet(self):
        assert is_sublet_text(None) is False

    def test_empty_string_is_not_a_sublet(self):
        assert is_sublet_text("") is False


class TestNoNegationHandling:
    # Unlike occupancy classification, sublet detection does not strip
    # negation phrases. A false positive here only routes a listing behind
    # the /sublets toggle rather than discarding it outright, so the extra
    # complexity of negation handling is not worth it for this signal.
    def test_negated_sublet_mention_is_still_flagged(self):
        assert is_sublet_text("זו לא דירה לסאבלט") is True
