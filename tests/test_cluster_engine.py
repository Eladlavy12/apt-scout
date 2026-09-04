from apt_scout.cluster.engine import Cluster, ClusterEngine
from apt_scout.models import Listing, Occupancy

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
        # Both carry real street addresses (differing from the bare city
        # name), so their coordinates are listing-precise and the geo key
        # is a legitimate second weak signal alongside struct.
        a = make_listing(
            source="yad2",
            source_id="y3",
            price=4800,
            rooms=3.0,
            size_sqm=65.0,
            address_text="רחוב הרצל 5",
            city="תל אביב",
            lat=32.0801,
            lon=34.7806,
        )
        b = make_listing(
            source="komo",
            source_id="k3",
            price=4800,
            rooms=3.0,
            size_sqm=65.0,
            address_text="הרצל 5, תל אביב",
            city="תל אביב",
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
            address_text="רחוב הרצל 5",
            city="תל אביב",
            lat=32.0801,
            lon=34.7806,
        )
        b = make_listing(
            source="komo",
            source_id="k4",
            price=4800,
            rooms=3.0,
            size_sqm=65.0,
            address_text="רחוב ביאליק 12",
            city="תל אביב",
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


class TestScenario12PoolingPhotos:
    def test_photoless_top_priority_member_does_not_beat_member_with_photos(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y12",
            photos=[],
            raw_text="לפרטים 050-1234567",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f12",
            photos=["u"],
            raw_text="התקשרו 050-1234567",
        )
        clusters = cluster_of([yad2, fb])
        assert len(clusters) == 1
        assert clusters[0].canonical.photos == ["u"]

    def test_no_member_has_photos_canonical_is_empty(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y12b",
            photos=[],
            raw_text="לפרטים 050-9990001",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f12b",
            photos=[],
            raw_text="התקשרו 050-9990001",
        )
        clusters = cluster_of([yad2, fb])
        assert len(clusters) == 1
        assert clusters[0].canonical.photos == []


class TestScenario13PoolingOccupancy:
    def test_roommates_from_lower_priority_member_wins_over_top_unsure(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y13",
            occupancy=Occupancy.UNSURE,
            raw_text="לפרטים 050-1230001",
        )
        komo = make_listing(
            source="komo",
            source_id="k13",
            occupancy=Occupancy.ROOMMATES,
            raw_text="התקשרו 050-1230001",
        )
        clusters = cluster_of([yad2, komo])
        assert len(clusters) == 1
        assert clusters[0].canonical.occupancy == Occupancy.ROOMMATES

    def test_first_non_unsure_in_priority_order_wins_when_no_roommates(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y13b",
            occupancy=Occupancy.UNSURE,
            raw_text="לפרטים 050-1230002",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f13b",
            occupancy=Occupancy.WHOLE,
            raw_text="התקשרו 050-1230002",
        )
        clusters = cluster_of([yad2, fb])
        assert len(clusters) == 1
        assert clusters[0].canonical.occupancy == Occupancy.WHOLE

    def test_all_members_unsure_canonical_is_unsure(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y13c",
            occupancy=Occupancy.UNSURE,
            raw_text="לפרטים 050-1230003",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f13c",
            occupancy=Occupancy.UNSURE,
            raw_text="התקשרו 050-1230003",
        )
        clusters = cluster_of([yad2, fb])
        assert len(clusters) == 1
        assert clusters[0].canonical.occupancy == Occupancy.UNSURE


class TestScenario17PoolingSublet:
    def test_sublet_from_lower_priority_member_wins_over_top_priority_false(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y17",
            is_sublet=False,
            raw_text="לפרטים 050-1230010",
        )
        komo = make_listing(
            source="komo",
            source_id="k17",
            is_sublet=True,
            raw_text="התקשרו 050-1230010",
        )
        clusters = cluster_of([yad2, komo])
        assert len(clusters) == 1
        assert clusters[0].canonical.is_sublet is True

    def test_no_member_is_a_sublet_canonical_is_false(self):
        yad2 = make_listing(
            source="yad2",
            source_id="y17b",
            is_sublet=False,
            raw_text="לפרטים 050-1230011",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f17b",
            is_sublet=False,
            raw_text="התקשרו 050-1230011",
        )
        clusters = cluster_of([yad2, fb])
        assert len(clusters) == 1
        assert clusters[0].canonical.is_sublet is False


class TestScenario14SourcesDedup:
    def test_two_yad2_members_and_one_fb_member_dedupe_sources(self):
        yad2_a = make_listing(
            source="yad2",
            source_id="y14a",
            raw_text="דירה להשכרה 050-1230004 גם: https://www.yad2.co.il/realestate/item/dup14",
        )
        yad2_b = make_listing(
            source="yad2",
            source_id="y14b",
            raw_text="לצפייה בדירה: https://www.yad2.co.il/realestate/item/dup14",
        )
        fb = make_listing(
            source="fb_marketplace",
            source_id="f14",
            raw_text="אותה דירה 050-1230004",
        )
        clusters = cluster_of([yad2_a, yad2_b, fb])
        assert len(clusters) == 1
        assert clusters[0].sources == ["yad2", "fb_marketplace"]


class TestScenario15CityCentroidGuard:
    def test_two_address_less_same_city_listings_do_not_merge(self):
        # Both geocoded from the bare city name to the exact same centroid,
        # and both size-less: without the guard they would share identical
        # geo + empty-bucket struct keys and merge two distinct apartments.
        a = make_listing(
            source="yad2",
            source_id="cg1",
            price=4800,
            rooms=3.0,
            city="תל אביב",
            lat=32.0801,
            lon=34.7806,
        )
        b = make_listing(
            source="komo",
            source_id="cg2",
            price=4800,
            rooms=3.0,
            city="תל אביב",
            lat=32.0801,
            lon=34.7806,
        )
        clusters = cluster_of([a, b])
        assert len(clusters) == 2


class TestScenario16AgencyPhoneGuard:
    def _with_phone(self, index: int):
        return make_listing(
            source="yad2",
            source_id=f"agency{index}",
            price=4000 + index * 100,
            rooms=2.0 + index,
            raw_text=f"דירה מספר {index} בתיווך, לפרטים 050-1234567",
        )

    def test_a_phone_shared_by_six_listings_is_not_a_merge_signal(self):
        # An agency switchboard number appears on the whole inventory;
        # merging on it would collapse six distinct apartments into one
        # cluster (and one alert would mark them all notified forever).
        listings = [self._with_phone(i) for i in range(6)]
        clusters = cluster_of(listings)
        assert len(clusters) == 6

    def test_a_phone_shared_by_three_listings_still_merges(self):
        listings = [self._with_phone(i) for i in range(3)]
        clusters = cluster_of(listings)
        assert len(clusters) == 1
        assert len(clusters[0].members) == 3


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


def test_canonical_takes_the_first_member_with_a_neighborhood():
    from apt_scout.cluster.engine import ClusterEngine
    from apt_scout.models import Listing

    # Fingerprints read the phone from the text (not from phone_hash), so
    # both ads carry the same number in raw_text to force a strong merge.
    a = Listing(source="yad2", source_id="1", url="https://y/1", raw_text="לפרטים 052-1234567", neighborhood=None)
    b = Listing(source="komo", source_id="2", url="https://k/2", raw_text="טל' 052-1234567", neighborhood="bavli")
    clusters = ClusterEngine().cluster([a, b], salt="s")
    assert len(clusters) == 1
    assert clusters[0].canonical.neighborhood == "bavli"
