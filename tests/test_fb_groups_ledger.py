from datetime import datetime, timedelta, timezone

from apt_scout.adapters.base import AdapterResult
from apt_scout.fb_groups.groups import Group
from apt_scout.fb_groups.ledger import YieldLedger, format_groups_report
from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy
from apt_scout.pipeline import run_pipeline
from apt_scout.state import StateStore

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
TEXT = "להשכרה דירת 3 חדרים משופצת בפלורנטין, קומה 2, מרפסת שמש, מזגנים בכל החדרים, כניסה מיידית, ללא תיווך, 4,900 ש\"ח"


def fb(group, pid, text=TEXT, **over):
    # price/rooms are set directly: run() passes no enrichers, so nothing
    # would parse them out of the text here.
    base = dict(source="fb_groups", source_id=f"{group}:{pid}", url=f"https://f/{group}/{pid}", raw_text=text, group_id=group,
                price=4900, rooms=3.0, occupancy=Occupancy.WHOLE)
    base.update(over)
    return Listing(**base)


class Stub:
    def __init__(self, name, listings):
        self.name = name; self._listings = listings

    def fetch(self, fetcher, config, since):
        return AdapterResult(source=self.name, listings=self._listings)


class Notifier:
    def send_listing(self, item): return True
    def send_text(self, text): return True


def run(adapters, store, ledger, now=NOW):
    return run_pipeline(adapters=adapters, fetcher=None, sources_config={a.name: {"enabled": True} for a in adapters},
                        filters=Filters(), store=store, notifier=Notifier(), now=now, yield_ledger=ledger)


class TestCounters:
    def test_offer_and_listing_counted_once(self, tmp_path):
        store = StateStore(tmp_path); ledger = YieldLedger(store)
        assert ledger.count_offer("g", "g:1") is True
        assert ledger.count_offer("g", "g:1") is False
        assert ledger.count_listing("g", "g:1") is True
        ledger.save()
        again = YieldLedger(store)
        assert again.count_offer("g", "g:1") is False
        row = again.rows([Group("g", "Name", True)], {"groups": {}})[0]
        assert row["offers"] == 1 and row["listings"] == 1 and row["name"] == "Name"

    def test_id_sets_are_capped(self, tmp_path):
        ledger = YieldLedger(StateStore(tmp_path))
        for i in range(5200):
            ledger.count_offer("g", f"g:{i}")
        ledger.save()
        raw = StateStore(tmp_path).load("fb_groups_yield", {})
        assert len(raw["_offers"]) == 5000
        assert raw["g"]["offers"] == 5200


class TestPipelineHooks:
    def test_match_is_credited_to_the_first_group_only(self, tmp_path):
        store = StateStore(tmp_path)
        ledger = YieldLedger(store)
        run([Stub("fb_groups", [fb("early", "1")])], store, ledger, now=NOW)
        ledger = YieldLedger(store)
        run([Stub("fb_groups", [fb("early", "1"), fb("late", "2")])], store, ledger, now=NOW + timedelta(hours=1))
        rows = {r["id"]: r for r in YieldLedger(store).rows([Group("early", "", True), Group("late", "", True)], {"groups": {}})}
        assert rows["early"]["matched"] == 1
        assert rows["late"]["matched"] == 0
        assert rows["late"]["offers"] == 1

    def test_a_cluster_is_credited_once_across_runs(self, tmp_path):
        store = StateStore(tmp_path)
        for i in range(3):
            run([Stub("fb_groups", [fb("g", "1")])], store, YieldLedger(store), now=NOW + timedelta(hours=i))
        assert YieldLedger(store).rows([Group("g", "", True)], {"groups": {}})[0]["matched"] == 1

    def test_a_yad2_first_cross_post_earns_the_group_nothing(self, tmp_path):
        store = StateStore(tmp_path)
        yad = Listing(source="yad2", source_id="9", url="https://y/9", raw_text=TEXT, price=4900, rooms=3.0, occupancy=Occupancy.WHOLE)
        run([Stub("yad2", [yad])], store, YieldLedger(store), now=NOW)
        run([Stub("yad2", [yad]), Stub("fb_groups", [fb("g", "1")])], store, YieldLedger(store), now=NOW + timedelta(hours=1))
        assert YieldLedger(store).rows([Group("g", "", True)], {"groups": {}})[0]["matched"] == 0

    def test_non_matching_offers_count_as_listings_but_not_matched(self, tmp_path):
        store = StateStore(tmp_path)
        run([Stub("fb_groups", [fb("g", "1", price=9900)])], store, YieldLedger(store))
        row = YieldLedger(store).rows([Group("g", "", True)], {"groups": {}})[0]
        assert row["offers"] == 1 and row["listings"] == 1 and row["matched"] == 0

    def test_pipeline_without_a_ledger_still_runs(self, tmp_path):
        store = StateStore(tmp_path)
        report = run_pipeline(adapters=[Stub("fb_groups", [fb("g", "1")])], fetcher=None, sources_config={"fb_groups": {"enabled": True}},
                              filters=Filters(), store=store, notifier=Notifier(), now=NOW)
        assert report.matched == 1


class TestRows:
    def test_merges_rotation_counters_and_sorts(self, tmp_path):
        ledger = YieldLedger(StateStore(tmp_path))
        ledger.count_offer("b", "b:1"); ledger.count_listing("b", "b:1"); ledger.credit_match("c1", "b", NOW)
        rotation = {"groups": {"a": {"visits": 4, "blocked": 1, "posts_seen": 9, "last_visit": NOW.isoformat(), "name": "From title"}}}
        rows = ledger.rows([Group("a", "", True), Group("b", "B", False)], rotation)
        assert [r["id"] for r in rows] == ["b", "a"]
        assert rows[1]["visits"] == 4 and rows[1]["name"] == "From title" and rows[1]["posts_seen"] == 9
        assert rows[0]["last_matched_at"] == NOW.isoformat() and rows[0]["enabled"] is False

    def test_report_text(self, tmp_path):
        ledger = YieldLedger(StateStore(tmp_path))
        text = format_groups_report(ledger.rows([Group("a", "קבוצה א", True)], {"groups": {}}), NOW + timedelta(hours=1))
        assert "קבוצה א" in text and "חסום עד" in text
