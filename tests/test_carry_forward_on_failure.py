"""A source that fails keeps its last good listings in the portal for a while.

Before this, only cadence-skipped sources were restored from the carry-forward
cache; a source that errored (yad2 while the PC feed is stale, homeless while
blocked) vanished from the portal the same hour it failed.
"""
from datetime import datetime, timedelta, timezone

from apt_scout.adapters.base import AdapterResult
from apt_scout.filters import Filters
from apt_scout.health import HealthTracker
from apt_scout.models import Listing, Occupancy
from apt_scout.pipeline import PORTAL_CACHE, PORTAL_CACHE_META, run_pipeline
from apt_scout.state import StateStore

T0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
SOURCES = {"yad2": {"enabled": True, "cadence_hours": 1}, "komo": {"enabled": True, "cadence_hours": 1}}


def listing(source="yad2", source_id="1") -> Listing:
    return Listing(
        source=source,
        source_id=source_id,
        url=f"https://{source}/{source_id}",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        occupancy=Occupancy.WHOLE,
    )


class StubAdapter:
    def __init__(self, name, listings=None, error=None):
        self.name = name
        self._result = AdapterResult(source=name, listings=listings or [], error=error)

    def fetch(self, fetcher, config, since):
        return self._result


class Notifier:
    def __init__(self):
        self.sent = []
        self.texts = []

    def send_listing(self, item):
        self.sent.append(item)
        return True

    def send_text(self, text):
        self.texts.append(text)
        return True


class AlwaysDue:
    def is_due(self, source, cadence_hours, now):
        return True

    def mark_ran(self, source, now):
        pass


def run(adapters, store, now, notifier=None, **kwargs):
    return run_pipeline(
        adapters=adapters,
        fetcher=None,
        sources_config=dict(SOURCES),
        filters=Filters(),
        store=store,
        notifier=notifier or Notifier(),
        gate=AlwaysDue(),
        now=now,
        **kwargs,
    )


def seed(store):
    """Run 1: yad2 and komo both fetch fine."""
    run(
        [StubAdapter("yad2", [listing("yad2")]), StubAdapter("komo", [listing("komo", "k1")])],
        store,
        now=T0,
    )


class TestFailedSourceIsRestored:
    def test_a_failed_source_keeps_its_last_listings_in_the_portal(self, tmp_path):
        store = StateStore(tmp_path)
        seed(store)

        notifier = Notifier()
        report = run(
            [StubAdapter("yad2", error="HTTP 403"), StubAdapter("komo", [listing("komo", "k1")])],
            store,
            now=T0 + timedelta(hours=3),
            notifier=notifier,
        )

        ids = {item.stable_id() for item in report.listings}
        assert "yad2:1" in ids
        assert report.restored == {"yad2": 1}
        # Restored listings are neither fetched nor new, and never re-alerted.
        assert report.fetched == 1
        assert report.new == 0
        assert notifier.sent == []
        # The failure is still a failure, but the health entry says what is shown.
        entry = HealthTracker(store).report()["yad2"]
        assert entry["consecutive_failures"] == 1
        assert entry["last_error"] == "HTTP 403"
        assert "1" in entry["detail"]

    def test_a_source_that_raises_is_restored_too(self, tmp_path):
        store = StateStore(tmp_path)
        seed(store)

        class Boom:
            name = "yad2"

            def fetch(self, fetcher, config, since):
                raise RuntimeError("network down")

        report = run([Boom(), StubAdapter("komo", [listing("komo", "k1")])], store, now=T0 + timedelta(hours=1))
        assert report.restored == {"yad2": 1}
        assert "yad2" in report.errors


class TestStaleCacheIsNotRestored:
    def test_older_than_the_limit_is_dropped(self, tmp_path):
        store = StateStore(tmp_path)
        seed(store)

        report = run(
            [StubAdapter("yad2", error="HTTP 403"), StubAdapter("komo", [listing("komo", "k1")])],
            store,
            now=T0 + timedelta(hours=25),
        )
        ids = {item.stable_id() for item in report.listings}
        assert "yad2:1" not in ids
        assert report.restored == {}
        assert HealthTracker(store).report()["yad2"]["detail"] is None

    def test_the_limit_is_configurable(self, tmp_path):
        store = StateStore(tmp_path)
        seed(store)

        report = run(
            [StubAdapter("yad2", error="HTTP 403"), StubAdapter("komo", [listing("komo", "k1")])],
            store,
            now=T0 + timedelta(hours=3),
            max_stale_hours=2,
        )
        assert report.restored == {}

    def test_a_legacy_cache_without_timestamps_is_not_restored_on_failure(self, tmp_path):
        store = StateStore(tmp_path)
        seed(store)
        store.save(PORTAL_CACHE_META, {})  # pre-upgrade state: no fetch times

        report = run(
            [StubAdapter("yad2", error="HTTP 403"), StubAdapter("komo", [listing("komo", "k1")])],
            store,
            now=T0 + timedelta(hours=1),
        )
        assert report.restored == {}

    def test_a_successful_fetch_refreshes_the_timestamp(self, tmp_path):
        store = StateStore(tmp_path)
        seed(store)
        assert store.load(PORTAL_CACHE_META, {})["yad2"] == T0.isoformat()
        assert set(store.load(PORTAL_CACHE, {})) == {"yad2", "komo"}

        run([StubAdapter("yad2", [listing("yad2")]), StubAdapter("komo", [])], store, now=T0 + timedelta(hours=1))
        assert store.load(PORTAL_CACHE_META, {})["yad2"] == (T0 + timedelta(hours=1)).isoformat()


class TestHealthDetailOnFailure:
    def test_a_failure_can_carry_a_detail(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=False, error="HTTP 403", detail="showing cached listings")
        entry = tracker.report()["yad2"]
        assert entry["consecutive_failures"] == 1
        assert entry["detail"] == "showing cached listings"

    def test_a_failure_without_a_detail_still_clears_it(self, tmp_path):
        tracker = HealthTracker(StateStore(tmp_path))
        tracker.record("yad2", ok=True, detail="local feed")
        tracker.record("yad2", ok=False, error="HTTP 403")
        assert tracker.report()["yad2"]["detail"] is None
