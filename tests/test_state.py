import json

from apt_scout.state import StateStore


class TestLoadSave:
    def test_load_returns_default_when_file_absent(self, tmp_path):
        assert StateStore(tmp_path).load("missing", {"a": 1}) == {"a": 1}

    def test_round_trips_data(self, tmp_path):
        store = StateStore(tmp_path)
        store.save("thing", {"key": "ערך"})
        assert StateStore(tmp_path).load("thing", {}) == {"key": "ערך"}

    def test_writes_readable_utf8_json(self, tmp_path):
        store = StateStore(tmp_path)
        store.save("thing", {"city": "תל אביב"})
        raw = (tmp_path / "thing.json").read_text(encoding="utf-8")
        assert "תל אביב" in raw, "Hebrew must not be escaped, for readable diffs"
        assert "\n" in raw, "must be indented, for readable diffs"

    def test_corrupt_file_falls_back_to_default(self, tmp_path):
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
        assert StateStore(tmp_path).load("broken", {"safe": True}) == {"safe": True}

    def test_non_utf8_bytes_fall_back_to_default(self, tmp_path):
        (tmp_path / "binary.json").write_bytes(b"\xff\xfe\x00garbage")
        assert StateStore(tmp_path).load("binary", {"safe": True}) == {"safe": True}

    def test_save_is_atomic_leaving_no_temp_files(self, tmp_path):
        store = StateStore(tmp_path)
        store.save("thing", {"a": 1})
        assert [p.name for p in tmp_path.iterdir()] == ["thing.json"]


class TestSeenTracking:
    def test_seen_starts_empty(self, tmp_path):
        assert StateStore(tmp_path).seen_ids() == set()

    def test_mark_seen_persists(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_seen(["yad2:1", "yad2:2"])
        assert StateStore(tmp_path).seen_ids() == {"yad2:1", "yad2:2"}

    def test_mark_seen_accumulates(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_seen(["yad2:1"])
        store.mark_seen(["yad2:2"])
        assert store.seen_ids() == {"yad2:1", "yad2:2"}


class TestNotifiedTracking:
    def test_notified_is_separate_from_seen(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_seen(["yad2:1"])
        assert store.notified_ids() == set()

    def test_mark_notified_persists(self, tmp_path):
        store = StateStore(tmp_path)
        store.mark_notified(["yad2:1"])
        assert StateStore(tmp_path).notified_ids() == {"yad2:1"}
