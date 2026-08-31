from apt_scout.adapters.base import AdapterResult
from apt_scout.filters import Filters
from apt_scout.health import HealthTracker
from apt_scout.models import Listing, Occupancy
from apt_scout.pipeline import run_pipeline
from apt_scout.state import StateStore


def listing(source_id="1", **overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id=source_id,
        url=f"https://y/{source_id}",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        occupancy=Occupancy.WHOLE,
    )
    base.update(overrides)
    return Listing(**base)


class StubAdapter:
    def __init__(self, name, listings=None, error=None):
        self.name = name
        self._result = AdapterResult(
            source=name, listings=listings or [], error=error
        )

    def fetch(self, fetcher, config, since):
        return self._result


class RecordingNotifier:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    def send_listing(self, listing):
        self.sent.append(listing)
        return self.ok


def run(adapters, store, notifier, filters=None, sources=None):
    return run_pipeline(
        adapters=adapters,
        fetcher=None,
        sources_config=sources or {a.name: {"enabled": True} for a in adapters},
        filters=filters or Filters(),
        store=store,
        notifier=notifier,
    )


class TestNotification:
    def test_notifies_for_a_new_matching_listing(self, tmp_path):
        notifier = RecordingNotifier()
        report = run([StubAdapter("yad2", [listing()])], StateStore(tmp_path), notifier)
        assert report.notified == 1
        assert len(notifier.sent) == 1

    def test_does_not_notify_twice_for_the_same_listing(self, tmp_path):
        store = StateStore(tmp_path)
        adapters = [StubAdapter("yad2", [listing()])]
        run(adapters, store, RecordingNotifier())

        notifier = RecordingNotifier()
        report = run(adapters, store, notifier)

        assert report.notified == 0
        assert notifier.sent == []

    def test_does_not_notify_for_a_non_matching_listing(self, tmp_path):
        notifier = RecordingNotifier()
        report = run(
            [StubAdapter("yad2", [listing(price=9000)])],
            StateStore(tmp_path),
            notifier,
        )
        assert report.matched == 0
        assert notifier.sent == []

    def test_a_failed_send_is_retried_on_the_next_run(self, tmp_path):
        # notified_at is only recorded after a confirmed send, so an alert is
        # never lost to a transient Telegram outage.
        store = StateStore(tmp_path)
        adapters = [StubAdapter("yad2", [listing()])]
        run(adapters, store, RecordingNotifier(ok=False))

        retry = RecordingNotifier(ok=True)
        report = run(adapters, store, retry)

        assert report.notified == 1
        assert len(retry.sent) == 1


class TestFailureIsolation:
    def test_one_failing_adapter_does_not_stop_the_others(self, tmp_path):
        notifier = RecordingNotifier()
        report = run(
            [
                StubAdapter("yad2", error="blocked"),
                StubAdapter("madlan", [listing(source_id="2", source="madlan")]),
            ],
            StateStore(tmp_path),
            notifier,
        )
        assert report.notified == 1
        assert "yad2" in report.errors

    def test_an_adapter_that_raises_is_caught(self, tmp_path):
        class Exploding:
            name = "bad"

            def fetch(self, fetcher, config, since):
                raise RuntimeError("kaboom")

        report = run([Exploding()], StateStore(tmp_path), RecordingNotifier())
        assert "bad" in report.errors
        assert "kaboom" in report.errors["bad"]

    def test_health_is_recorded_for_every_source(self, tmp_path):
        store = StateStore(tmp_path)
        run(
            [StubAdapter("yad2", error="blocked"), StubAdapter("madlan", [listing()])],
            store,
            RecordingNotifier(),
        )
        report = HealthTracker(store).report()
        assert report["yad2"]["consecutive_failures"] == 1
        assert report["madlan"]["consecutive_failures"] == 0


class TestSourceToggles:
    def test_a_disabled_source_is_skipped(self, tmp_path):
        notifier = RecordingNotifier()
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": False}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=notifier,
        )
        assert report.fetched == 0
        assert notifier.sent == []


class TestEnrichment:
    def test_enrichers_run_before_filtering(self, tmp_path):
        # A listing 40 minutes away must be rejected, which can only happen if
        # the enricher has already set drive_minutes.
        def set_far_drive_time(item):
            item.drive_minutes = 40.0
            return item

        notifier = RecordingNotifier()
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(max_drive_minutes=15),
            store=StateStore(tmp_path),
            notifier=notifier,
            enrichers=[set_far_drive_time],
        )
        assert report.matched == 0
        assert notifier.sent == []
