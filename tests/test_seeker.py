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
    # I2: "מחפש/ת" narrowed to "מחפש/ת דיר" so it binds to the object
    # ("דיר..."); "מחפש/ת דירה" still matches since "דירה" starts with
    # "דיר". This is an offer worded as a hook ("looking for an
    # apartment? I have one"), not a real seeker post, but the fix list
    # accepts this known false positive rather than over-narrowing the
    # term - it has no price, so it reads the same as a genuine seeker.
    "מחפש/ת דירה? יש לי דירת 3 חדרים להשכרה בפלורנטין",
])
def test_seeker_posts(text):
    assert is_seeker_text(text) is True


@pytest.mark.parametrize("text", [
    "להשכרה דירת 3 חדרים בפלורנטין, 4,900 ₪",
    "דירה מקסימה, מחפשים שוכרים רציניים, 5,200 ש\"ח",   # offer that contains a seeker-ish word AND a price
    "מחפש דירה? יש לי אחת בשבילך! 4800 ₪",
    None,
    "",
    # I2: "מחפש/ת שותף" (looking for a ROOMMATE) is an offer of a room in
    # an existing apartment, not someone seeking an apartment - the term
    # must not fire on it just because it starts with "מחפש/ת".
    "מחפש/ת שותף לדירת 3 חדרים, כניסה מיידית",
])
def test_offer_posts(text):
    assert is_seeker_text(text) is False


def test_only_the_opening_counts():
    tail = "x" * 250 + " מחפשת דירה"
    assert is_seeker_text(tail) is False
