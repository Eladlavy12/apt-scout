from apt_scout.cluster.engine import Cluster, ClusterEngine
from apt_scout.models import Listing

SALT = "test-salt"


def make_listing(**overrides) -> Listing:
    defaults = dict(source="yad2", source_id="default-id", url="https://y.co/1")
    defaults.update(overrides)
    return Listing(**defaults)


def cluster_of(listings: list[Listing]) -> list[Cluster]:
    return ClusterEngine().cluster(listings, SALT)


class TestScenario1SharedPhone:
    def test_same_phone_across_yad2_and_facebook_merges(self):
        a = make_listing(
            source="yad2",
            source_id="y1",
            raw_text="דירה להשכרה, לפרטים 050-1234567",
        )
        b = make_listing(
            source="fb_marketplace",
            source_id="f1",
            raw_text="אותה דירה! התקשרו 050-1234567",
        )
        clusters = cluster_of([a, b])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 2
        assert set(clusters[0].sources) == {"yad2", "fb_marketplace"}


class TestScenario2SharedExturl:
    def test_facebook_post_containing_yad2_url_merges(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y2",
            url="https://www.yad2.co.il/realestate/item/abc123",
            raw_text="דירה מדהימה, לצפייה: https://www.yad2.co.il/realestate/item/abc123",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f2",
            raw_text="תראו את הדירה הזו! https://www.yad2.co.il/realestate/item/abc123 שווה בדיקה",
        )
        clusters = cluster_of([yad2, fb])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 2


class TestScenario3TwoSharedWeak:
    def test_same_struct_and_geo_merges(self):
        a = make_listing(
            source="yad2",
            source_id="y3",
            price=4800,
            rooms=3.0,
            size_sqm=65.0,
            lat=32.0801,
            lon=34.7806,
        )
        b = make_listing(
            source="komo",
            source_id="k3",
            price=4800,
            rooms=3.0,
            size_sqm=65.0,
            lat=32.0803,
            lon=34.7806,
        )
        clusters = cluster_of([a, b])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 2


class TestScenario4OneSharedWeakOnly:
    def test_same_struct_but_far_apart_does_not_merge(self):
        a = make_listing(
            source="yad2",
            source_id="y4",
            price=4800,
            rooms=3.0,
            size_sqm=65.0,
            lat=32.0801,
            lon=34.7806,
        )
        b = make_listing(
            source="komo",
            source_id="k4",
            price=4800,
            rooms=3.0,
            size_sqm=65.0,
            lat=32.1100,
            lon=34.7806,
        )
        clusters = cluster_of([a, b])
        assert len(clusters) == 2


class TestScenario5NoSharedFingerprint:
    def test_same_street_different_price_and_rooms_does_not_merge(self):
        a = make_listing(
            source="yad2",
            source_id="y5",
            price=4800,
            rooms=3.0,
            address_text="רחוב הרצל 5",
        )
        b = make_listing(
            source="komo",
            source_id="k5",
            price=5200,
            rooms=2.0,
            address_text="רחוב הרצל 5",
        )
        clusters = cluster_of([a, b])
        assert len(clusters) == 2


class TestScenario6PoolingMissingField:
    def test_canonical_price_pooled_from_member_that_has_it(self):
        fb = make_listing(
            source="fb_marketplace",
            source_id="f6",
            price=None,
            raw_text="לפרטים 050-1234567",
        )
        yad2 = make_listing(
            source="yad2",
            source_id="y6",
            price=4800,
            raw_text="דירה יפה 050-1234567",
        )
        clusters = cluster_of([fb, yad2])
        assert len(clusters) == 1
        assert clusters[0].canonical.price == 4800


class TestScenario7PoolingPriority:
    def test_canonical_url_prefers_yad2_member(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y7",
            url="https://www.yad2.co.il/realestate/item/abc123",
            raw_text="לפרטים 050-1234567",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f7",
            url="https://facebook.com/marketplace/item/999",
            raw_text="התקשרו 050-1234567",
        )
        # order shouldn't matter for pooling priority
        clusters_a = cluster_of([fb, yad2])
        clusters_b = cluster_of([yad2, fb])
        assert clusters_a[0].canonical.url == "https://www.yad2.co.il/realestate/item/abc123"
        assert clusters_b[0].canonical.url == "https://www.yad2.co.il/realestate/item/abc123"


class TestScenario8Singleton:
    def test_lone_listing_forms_its_own_cluster(self):
        listing = make_listing(
            source="yad2",
            source_id="solo",
            raw_text="דירה יפה בלי שום קשר לדירות אחרות",
        )
        clusters = cluster_of([listing])
        assert len(clusters) == 1
        assert clusters[0].members == [listing]
        assert clusters[0].canonical == listing
        assert clusters[0].sources == ["yad2"]


class TestScenario9TransitiveMerge:
    def test_a_b_via_phone_b_c_via_exturl_forms_one_cluster(self):
        a = make_listing(
            source="yad2",
            source_id="a9",
            raw_text="דירה להשכרה 050-9998887",
        )
        b = make_listing(
            source="fb_marketplace",
            source_id="b9",
            raw_text=(
                "אותה דירה 050-9998887 גם מפורסמת כאן: "
                "https://www.yad2.co.il/realestate/item/xyz999"
            ),
        )
        c = make_listing(
            source="komo",
            source_id="c9",
            raw_text="לצפייה בדירה: https://www.yad2.co.il/realestate/item/xyz999",
        )
        clusters = cluster_of([a, b, c])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 3
        assert set(clusters[0].sources) == {"yad2", "fb_marketplace", "komo"}


class TestScenario10ClusterIdStability:
    def test_same_members_different_input_order_same_cluster_id(self):
        a = make_listing(
            source="yad2",
            source_id="y10",
            raw_text="דירה להשכרה 050-1112223",
        )
        b = make_listing(
            source="fb_marketplace",
            source_id="f10",
            raw_text="אותה דירה 050-1112223",
        )
        clusters_forward = cluster_of([a, b])
        clusters_backward = cluster_of([b, a])
        assert clusters_forward[0].cluster_id == clusters_backward[0].cluster_id


class TestScenario11SaltedPhoneHash:
    def test_differently_formatted_same_phone_still_merges_via_hash(self):
        a = make_listing(
            source="yad2",
            source_id="y11",
            raw_text="נייד: 0501234567",
        )
        b = make_listing(
            source="fb_marketplace",
            source_id="f11",
            raw_text="נייד: 050-1234567",
        )
        clusters = cluster_of([a, b])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 2
