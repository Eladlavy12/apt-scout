from apt_scout.health import HealthTracker
from apt_scout.state import StateStore


class TestRecording:
    def test_records_a_success(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True)
        entry = tracker.report()["yad2"]
        assert entry["consecutive_failures"] == 0
        assert entry["last_success"] is not None

    def test_records_a_failure_with_its_message(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=False, error="blocked")
        entry = tracker.report()["yad2"]
        assert entry["consecutive_failures"] == 1
        assert entry["last_error"] == "blocked"

    def test_records_a_detail_on_success(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True, detail="local feed from 2026-09-02T18:45Z")
        entry = tracker.report()["yad2"]
        assert entry["detail"] == "local feed from 2026-09-02T18:45Z"

    def test_detail_defaults_to_none(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True)
        assert tracker.report()["yad2"]["detail"] is None

    def test_a_failure_clears_the_previous_detail(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True, detail="local feed from 2026-09-02T18:45Z")
        tracker.record("yad2", ok=False, error="blocked")
        assert tracker.report()["yad2"]["detail"] is None

    def test_failures_accumulate(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        for _ in range(3):
            tracker.record("yad2", ok=False, error="blocked")
        assert tracker.report()["yad2"]["consecutive_failures"] == 3

    def test_a_success_resets_the_failure_streak(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=False, error="blocked")
        tracker.record("yad2", ok=True)
        assert tracker.report()["yad2"]["consecutive_failures"] == 0

    def test_state_survives_a_restart(self, tmp_path):
        HealthTracker(StateStore(tmp_path)).record("yad2", ok=False, error="x")
        reloaded = HealthTracker(StateStore(tmp_path))
        assert reloaded.report()["yad2"]["consecutive_failures"] == 1


class TestFailingSources:
    def test_reports_sources_at_or_over_the_threshold(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        for _ in range(3):
            tracker.record("yad2", ok=False, error="blocked")
        tracker.record("madlan", ok=False, error="blocked")
        assert tracker.failing_sources(threshold=3) == ["yad2"]

    def test_healthy_sources_are_not_reported(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True)
        assert tracker.failing_sources() == []
