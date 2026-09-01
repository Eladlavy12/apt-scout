from datetime import datetime, timedelta, timezone

from apt_scout.scheduler import CadenceGate
from apt_scout.state import StateStore

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class TestCadenceGate:
    def test_due_when_never_ran(self, tmp_path):
        gate = CadenceGate(StateStore(tmp_path))
        assert gate.is_due("yad2", 1, NOW) is True

    def test_not_due_shortly_after_a_run(self, tmp_path):
        store = StateStore(tmp_path)
        gate = CadenceGate(store)
        gate.mark_ran("yad2", NOW)
        assert gate.is_due("yad2", 1, NOW + timedelta(minutes=30)) is False

    def test_due_again_after_the_full_cadence_elapses(self, tmp_path):
        store = StateStore(tmp_path)
        gate = CadenceGate(store)
        gate.mark_ran("yad2", NOW)
        assert gate.is_due("yad2", 1, NOW + timedelta(minutes=61)) is True

    def test_five_minute_slack_absorbs_scheduler_drift(self, tmp_path):
        # An hourly cron firing a few minutes early (e.g. at :57) must still
        # count as due, or a drifting schedule silently skips runs forever.
        store = StateStore(tmp_path)
        gate = CadenceGate(store)
        gate.mark_ran("yad2", NOW)
        assert gate.is_due("yad2", 1, NOW + timedelta(minutes=57)) is True

    def test_just_outside_the_slack_window_is_still_not_due(self, tmp_path):
        store = StateStore(tmp_path)
        gate = CadenceGate(store)
        gate.mark_ran("yad2", NOW)
        assert gate.is_due("yad2", 1, NOW + timedelta(minutes=54)) is False

    def test_mark_ran_persists_across_instances(self, tmp_path):
        CadenceGate(StateStore(tmp_path)).mark_ran("yad2", NOW)
        gate = CadenceGate(StateStore(tmp_path))
        assert gate.is_due("yad2", 1, NOW + timedelta(minutes=30)) is False

    def test_sources_are_gated_independently(self, tmp_path):
        store = StateStore(tmp_path)
        gate = CadenceGate(store)
        gate.mark_ran("yad2", NOW)
        assert gate.is_due("komo", 1, NOW + timedelta(minutes=1)) is True

    def test_fractional_cadence_hours(self, tmp_path):
        store = StateStore(tmp_path)
        gate = CadenceGate(store)
        gate.mark_ran("prog", NOW)
        assert gate.is_due("prog", 0.5, NOW + timedelta(minutes=20)) is False
        assert gate.is_due("prog", 0.5, NOW + timedelta(minutes=26)) is True
