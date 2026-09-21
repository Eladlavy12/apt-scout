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

    def test_a_block_after_an_ok_visit_still_doubles_backoff_not_resets(self, tmp_path):
        root = repo(tmp_path)
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        rot.note_block(NOW - timedelta(hours=10), 4, 24)  # backoff_hours -> 8, already past
        rot.save()
        visit = FakeVisit({"a": VisitResult("ok", [post("a", "1")]), "b": VisitResult("blocked", error="login")})
        run_collection(root, NOW, settings(batch_size=2), visit=visit, sleep=lambda s: None)
        result = Rotation(root / "state" / "fb_groups_rotation.json")
        # M2: an ok visit earlier in the same batch must not reset
        # backoff_hours before a later block in that batch is recorded - it
        # must keep doubling from where it left off (8 -> 16), not restart
        # from settings.backoff_hours_initial (1).
        assert result.data["backoff_hours"] == 16


def test_settings_from_config_reads_known_keys():
    s = settings_from_config({"batch_size": 4, "visit_gap_seconds": 1, "unknown": 5})
    assert s.batch_size == 4 and s.visit_gap_seconds == 1 and s.min_hours_between_visits == 5


def test_a_visit_that_raises_is_recorded_as_an_error(tmp_path):
    root = repo(tmp_path)

    class RaisingVisit:
        def __call__(self, group_id, now):
            if group_id == "a":
                raise RuntimeError("boom")
            return VisitResult("ok", [post(group_id, "1")])

    report = run_collection(root, NOW, settings(batch_size=2), visit=RaisingVisit(), sleep=lambda s: None)
    assert report.outcomes == {"a": "error", "b": "ok"}
    rot = Rotation(root / "state" / "fb_groups_rotation.json")
    assert rot.group_state("a")["last_outcome"] == "error"
    feed = read_feed(root / "state" / "feeds" / "facebook_groups.json")
    assert {p["post_id"] for p in feed["posts"]} == {"1"}


def test_pruning_lands_even_without_new_posts(tmp_path):
    root = repo(tmp_path)
    # First run: collect one post at NOW
    first_visit = FakeVisit({"a": VisitResult("ok", [post("a", "1", NOW)])})
    first_report = run_collection(root, NOW, settings(batch_size=1), visit=first_visit, sleep=lambda s: None)
    assert first_report.feed_size == 1

    # Second run: 4 days later, no new posts (empty), but max_post_age_days=1
    # So the old post should be pruned
    second_visit = FakeVisit({g: VisitResult("empty") for g in "abcd"})
    second_report = run_collection(
        root,
        NOW + timedelta(days=4),
        settings(batch_size=1, max_post_age_days=1),
        visit=second_visit,
        sleep=lambda s: None
    )
    assert second_report.feed_size == 0
    feed = read_feed(root / "state" / "feeds" / "facebook_groups.json")
    assert feed["posts"] == []


def test_sources_json_has_the_block():
    # M3: independent of the process's cwd - anchored to the repo root via
    # this test file's own location, not a path relative to wherever pytest
    # happens to be invoked from.
    config_path = Path(__file__).resolve().parents[1] / "config" / "sources.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))["fb_groups"]
    assert cfg["feed_file"] == "state/feeds/facebook_groups.json"
    assert cfg["rotation_file"] == "state/fb_groups_rotation.json"
