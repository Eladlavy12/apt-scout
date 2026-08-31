import json

from apt_scout.filters import Filters
from apt_scout.notify.commands import apply_command, parse_command, process_commands
from apt_scout.state import StateStore


class TestParsing:
    def test_parses_a_command_with_arguments(self):
        assert parse_command("/price 4000 6000") == ("price", ["4000", "6000"])

    def test_parses_a_bare_command(self):
        assert parse_command("/status") == ("status", [])

    def test_strips_a_bot_mention(self):
        assert parse_command("/status@AptScoutBot") == ("status", [])

    def test_ignores_ordinary_messages(self):
        assert parse_command("hello there") is None
        assert parse_command("") is None
        assert parse_command(None) is None


class TestApplying:
    def test_price_sets_both_bounds(self):
        updated, reply = apply_command(Filters(), "price", ["4000", "6000"])
        assert updated.min_price == 4000
        assert updated.max_price == 6000
        assert "4,000" in reply or "4000" in reply

    def test_radius_sets_the_drive_time(self):
        updated, _ = apply_command(Filters(), "radius", ["25"])
        assert updated.max_drive_minutes == 25

    def test_rooms_sets_the_minimum(self):
        updated, _ = apply_command(Filters(), "rooms", ["3"])
        assert updated.min_rooms == 3

    def test_size_sets_the_minimum(self):
        updated, _ = apply_command(Filters(), "size", ["60"])
        assert updated.min_size_sqm == 60

    def test_pause_and_resume_toggle_alerting(self):
        paused, _ = apply_command(Filters(), "pause", [])
        assert paused.paused is True
        resumed, _ = apply_command(paused, "resume", [])
        assert resumed.paused is False

    def test_status_reports_without_changing_anything(self):
        original = Filters()
        updated, reply = apply_command(original, "status", [])
        assert updated.to_dict() == original.to_dict()
        assert "4000" in reply or "4,000" in reply

    def test_bad_arguments_explain_the_usage_and_change_nothing(self):
        original = Filters()
        updated, reply = apply_command(original, "price", ["abc"])
        assert updated.to_dict() == original.to_dict()
        assert "/price" in reply

    def test_missing_arguments_explain_the_usage(self):
        updated, reply = apply_command(Filters(), "price", ["4000"])
        assert updated.max_price == Filters().max_price
        assert "/price" in reply

    def test_an_unknown_command_lists_what_is_available(self):
        _, reply = apply_command(Filters(), "teleport", [])
        assert "/price" in reply and "/radius" in reply


class TestPausedFiltersRejectEverything:
    def test_paused_blocks_all_alerts(self):
        from apt_scout.models import Listing, Occupancy

        listing = Listing(
            source="yad2",
            source_id="1",
            url="https://y/1",
            price=4800,
            rooms=3.0,
            size_sqm=70.0,
            occupancy=Occupancy.WHOLE,
        )
        assert Filters().matches(listing) is True
        assert Filters(paused=True).matches(listing) is False


class FakeNotifier:
    def __init__(self, updates):
        self._updates = updates
        self.replies = []
        self.offsets = []

    def get_updates(self, offset=None):
        self.offsets.append(offset)
        return self._updates

    def send_text(self, text):
        self.replies.append(text)
        return True


def update(update_id, text):
    return {"update_id": update_id, "message": {"text": text}}


class TestProcessing:
    def test_applies_a_command_and_persists_it(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "/radius 25")])

        result = process_commands(notifier, StateStore(tmp_path), Filters(), path)

        assert result.max_drive_minutes == 25
        assert json.loads(path.read_text("utf-8"))["max_drive_minutes"] == 25
        assert notifier.replies, "the user must get confirmation"

    def test_remembers_the_offset_so_commands_run_once(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        store = StateStore(tmp_path)
        process_commands(FakeNotifier([update(7, "/radius 25")]), store, Filters(), path)

        second = FakeNotifier([])
        process_commands(second, store, Filters(), path)

        assert second.offsets == [8], "must ask only for updates after the last one"

    def test_applies_several_commands_in_order(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "/radius 20"), update(2, "/radius 30")])

        result = process_commands(notifier, StateStore(tmp_path), Filters(), path)

        assert result.max_drive_minutes == 30

    def test_non_command_messages_are_ignored_silently(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "good morning")])

        process_commands(notifier, StateStore(tmp_path), Filters(), path)

        assert notifier.replies == []

    def test_a_polling_failure_leaves_filters_untouched(self, tmp_path):
        class Broken:
            def get_updates(self, offset=None):
                raise RuntimeError("telegram down")

            def send_text(self, text):
                return True

        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")

        result = process_commands(Broken(), StateStore(tmp_path), Filters(), path)

        assert result.to_dict() == Filters().to_dict()
