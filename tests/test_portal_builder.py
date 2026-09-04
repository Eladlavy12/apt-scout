import json
from datetime import datetime, timezone

from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy
from apt_scout.portal.builder import build_portal, listing_to_public_dict

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def listing(**overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id="1",
        url="https://y/1",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        drive_minutes=11.4,
        distance_km=3.4,
        city="תל אביב",
        address_text="הרצל 10",
        lat=32.07,
        lon=34.79,
        photos=["https://img/1.jpg"],
        occupancy=Occupancy.WHOLE,
        phone_hash="deadbeef",
        first_seen_at=NOW,
    )
    base.update(overrides)
    return Listing(**base)


class TestPublicDict:
    def test_includes_the_display_fields(self):
        data = listing_to_public_dict(listing())
        assert data["price"] == 4800
        assert data["rooms"] == 3.0
        assert data["drive_minutes"] == 11.4
        assert data["distance_km"] == 3.4
        assert data["url"] == "https://y/1"

    def test_never_includes_the_phone_hash(self):
        # The salted hash is an internal matching key. It has no display value
        # and publishing it would be a needless leak of derived personal data.
        assert "phone_hash" not in listing_to_public_dict(listing())

    def test_never_includes_raw_text(self):
        # Raw post text routinely contains phone numbers and names.
        data = listing_to_public_dict(listing(raw_text="חייגו 050-1234567"))
        assert "raw_text" not in data
        assert "050" not in json.dumps(data, ensure_ascii=False)

    def test_serialises_datetimes_as_iso_strings(self):
        assert listing_to_public_dict(listing())["first_seen_at"] == NOW.isoformat()

    def test_handles_missing_values(self):
        data = listing_to_public_dict(listing(price=None, first_seen_at=None))
        assert data["price"] is None
        assert data["first_seen_at"] is None


    def test_includes_is_sublet(self):
        data = listing_to_public_dict(listing(is_sublet=True))
        assert data["is_sublet"] is True

    def test_includes_sources(self):
        data = listing_to_public_dict(listing(sources=["yad2", "fb_marketplace"]))
        assert data["sources"] == ["yad2", "fb_marketplace"]

    def test_publishes_the_neighborhood_id(self):
        assert listing_to_public_dict(listing(neighborhood="bavli"))["neighborhood"] == "bavli"


class TestBuildPortal:
    def test_writes_the_data_file(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert len(data["listings"]) == 1
        assert data["generated_at"] == NOW.isoformat()

    def test_copies_the_static_assets(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW)
        assert (tmp_path / "index.html").exists()
        assert (tmp_path / "app.js").exists()
        assert (tmp_path / "style.css").exists()

    def test_includes_source_health(self, tmp_path):
        health = {"yad2": {"consecutive_failures": 0, "last_success": NOW.isoformat()}}
        build_portal(tmp_path, [listing()], health, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["health"]["yad2"]["consecutive_failures"] == 0

    def test_includes_the_alert_thresholds_as_initial_ui_values(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(max_price=6000), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["defaults"]["max_price"] == 6000

    def test_no_phone_number_appears_anywhere_in_the_output(self, tmp_path):
        # The hard rule from the spec, enforced by a test rather than a comment.
        build_portal(
            tmp_path,
            [listing(raw_text="לפרטים 052-9876543", phone_hash="abc123")],
            {},
            Filters(),
            NOW,
        )
        published = (tmp_path / "data" / "listings.json").read_text("utf-8")
        assert "052" not in published
        assert "9876543" not in published
        assert "abc123" not in published

    def test_scrubs_phones_from_title_and_address(self, tmp_path):
        # Phone numbers in free-text fields (title, address_text) must be
        # scrubbed from the published output. Non-phone numbers like house
        # numbers and prices must survive.
        build_portal(
            tmp_path,
            [
                listing(
                    title="למכירה! חייגו 052-1234567 עכשיו",
                    address_text="הרצל 10, 03-5551234",
                    price=4500,
                )
            ],
            {},
            Filters(),
            NOW,
        )
        published = (tmp_path / "data" / "listings.json").read_text("utf-8")
        # Phone digits must not appear
        assert "052" not in published
        assert "1234567" not in published
        assert "03-" not in published
        assert "5551234" not in published
        # House number and price must survive
        assert "10" in published
        assert "4500" in published

    def test_sorts_newest_first(self, tmp_path):
        older = listing(source_id="old", first_seen_at=datetime(2026, 8, 30, tzinfo=timezone.utc))
        newer = listing(source_id="new", first_seen_at=datetime(2026, 8, 31, tzinfo=timezone.utc))
        build_portal(tmp_path, [older, newer], {}, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["listings"][0]["source_id"] == "new"


from apt_scout.neighborhoods.knowledge import KnowledgeBase


def knowledge():
    return KnowledgeBase.from_dict(
        {"bavli": {"names": ["בבלי"], "city": "תל אביב יפו", "reputation": "sought_after", "summary": "s",
                   "pros": ["a", "b"], "cons": ["c", "d"], "tags": ["quiet"], "sources": ["x"],
                   "notes": "private"}}
    )


class TestNeighborhoodsFile:
    def test_publishes_profiles_without_notes_or_sources(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW, knowledge=knowledge())
        data = json.loads((tmp_path / "data" / "neighborhoods.json").read_text(encoding="utf-8"))
        assert data["bavli"]["names"] == ["בבלי"]
        assert "notes" not in data["bavli"]
        assert "sources" not in data["bavli"]
        assert "private" not in (tmp_path / "data" / "neighborhoods.json").read_text(encoding="utf-8")

    def test_writes_an_empty_object_without_a_knowledge_base(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW)
        assert json.loads((tmp_path / "data" / "neighborhoods.json").read_text(encoding="utf-8")) == {}

    def test_defaults_carry_the_new_filter_fields(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(excluded_neighborhoods=["bavli"]), NOW)
        payload = json.loads((tmp_path / "data" / "listings.json").read_text(encoding="utf-8"))
        assert payload["defaults"]["cities"] == ["תל אביב יפו", "גבעתיים", "רמת גן"]
        assert payload["defaults"]["excluded_neighborhoods"] == ["bavli"]
