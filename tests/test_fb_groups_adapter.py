import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apt_scout.adapters.fb_groups import FbGroupsAdapter, listing_from_post
from apt_scout.models import Listing, Occupancy

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def post(**over):
    base = {"group_id": "tlvrent", "post_id": "55", "url": "https://www.facebook.com/groups/tlvrent/posts/55/",
            "text": "להשכרה בפלורנטין\n3 חדרים, 4,900 ₪, כניסה מיידית", "posted_at": (NOW - timedelta(hours=3)).isoformat(),
            "photos": ["https://scontent.x/a.jpg"], "fetched_at": NOW.isoformat()}
    base.update(over)
    return base


class TestListingFromPost:
    def test_maps_the_record(self):
        item = listing_from_post(post(), NOW, 3)
        assert item.source == "fb_groups"
        assert item.source_id == "tlvrent:55"
        assert item.group_id == "tlvrent"
        assert item.url.endswith("/posts/55/")
        assert item.title == "להשכרה בפלורנטין"
        assert item.raw_text.startswith("להשכרה")
        assert item.photos == ["https://scontent.x/a.jpg"]
        assert item.occupancy is Occupancy.UNSURE
        assert item.posted_at == NOW - timedelta(hours=3)
        assert item.price is None  # parsing happens in enrichment, not here

    def test_title_is_capped(self):
        item = listing_from_post(post(text="x" * 300), NOW, 3)
        assert len(item.title) == 120

    def test_seeker_posts_are_dropped(self):
        assert listing_from_post(post(text="מחפשת דירה 2 חדרים במרכז"), NOW, 3) is None

    def test_old_posts_are_dropped(self):
        assert listing_from_post(post(posted_at=(NOW - timedelta(days=4)).isoformat()), NOW, 3) is None

    def test_missing_posted_at_ages_by_fetched_at(self):
        assert listing_from_post(post(posted_at=None, fetched_at=(NOW - timedelta(days=5)).isoformat()), NOW, 3) is None
        assert listing_from_post(post(posted_at=None), NOW, 3) is not None

    def test_unparseable_time_label_is_dropped(self):
        # I4: posted_at is None because the label couldn't be parsed - age
        # unknown must fail closed, not fall back to fetched_at.
        assert listing_from_post(post(posted_at=None, time_label="garbage"), NOW, 3) is None

    def test_missing_time_label_keeps_the_fetch_time_fallback(self):
        # I4: no label at all (time_label None/empty) keeps the existing
        # fetch-time fallback.
        item = listing_from_post(post(posted_at=None, time_label=None), NOW, 3)
        assert item is not None

    def test_missing_ids_are_dropped(self):
        assert listing_from_post(post(post_id=None), NOW, 3) is None
        assert listing_from_post({"text": "x"}, NOW, 3) is None


def repo_with_feed(tmp_path, posts, fetched_at=NOW, rotation=None):
    feed = tmp_path / "state" / "feeds" / "facebook_groups.json"
    feed.parent.mkdir(parents=True)
    feed.write_text(json.dumps({"source": "fb_groups", "fetched_at": fetched_at.isoformat(), "posts": posts}, ensure_ascii=False), encoding="utf-8")
    if rotation is not None:
        (tmp_path / "state" / "fb_groups_rotation.json").write_text(json.dumps(rotation), encoding="utf-8")
    return {"repo_root": str(tmp_path), "feed_file": "state/feeds/facebook_groups.json", "feed_max_age_hours": 24,
            "max_post_age_days": 3, "rotation_file": "state/fb_groups_rotation.json", "enabled": True}


class TestAdapter:
    def test_reads_a_fresh_feed(self, tmp_path):
        config = repo_with_feed(tmp_path, [post(), post(post_id="56"), post(post_id="57", text="מחפש דירה בבקשה")])
        result = FbGroupsAdapter().fetch(None, config, since=None)
        assert result.error is None
        assert [l.source_id for l in result.listings] == ["tlvrent:55", "tlvrent:56"]
        assert result.detail.startswith("local feed from")

    def test_stale_feed_is_an_error(self, tmp_path):
        config = repo_with_feed(tmp_path, [post()], fetched_at=NOW - timedelta(hours=30))
        result = FbGroupsAdapter().fetch(None, config, since=None)
        assert result.listings == []
        assert "stale" in result.error

    def test_missing_feed_is_an_error(self, tmp_path):
        config = {"repo_root": str(tmp_path), "feed_file": "state/feeds/facebook_groups.json"}
        assert "no feed" in FbGroupsAdapter().fetch(None, config, since=None).error

    def test_block_state_shows_in_the_detail(self, tmp_path):
        until = NOW + timedelta(hours=2)
        config = repo_with_feed(tmp_path, [post()], rotation={"groups": {}, "blocked_until": until.isoformat(), "backoff_hours": 2})
        detail = FbGroupsAdapter(now=lambda: NOW).fetch(None, config, since=None).detail
        assert "חסום עד" in detail

    def test_never_raises_on_garbage(self, tmp_path):
        feed = tmp_path / "state" / "feeds" / "facebook_groups.json"
        feed.parent.mkdir(parents=True)
        feed.write_text("{nope", encoding="utf-8")
        config = {"repo_root": str(tmp_path), "feed_file": "state/feeds/facebook_groups.json"}
        assert FbGroupsAdapter().fetch(None, config, since=None).error
