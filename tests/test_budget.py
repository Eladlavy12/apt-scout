from datetime import datetime, timezone

from apt_scout.budget import BudgetGuard
from apt_scout.state import StateStore


def dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


class FakeNotifier:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    def send_text(self, text: str) -> bool:
        self.sent.append(text)
        return self.ok


class TestFreshMonth:
    def test_can_spend_is_true(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path))
        assert guard.can_spend("apify", dt("2026-09-01T00:00:00")) is True

    def test_spent_is_zero(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path))
        assert guard.spent_this_month(dt("2026-09-01T00:00:00")) == 0.0


class TestRecording:
    def test_accumulates_cost(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path))
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=300, cost_usd=300 * 0.0005, now=now)
        assert guard.spent_this_month(now) == 0.15

    def test_accumulates_across_multiple_records(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path))
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=100, cost_usd=0.05, now=now)
        guard.record("apify", results=100, cost_usd=0.05, now=now)
        assert guard.spent_this_month(now) == 0.1

    def test_tracks_cost_by_source(self, tmp_path):
        store = StateStore(tmp_path)
        guard = BudgetGuard(store)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=10, cost_usd=0.10, now=now)
        guard.record("other", results=10, cost_usd=0.20, now=now)
        assert store.load("budget", {})["by_source"] == {
            "apify": 0.10,
            "other": 0.20,
        }


class TestCapEnforcement:
    def test_can_spend_false_at_cap(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=5.0, now=now)
        assert guard.can_spend("apify", now) is False

    def test_can_spend_false_above_cap(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=5.50, now=now)
        assert guard.can_spend("apify", now) is False

    def test_can_spend_true_below_cap(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=4.99, now=now)
        assert guard.can_spend("apify", now) is True


class TestWarning:
    def test_crossing_80_percent_sends_one_warning(self, tmp_path):
        notifier = FakeNotifier()
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0, notifier=notifier)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=4.10, now=now)
        assert len(notifier.sent) == 1
        assert "4.1" in notifier.sent[0]

    def test_warning_not_repeated_across_multiple_records(self, tmp_path):
        notifier = FakeNotifier()
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0, notifier=notifier)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=4.10, now=now)
        guard.record("apify", results=1, cost_usd=0.10, now=now)
        guard.record("apify", results=1, cost_usd=0.10, now=now)
        assert len(notifier.sent) == 1

    def test_below_80_percent_sends_no_warning(self, tmp_path):
        notifier = FakeNotifier()
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0, notifier=notifier)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=1.0, now=now)
        assert notifier.sent == []

    def test_no_notifier_does_not_crash(self, tmp_path):
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0, notifier=None)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=4.50, now=now)
        assert guard.spent_this_month(now) == 4.50

    def test_failed_send_is_retried_next_record(self, tmp_path):
        notifier = FakeNotifier(ok=False)
        guard = BudgetGuard(StateStore(tmp_path), monthly_cap_usd=5.0, notifier=notifier)
        now = dt("2026-09-01T00:00:00")
        guard.record("apify", results=1, cost_usd=4.10, now=now)
        guard.record("apify", results=1, cost_usd=0.05, now=now)
        assert len(notifier.sent) == 2

        notifier.ok = True
        guard.record("apify", results=1, cost_usd=0.05, now=now)
        assert len(notifier.sent) == 3

        # now that a send finally succeeded, it should not fire again.
        guard.record("apify", results=1, cost_usd=0.05, now=now)
        assert len(notifier.sent) == 3


class TestMonthRollover:
    def test_rollover_resets_spent_and_by_source_and_warning_flag(self, tmp_path):
        notifier = FakeNotifier()
        store = StateStore(tmp_path)
        guard = BudgetGuard(store, monthly_cap_usd=5.0, notifier=notifier)
        september = dt("2026-09-15T00:00:00")
        october = dt("2026-10-01T00:00:00")

        guard.record("apify", results=1, cost_usd=4.50, now=september)
        assert len(notifier.sent) == 1

        assert guard.spent_this_month(october) == 0.0
        assert guard.can_spend("apify", october) is True
        assert store.load("budget", {})["by_source"] == {}
        assert store.load("budget", {})["warned"] is False

        # a fresh crossing in the new month should warn again.
        guard.record("apify", results=1, cost_usd=4.10, now=october)
        assert len(notifier.sent) == 2


class TestPersistence:
    def test_state_survives_a_restart(self, tmp_path):
        now = dt("2026-09-01T00:00:00")
        BudgetGuard(StateStore(tmp_path)).record(
            "apify", results=1, cost_usd=1.23, now=now
        )
        reloaded = BudgetGuard(StateStore(tmp_path))
        assert reloaded.spent_this_month(now) == 1.23

    def test_state_file_shape(self, tmp_path):
        store = StateStore(tmp_path)
        now = dt("2026-09-01T00:00:00")
        BudgetGuard(store).record("apify", results=1, cost_usd=1.0, now=now)
        data = store.load("budget", {})
        assert data["month"] == "2026-09"
        assert data["spent_usd"] == 1.0
        assert data["by_source"] == {"apify": 1.0}
        assert data["warned"] is False
