import pytest

from apt_scout.enrich.city import CANONICAL_CITIES, normalise_city

TEL_AVIV, GIVATAYIM, RAMAT_GAN = CANONICAL_CITIES


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("תל אביב יפו", TEL_AVIV),
        ("תל אביב - יפו", TEL_AVIV),
        ("תל אביב-יפו", TEL_AVIV),
        ("תל-אביב", TEL_AVIV),
        ("תל אביב", TEL_AVIV),
        ("  תל אביב, TA ", TEL_AVIV),
        ('ת"א', TEL_AVIV),
        ("יפו", TEL_AVIV),
        ("Tel Aviv-Yafo", TEL_AVIV),
        ("Tel Aviv", TEL_AVIV),
        ("tel aviv yafo", TEL_AVIV),
        ("גבעתיים", GIVATAYIM),
        ("Givatayim", GIVATAYIM),
        ("Giv'atayim", GIVATAYIM),
        ("רמת גן", RAMAT_GAN),
        ("רמת-גן", RAMAT_GAN),
        ("Ramat Gan", RAMAT_GAN),
        ("ramat-gan", RAMAT_GAN),
    ],
)
def test_maps_variants_to_the_canonical_name(raw, expected):
    assert normalise_city(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "חולון", "בת ים", "Jerusalem", "ירושלים, JM"])
def test_unknown_cities_return_none(raw):
    assert normalise_city(raw) is None


def test_canonical_names_are_fixed_points():
    for name in CANONICAL_CITIES:
        assert normalise_city(name) == name
