import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apt_scout.fb_groups.groups import Group, group_url, load_groups
from apt_scout.fb_groups.posts import (
    merge_feed,
    parse_relative_time,
    post_record,
    read_feed,
    write_feed,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


class TestGroups:
    def test_loads_the_committed_config(self):
        groups = load_groups(Path("config/facebook_groups.json"))
        ids = [g.id for g in groups]
        assert len(ids) == 17
        assert len(set(ids)) == 17
        assert "ApartmentsTelAviv" in ids
        assert "101875683484689" in ids
        assert all(isinstance(g, Group) for g in groups)

    def test_rejects_duplicate_ids(self, tmp_path):
        path = tmp_path / "g.json"
        path.write_text(json.dumps({"groups": [{"id": "a", "name": "", "enabled": True}, {"id": "a", "name": "", "enabled": True}]}), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate"):
            load_groups(path)

    def test_group_url(self):
        assert group_url("tlvrent") == "https://www.facebook.com/groups/tlvrent/"


@pytest.mark.parametrize(
    "label, expected",
    [
        ("5 שעות", NOW - timedelta(hours=5)),
        ("שעה", NOW - timedelta(hours=1)),
        ("12 דקות", NOW - timedelta(minutes=12)),
        ("דקה", NOW - timedelta(minutes=1)),
        ("אתמול ב-14:30", NOW - timedelta(days=1)),
        ("3 ימים", NOW - timedelta(days=3)),
        ("יום", NOW - timedelta(days=1)),
        ("5h", NOW - timedelta(hours=5)),
        ("2d", NOW - timedelta(days=2)),
        ("Yesterday at 3:15 PM", NOW - timedelta(days=1)),
        ("Just now", NOW),
        ("עכשיו", NOW),
    ],
)
def test_relative_time(label, expected):
    assert parse_relative_time(label, NOW) == expected


@pytest.mark.parametrize("label", [None, "", "September 3", "3 בספטמבר", "garbage"])
def test_relative_time_unknown_is_none(label):
    assert parse_relative_time(label, NOW) is None


class TestPostRecord:
    def test_builds_the_spec_record(self):
        rec = post_record("tlvrent", "123", " דירה \n\n יפה ", "5 שעות", ["https://scontent.x/a.jpg"], NOW)
        assert rec == {
            "group_id": "tlvrent",
            "post_id": "123",
            "url": "https://www.facebook.com/groups/tlvrent/posts/123/",
            "text": "דירה \n\n יפה",
            "posted_at": (NOW - timedelta(hours=5)).isoformat(),
            "photos": ["https://scontent.x/a.jpg"],
            "fetched_at": NOW.isoformat(),
        }

    def test_unknown_time_is_null(self):
        assert post_record("g", "1", "x", None, [], NOW)["posted_at"] is None


class TestMergeFeed:
    def _post(self, group, pid, fetched, text="t", posted=None):
        return {"group_id": group, "post_id": pid, "url": f"https://www.facebook.com/groups/{group}/posts/{pid}/",
                "text": text, "posted_at": posted, "photos": [], "fetched_at": fetched.isoformat()}

    def test_upserts_by_group_and_post_id(self):
        old = self._post("g", "1", NOW - timedelta(hours=6), text="old")
        new = self._post("g", "1", NOW, text="new")
        merged = merge_feed([old], [new], NOW, 3, {"g"})
        assert [p["text"] for p in merged] == ["new"]

    def test_keeps_the_newer_fetch_when_old_arrives_late(self):
        newer = self._post("g", "1", NOW, text="new")
        older = self._post("g", "1", NOW - timedelta(hours=1), text="old")
        assert merge_feed([newer], [older], NOW, 3, {"g"})[0]["text"] == "new"

    def test_drops_posts_older_than_the_window(self):
        stale = self._post("g", "1", NOW - timedelta(days=1), posted=(NOW - timedelta(days=4)).isoformat())
        fresh = self._post("g", "2", NOW - timedelta(days=1), posted=(NOW - timedelta(days=2)).isoformat())
        assert [p["post_id"] for p in merge_feed([stale, fresh], [], NOW, 3, {"g"})] == ["2"]

    def test_posts_without_posted_at_age_by_fetched_at(self):
        stale = self._post("g", "1", NOW - timedelta(days=4))
        assert merge_feed([stale], [], NOW, 3, {"g"}) == []

    def test_drops_posts_from_removed_groups(self):
        assert merge_feed([self._post("gone", "1", NOW)], [], NOW, 3, {"g"}) == []

    def test_sorted_newest_first(self):
        a = self._post("g", "a", NOW, posted=(NOW - timedelta(hours=9)).isoformat())
        b = self._post("g", "b", NOW, posted=(NOW - timedelta(hours=1)).isoformat())
        assert [p["post_id"] for p in merge_feed([], [a, b], NOW, 3, {"g"})] == ["b", "a"]


class TestFeedFile:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "feeds" / "facebook_groups.json"
        write_feed(path, [{"group_id": "g", "post_id": "1", "url": "u", "text": "t", "posted_at": None, "photos": [], "fetched_at": NOW.isoformat()}], NOW)
        data = read_feed(path)
        assert data["source"] == "fb_groups"
        assert data["fetched_at"] == NOW.isoformat()
        assert data["posts"][0]["post_id"] == "1"
        assert not path.with_suffix(".json.tmp").exists()

    def test_missing_or_foreign_file_is_none(self, tmp_path):
        assert read_feed(tmp_path / "nope.json") is None
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"source": "yad2", "posts": []}), encoding="utf-8")
        assert read_feed(bad) is None
        bad.write_text("{not json", encoding="utf-8")
        assert read_feed(bad) is None
