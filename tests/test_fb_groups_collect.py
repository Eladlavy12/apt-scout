import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apt_scout.fb_groups.browser import VisitResult
from apt_scout.fb_groups.collect import CollectSettings, run_collection, settings_from_config
from apt_scout.fb_groups.posts import read_feed
from apt_scout.fb_groups.rotation import Rotation

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def repo(tmp_path, groups=("a", "b", "c", "d")):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "facebook_groups.json").write_text(
        json.dumps({"groups": [{"id": g, "name": "", "enabled": True} for g in groups]}), encoding="utf-8")
    return tmp_path


def post(group, pid, now=NOW):
    return {"group_id": group, "post_id": pid, "url": f"https://www.facebook.com/groups/{group}/posts/{pid}/",
            "text": "t", "posted_at": None, "photos": [], "fetched_at": now.isoformat()}


class FakeVisit:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, group_id, now, **kwargs):
        self.calls.append(group_id)
        return self.results.get(group_id, VisitResult("empty"))


def settings(**kw):
    base = dict(batch_size=2, min_hours_between_visits=5, visit_gap_seconds=0)
    base.update(kw)
    return CollectSettings(**base)


class TestRun:
    def test_visits_a_batch_and_writes_the_feed(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({"a": VisitResult("ok", [post("a", "1"), post("a", "2")], title="Group A"), "b": VisitResult("ok", [post("b", "9")])})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == ["a", "b"]
        assert report.posts_added == 3 and report.feed_size == 3
        feed = read_feed(root / "state" / "feeds" / "facebook_groups.json")
        assert {p["post_id"] for p in feed["posts"]} == {"1", "2", "9"}
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        assert rot.group_state("a")["posts_seen"] == 2
        assert rot.group_state("a")["name"] == "Group A"
        assert rot.group_state("a")["last_outcome"] == "ok"

    def test_a_block_ends_the_batch_and_sets_backoff(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({"a": VisitResult("blocked", error="login")})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == ["a"]
        assert report.outcomes == {"a": "blocked"}
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        assert rot.blocked_until == NOW + timedelta(hours=1)
        assert rot.group_state("a")["blocked"] == 1

    def test_a_blocked_period_skips_the_run(self, tmp_path):
        root = repo(tmp_path)
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        rot.note_block(NOW - timedelta(minutes=10), 1, 24)
        rot.save()
        visit = FakeVisit({})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == []
        assert report.skipped and "blocked" in report.skipped

    def test_rotation_moves_on_next_run(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({g: VisitResult("ok", [post(g, "1")]) for g in "abcd"})
        run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        run_collection(root, NOW + timedelta(hours=1), settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == ["a", "b", "c", "d"]

    def test_existing_feed_is_merged_not_replaced(self, tmp_path):
        root = repo(tmp_path)
        first = FakeVisit({"a": VisitResult("ok", [post("a", "1")])})
        run_collection(root, NOW, settings(batch_size=1), visit=first, sleep=lambda s: None)
        second = FakeVisit({"b": VisitResult("ok", [post("b", "2", NOW + timedelta(hours=6))])})
        report = run_collection(root, NOW + timedelta(hours=6), settings(batch_size=1), visit=second, sleep=lambda s: None)
        assert report.feed_size == 2

    def test_an_error_in_one_group_does_not_stop_the_batch(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({"a": VisitResult("error", error="boom"), "b": VisitResult("ok", [post("b", "1")])})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert report.outcomes == {"a": "error", "b": "ok"}

    def test_success_resets_backoff(self, tmp_path):
        root = repo(tmp_path)
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        rot.note_block(NOW - timedelta(hours=3), 1, 24)
        rot.save()
        visit = FakeVisit({"a": VisitResult("ok", [post("a", "1")])})
        run_collection(root, NOW, settings(batch_size=1), visit=visit, sleep=lambda s: None)
        assert Rotation(root / "state" / "fb_groups_rotation.json").data["backoff_hours"] == 1


def test_settings_from_config_reads_known_keys():
    s = settings_from_config({"batch_size": 4, "visit_gap_seconds": 1, "unknown": 5})
    assert s.batch_size == 4 and s.visit_gap_seconds == 1 and s.min_hours_between_visits == 5


def test_sources_json_has_the_block():
    cfg = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))["fb_groups"]
    assert cfg["feed_file"] == "state/feeds/facebook_groups.json"
    assert cfg["rotation_file"] == "state/fb_groups_rotation.json"
