import pytest

from apt_scout.enrich.seeker import is_seeker_text


@pytest.mark.parametrize("text", [
    "מחפשת דירה 2 חדרים במרכז תל אביב, כניסה מיידית",
    "מחפשים דירה לזוג, כניסה בנובמבר",
    "היי! מחפש/ת דירת 3 חדרים ברמת גן",
    "Looking for a 2 bedroom apartment in Tel Aviv, budget flexible",
    "Looking for an apartment near Dizengoff",
    "WANTED: studio in Florentin",
    "דרושה דירה להשכרה בגבעתיים",
    "מעוניינת לשכור דירה קטנה",
])
def test_seeker_posts(text):
    assert is_seeker_text(text) is True


@pytest.mark.parametrize("text", [
    "להשכרה דירת 3 חדרים בפלורנטין, 4,900 ₪",
    "דירה מקסימה, מחפשים שוכרים רציניים, 5,200 ש\"ח",   # offer that contains a seeker-ish word AND a price
    "מחפש דירה? יש לי אחת בשבילך! 4800 ₪",
    None,
    "",
])
def test_offer_posts(text):
    assert is_seeker_text(text) is False


def test_only_the_opening_counts():
    tail = "x" * 250 + " מחפשת דירה"
    assert is_seeker_text(tail) is False
