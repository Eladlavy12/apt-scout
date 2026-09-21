import json
from datetime import datetime, timedelta, timezone

from apt_scout.fb_groups.groups import Group
from apt_scout.fb_groups.rotation import Rotation

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
G = [Group("a", "", True), Group("b", "", True), Group("c", "", False), Group("d", "", True)]


def rot(tmp_path):
    return Rotation(tmp_path / "rot.json")


class TestPick:
    def test_never_visited_first_then_least_recent(self, tmp_path):
        r = rot(tmp_path)
        r.record("a", "ok", 3, NOW - timedelta(hours=10))
        r.record("b", "ok", 3, NOW - timedelta(hours=20))
        picked = [g.id for g in r.pick(G, NOW, batch_size=3, min_gap_hours=5)]
        assert picked == ["d", "b", "a"]

    def test_respects_the_minimum_gap_and_batch_size(self, tmp_path):
        r = rot(tmp_path)
        r.record("a", "ok", 1, NOW - timedelta(hours=1))
        picked = [g.id for g in r.pick(G, NOW, batch_size=1, min_gap_hours=5)]
        assert picked == ["b"]

    def test_skips_disabled_groups(self, tmp_path):
        assert "c" not in [g.id for g in rot(tmp_path).pick(G, NOW, 10, 5)]


class TestBackoff:
    def test_block_sets_blocked_until_and_doubles(self, tmp_path):
        r = rot(tmp_path)
        r.note_block(NOW, initial_hours=1, max_hours=24)
        assert r.blocked_until == NOW + timedelta(hours=1)
        assert r.is_blocked(NOW + timedelta(minutes=30))
        assert not r.is_blocked(NOW + timedelta(hours=2))
        r.note_block(NOW + timedelta(hours=2), initial_hours=1, max_hours=24)
        assert r.blocked_until == NOW + timedelta(hours=4)

    def test_backoff_is_capped(self, tmp_path):
        r = rot(tmp_path)
        for i in range(10):
            r.note_block(NOW + timedelta(days=i), initial_hours=1, max_hours=24)
        assert r.data["backoff_hours"] == 24

    def test_success_resets(self, tmp_path):
        r = rot(tmp_path)
        r.note_block(NOW, 1, 24)
        r.note_block(NOW, 1, 24)
        r.note_ok(initial_hours=1)
        assert r.blocked_until is None
        assert r.data["backoff_hours"] == 1


class TestRecordAndPersist:
    def test_counters_and_round_trip(self, tmp_path):
        r = rot(tmp_path)
        r.record("a", "ok", 5, NOW)
        r.record("a", "blocked", 0, NOW + timedelta(hours=6))
        r.save()
        again = Rotation(tmp_path / "rot.json")
        state = again.group_state("a")
        assert state["visits"] == 2
        assert state["blocked"] == 1
        assert state["posts_seen"] == 5
        assert state["last_outcome"] == "blocked"
        assert state["last_visit"] == (NOW + timedelta(hours=6)).isoformat()

    def test_corrupt_file_starts_empty(self, tmp_path):
        (tmp_path / "rot.json").write_text("{oops", encoding="utf-8")
        assert Rotation(tmp_path / "rot.json").data["groups"] == {}

    def test_junk_keys_are_not_persisted(self, tmp_path):
        # Write a file with junk key plus valid data
        file_path = tmp_path / "rot.json"
        file_path.write_text(
            json.dumps({
                "groups": {"a": {"last_visit": None, "last_outcome": None, "visits": 0, "blocked": 0, "posts_seen": 0}},
                "blocked_until": None,
                "backoff_hours": None,
                "junk": 1
            }),
            encoding="utf-8"
        )
        # Load and save
        r = Rotation(file_path)
        r.save()
        # Reload raw JSON and check keys
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        assert set(raw.keys()) == {"groups", "blocked_until", "backoff_hours"}

    def test_pick_has_no_side_effects(self, tmp_path):
        r = Rotation(tmp_path / "rot.json")
        r.pick(G, NOW, 10, 5)
        assert r.data["groups"] == {}
