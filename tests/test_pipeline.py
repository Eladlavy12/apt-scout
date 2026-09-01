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
        self.texts = []

    def send_listing(self, listing):
        self.sent.append(listing)
        return self.ok

    def send_text(self, text):
        self.texts.append(text)
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


class TestIntraRunDedup:
    def test_the_same_listing_twice_in_one_run_notifies_once(self, tmp_path):
        notifier = RecordingNotifier()
        report = run(
            [StubAdapter("yad2", [listing(), listing()])],
            StateStore(tmp_path),
            notifier,
        )
        assert report.fetched == 2
        assert report.matched == 1
        assert report.notified == 1
        assert len(notifier.sent) == 1


class TestFirstSeenPersistence:
    def test_first_seen_survives_across_runs(self, tmp_path):
        from datetime import datetime, timezone

        store = StateStore(tmp_path)
        adapters = [StubAdapter("yad2", [listing()])]
        first_run = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)
        second_run = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)

        run_pipeline(
            adapters=adapters,
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(),
            store=store,
            notifier=RecordingNotifier(),
            now=first_run,
        )
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(),
            store=store,
            notifier=RecordingNotifier(),
            now=second_run,
        )

        assert report.new == 0
        assert report.listings[0].first_seen_at == first_run

    def test_legacy_list_form_seen_state_still_works(self, tmp_path):
        import json

        (tmp_path / "seen.json").write_text(json.dumps(["yad2:1"]), encoding="utf-8")
        store = StateStore(tmp_path)

        report = run([StubAdapter("yad2", [listing()])], store, RecordingNotifier())

        assert report.new == 0
        assert report.listings[0].first_seen_at is None


class TestNotifyPersistence:
    def test_a_sent_alert_is_recorded_before_the_run_finishes(self, tmp_path):
        # Simulate a crash mid-loop: the second send blows up, yet the first
        # alert must already be on disk so it is never sent twice.
        import pytest

        store = StateStore(tmp_path)

        class ExplodesOnSecondSend:
            def __init__(self):
                self.count = 0

            def send_listing(self, item):
                self.count += 1
                if self.count > 1:
                    raise RuntimeError("crash mid-run")
                return True

        with pytest.raises(RuntimeError):
            run(
                [StubAdapter("yad2", [listing("1"), listing("2")])],
                store,
                ExplodesOnSecondSend(),
            )

        assert StateStore(tmp_path).notified_ids() == {"yad2:1"}


class TestEnricherIsolation:
    def test_a_raising_enricher_does_not_stop_the_run(self, tmp_path):
        def explode(item):
            raise ValueError("bad data")

        notifier = RecordingNotifier()
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=notifier,
            enrichers=[explode],
        )

        assert report.errors["enrich:yad2:1"] == "ValueError: bad data"
        assert len(report.listings) == 1, "the listing is kept, partially enriched"
        assert report.notified == 1, "it still flows through filtering and alerts"

    def test_only_the_first_enrich_error_is_recorded_per_listing(self, tmp_path):
        def explode_a(item):
            raise ValueError("first")

        def explode_b(item):
            raise ValueError("second")

        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=RecordingNotifier(),
            enrichers=[explode_a, explode_b],
        )

        assert report.errors["enrich:yad2:1"] == "ValueError: first"


class TestCadenceGating:
    class RefusingGate:
        def is_due(self, source, cadence_hours, now):
            return False

        def mark_ran(self, source, now):
            raise AssertionError("mark_ran must not be called on a gate-skip")

    class RecordingGate:
        def __init__(self, due=True):
            self.due = due
            self.marked = []

        def is_due(self, source, cadence_hours, now):
            return self.due

        def mark_ran(self, source, now):
            self.marked.append(source)

    def test_a_gated_out_source_is_neither_fetched_nor_recorded(self, tmp_path):
        store = StateStore(tmp_path)

        class ExplodingIfFetched:
            name = "onmap"

            def fetch(self, fetcher, config, since):
                raise AssertionError("fetch must not run when the source is gated out")

        report = run_pipeline(
            adapters=[ExplodingIfFetched()],
            fetcher=None,
            sources_config={"onmap": {"enabled": True, "cadence_hours": 1}},
            filters=Filters(),
            store=store,
            notifier=RecordingNotifier(),
            gate=self.RefusingGate(),
        )

        assert report.fetched == 0
        assert report.errors == {}
        assert HealthTracker(store).report() == {}

    def test_a_gated_out_source_does_not_count_as_errored(self, tmp_path):
        # A source that simply hasn't reached its cadence yet is not a
        # failure; should_build_portal must not treat it as one.
        store = StateStore(tmp_path)
        report = run_pipeline(
            adapters=[StubAdapter("onmap", [listing(source_id="1", source="onmap")])],
            fetcher=None,
            sources_config={"onmap": {"enabled": True, "cadence_hours": 1}},
            filters=Filters(),
            store=store,
            notifier=RecordingNotifier(),
            gate=self.RefusingGate(),
        )
        assert "onmap" not in report.errors

    def test_a_due_source_runs_and_marks_ran_on_success(self, tmp_path):
        gate = self.RecordingGate(due=True)
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True, "cadence_hours": 1}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=RecordingNotifier(),
            gate=gate,
        )
        assert report.fetched == 1
        assert gate.marked == ["yad2"]

    def test_an_error_result_still_marks_ran(self, tmp_path):
        # A source that returns an error must not be retried faster than its
        # cadence just because it failed.
        gate = self.RecordingGate(due=True)
        report = run_pipeline(
            adapters=[StubAdapter("yad2", error="blocked")],
            fetcher=None,
            sources_config={"yad2": {"enabled": True, "cadence_hours": 1}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=RecordingNotifier(),
            gate=gate,
        )
        assert "yad2" in report.errors
        assert gate.marked == ["yad2"]

    def test_a_raised_exception_still_marks_ran(self, tmp_path):
        # The fetch WAS attempted; a source that raises (rather than
        # politely returning an error result) must not be retried faster
        # than its cadence either.
        class Exploding:
            name = "bad"

            def fetch(self, fetcher, config, since):
                raise RuntimeError("kaboom")

        gate = self.RecordingGate(due=True)
        report = run_pipeline(
            adapters=[Exploding()],
            fetcher=None,
            sources_config={"bad": {"enabled": True, "cadence_hours": 1}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=RecordingNotifier(),
            gate=gate,
        )
        assert "bad" in report.errors
        assert gate.marked == ["bad"]

    def test_a_source_without_a_cadence_always_runs_when_a_gate_is_present(
        self, tmp_path
    ):
        gate = self.RecordingGate(due=False)
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=RecordingNotifier(),
            gate=gate,
        )
        assert report.fetched == 1

    def test_no_gate_means_no_gating_at_all(self, tmp_path):
        report = run_pipeline(
            adapters=[StubAdapter("yad2", [listing()])],
            fetcher=None,
            sources_config={"yad2": {"enabled": True, "cadence_hours": 1}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=RecordingNotifier(),
        )
        assert report.fetched == 1


class TestPortalCarryForward:
    class SelectiveGate:
        """Refuses only the named sources; everything else is due."""

        def __init__(self, refuse=()):
            self.refuse = set(refuse)

        def is_due(self, source, cadence_hours, now):
            return source not in self.refuse

        def mark_ran(self, source, now):
            pass

    SOURCES = {
        "yad2": {"enabled": True, "cadence_hours": 1},
        "fb_marketplace": {"enabled": True, "cadence_hours": 6},
    }

    def _fb_listing(self):
        return listing(
            source="fb_marketplace", source_id="f1", url="https://fb/f1"
        )

    def _run(self, adapters, store, notifier, gate, now=None):
        return run_pipeline(
            adapters=adapters,
            fetcher=None,
            sources_config=dict(self.SOURCES),
            filters=Filters(),
            store=store,
            notifier=notifier,
            gate=gate,
            now=now,
        )

    def test_a_cadence_skipped_source_is_restored_from_the_cache(self, tmp_path):
        from datetime import datetime, timezone

        from apt_scout.__main__ import should_build_portal

        store = StateStore(tmp_path)
        first_run = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        second_run = datetime(2026, 8, 31, 11, 0, tzinfo=timezone.utc)

        self._run(
            [StubAdapter("fb_marketplace", [self._fb_listing()])],
            store,
            RecordingNotifier(),
            gate=self.SelectiveGate(),
            now=first_run,
        )

        class ExplodingIfFetched:
            name = "fb_marketplace"

            def fetch(self, fetcher, config, since):
                raise AssertionError("a gated source must not be fetched")

        notifier = RecordingNotifier()
        report = self._run(
            [StubAdapter("yad2", [listing()]), ExplodingIfFetched()],
            store,
            notifier,
            gate=self.SelectiveGate(refuse=["fb_marketplace"]),
            now=second_run,
        )

        # The skipped source's listing is still in the portal's input...
        by_source = {tuple(l.sources): l for l in report.listings}
        assert ("fb_marketplace",) in by_source
        restored = by_source[("fb_marketplace",)]
        assert restored.stable_id() == "fb_marketplace:f1"
        # ...with its enrichment-era first_seen_at intact...
        assert restored.first_seen_at == first_run
        # ...and it counts as neither fetched nor new.
        assert report.fetched == 1
        assert report.new == 1
        assert report.attempted == ["yad2"]
        # It was notified in run 1, so restoring must not re-alert it.
        assert [l.stable_id() for l in notifier.sent] == ["yad2:1"]

        assert should_build_portal(report, self.SOURCES) is True

    def test_an_all_gated_run_does_not_build_the_portal(self, tmp_path):
        from apt_scout.__main__ import should_build_portal

        store = StateStore(tmp_path)
        self._run(
            [
                StubAdapter("yad2", [listing()]),
                StubAdapter("fb_marketplace", [self._fb_listing()]),
            ],
            store,
            RecordingNotifier(),
            gate=self.SelectiveGate(),
        )

        report = self._run(
            [
                StubAdapter("yad2", [listing()]),
                StubAdapter("fb_marketplace", [self._fb_listing()]),
            ],
            store,
            RecordingNotifier(),
            gate=self.SelectiveGate(refuse=["yad2", "fb_marketplace"]),
        )

        assert report.attempted == []
        assert report.fetched == 0
        assert report.errors == {}
        assert should_build_portal(report, self.SOURCES) is False

    def test_a_re_fetched_source_replaces_its_cache_entry(self, tmp_path):
        store = StateStore(tmp_path)

        self._run(
            [StubAdapter("fb_marketplace", [self._fb_listing()])],
            store,
            RecordingNotifier(),
            gate=self.SelectiveGate(),
        )
        # The source runs again with a different listing: the cache entry is
        # replaced, not appended to.
        newer = listing(
            source="fb_marketplace", source_id="f2", url="https://fb/f2"
        )
        self._run(
            [StubAdapter("fb_marketplace", [newer])],
            store,
            RecordingNotifier(),
            gate=self.SelectiveGate(),
        )

        report = self._run(
            [StubAdapter("yad2", [listing()]), StubAdapter("fb_marketplace", [])],
            store,
            RecordingNotifier(),
            gate=self.SelectiveGate(refuse=["fb_marketplace"]),
        )

        fb_ids = {
            l.stable_id()
            for l in report.listings
            if l.sources == ["fb_marketplace"]
        }
        assert fb_ids == {"fb_marketplace:f2"}


class TestClustering:
    def test_two_sources_same_phone_notify_once_with_pooled_fields(self, tmp_path):
        store = StateStore(tmp_path)
        notifier = RecordingNotifier()
        yad2_listing = listing(
            source="yad2",
            source_id="p1",
            raw_text="דירה להשכרה, לפרטים 050-1234567",
            price=None,
        )
        fb_listing = listing(
            source="fb_marketplace",
            source_id="p2",
            url="https://fb/p2",
            raw_text="אותה דירה! התקשרו 050-1234567",
            price=4800,
        )
        report = run_pipeline(
            adapters=[
                StubAdapter("yad2", [yad2_listing]),
                StubAdapter("fb_marketplace", [fb_listing]),
            ],
            fetcher=None,
            sources_config={
                "yad2": {"enabled": True},
                "fb_marketplace": {"enabled": True},
            },
            filters=Filters(),
            store=store,
            notifier=notifier,
            cluster_salt="test-salt",
        )

        assert report.notified == 1
        assert len(notifier.sent) == 1
        sent = notifier.sent[0]
        assert sent.sources == ["yad2", "fb_marketplace"]
        assert sent.price == 4800, "pooled from the member that actually has a price"

        assert store.notified_ids() == {"yad2:p1", "fb_marketplace:p2"}

        assert len(report.listings) == 1
        assert report.listings[0].sources == ["yad2", "fb_marketplace"]

    def test_a_cluster_with_one_previously_notified_member_is_not_re_alerted(
        self, tmp_path
    ):
        store = StateStore(tmp_path)
        store.mark_notified(["yad2:p1"])

        notifier = RecordingNotifier()
        yad2_listing = listing(
            source="yad2",
            source_id="p1",
            raw_text="דירה להשכרה, לפרטים 050-1234567",
        )
        fb_listing = listing(
            source="fb_marketplace",
            source_id="p2",
            url="https://fb/p2",
            raw_text="אותה דירה! התקשרו 050-1234567",
        )
        report = run_pipeline(
            adapters=[
                StubAdapter("yad2", [yad2_listing]),
                StubAdapter("fb_marketplace", [fb_listing]),
            ],
            fetcher=None,
            sources_config={
                "yad2": {"enabled": True},
                "fb_marketplace": {"enabled": True},
            },
            filters=Filters(),
            store=store,
            notifier=notifier,
            cluster_salt="test-salt",
        )

        assert report.notified == 0
        assert notifier.sent == []

    def test_suppression_self_heals_the_whole_clusters_notified_state(
        self, tmp_path
    ):
        # A cluster suppressed because one member (yad2) was already
        # notified must still record the *other* member (fb) as notified.
        # Otherwise, once the yad2 listing expires and drops out of future
        # fetches, the surviving fb listing forms a fresh, unsuppressed
        # cluster and fires a duplicate alert.
        store = StateStore(tmp_path)
        store.mark_notified(["yad2:p1"])

        yad2_listing = listing(
            source="yad2",
            source_id="p1",
            raw_text="דירה להשכרה, לפרטים 050-1234567",
        )
        fb_listing = listing(
            source="fb_marketplace",
            source_id="p2",
            url="https://fb/p2",
            raw_text="אותה דירה! התקשרו 050-1234567",
        )

        notifier = RecordingNotifier()
        report = run_pipeline(
            adapters=[
                StubAdapter("yad2", [yad2_listing]),
                StubAdapter("fb_marketplace", [fb_listing]),
            ],
            fetcher=None,
            sources_config={
                "yad2": {"enabled": True},
                "fb_marketplace": {"enabled": True},
            },
            filters=Filters(),
            store=store,
            notifier=notifier,
            cluster_salt="test-salt",
        )

        assert report.notified == 0
        assert store.notified_ids() == {"yad2:p1", "fb_marketplace:p2"}

        # Now the yad2 source stops re-posting (listing expired) and only
        # fb still advertises it - the surviving member must stay suppressed.
        second_notifier = RecordingNotifier()
        second_report = run_pipeline(
            adapters=[StubAdapter("fb_marketplace", [fb_listing])],
            fetcher=None,
            sources_config={"fb_marketplace": {"enabled": True}},
            filters=Filters(),
            store=store,
            notifier=second_notifier,
            cluster_salt="test-salt",
        )

        assert second_report.notified == 0
        assert second_notifier.sent == []


class TestFloodCap:
    def _singletons(self, count):
        return [
            listing(source_id=str(i), url=f"https://y/{i}") for i in range(count)
        ]

    def test_overflow_beyond_twelve_gets_one_summary_and_retries_next_run(
        self, tmp_path
    ):
        store = StateStore(tmp_path)
        notifier = RecordingNotifier()
        adapters = [StubAdapter("yad2", self._singletons(15))]
        report = run(adapters, store, notifier)

        assert report.notified == 12
        assert len(notifier.sent) == 12
        assert notifier.texts == ["+ עוד 3 דירות תואמות — ראו בפורטל"]
        assert len(store.notified_ids()) == 12

        second_notifier = RecordingNotifier()
        second_report = run(adapters, store, second_notifier)

        assert second_report.notified == 3
        assert len(second_notifier.sent) == 3
        assert second_notifier.texts == []
        assert len(store.notified_ids()) == 15


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
