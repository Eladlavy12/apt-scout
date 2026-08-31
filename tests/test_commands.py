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


CHAT_ID = "111"


def update(update_id, text, chat_id=111):
    return {
        "update_id": update_id,
        "message": {"text": text, "chat": {"id": chat_id}},
    }


class TestProcessing:
    def test_applies_a_command_and_persists_it(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "/radius 25")])

        result = process_commands(notifier, StateStore(tmp_path), Filters(), path, chat_id=CHAT_ID)

        assert result.max_drive_minutes == 25
        assert json.loads(path.read_text("utf-8"))["max_drive_minutes"] == 25
        assert notifier.replies, "the user must get confirmation"

    def test_remembers_the_offset_so_commands_run_once(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        store = StateStore(tmp_path)
        process_commands(FakeNotifier([update(7, "/radius 25")]), store, Filters(), path, chat_id=CHAT_ID)

        second = FakeNotifier([])
        process_commands(second, store, Filters(), path, chat_id=CHAT_ID)

        assert second.offsets == [8], "must ask only for updates after the last one"

    def test_applies_several_commands_in_order(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "/radius 20"), update(2, "/radius 30")])

        result = process_commands(notifier, StateStore(tmp_path), Filters(), path, chat_id=CHAT_ID)

        assert result.max_drive_minutes == 30

    def test_non_command_messages_are_ignored_silently(self, tmp_path):
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "good morning")])

        process_commands(notifier, StateStore(tmp_path), Filters(), path, chat_id=CHAT_ID)

        assert notifier.replies == []

    def test_a_polling_failure_leaves_filters_untouched(self, tmp_path):
        class Broken:
            def get_updates(self, offset=None):
                raise RuntimeError("telegram down")

            def send_text(self, text):
                return True

        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")

        result = process_commands(Broken(), StateStore(tmp_path), Filters(), path, chat_id=CHAT_ID)

        assert result.to_dict() == Filters().to_dict()

    def test_status_does_not_rewrite_the_config_file(self, tmp_path):
        path = tmp_path / "filters.json"
        original = json.dumps(Filters().to_dict())
        path.write_text(original, encoding="utf-8")
        notifier = FakeNotifier([update(1, "/status")])

        process_commands(notifier, StateStore(tmp_path), Filters(), path, chat_id=CHAT_ID)

        assert path.read_text("utf-8") == original, "no-op command must not touch the file"
        assert notifier.replies, "status must still get a reply"

    def test_invalid_command_does_not_rewrite_the_config_file(self, tmp_path):
        path = tmp_path / "filters.json"
        original = json.dumps(Filters().to_dict())
        path.write_text(original, encoding="utf-8")
        notifier = FakeNotifier([update(1, "/price abc")])

        process_commands(notifier, StateStore(tmp_path), Filters(), path, chat_id=CHAT_ID)

        assert path.read_text("utf-8") == original

    def test_a_command_from_a_foreign_chat_is_ignored_entirely(self, tmp_path):
        # Anyone on Telegram can message the bot; only the configured chat may
        # reconfigure the alerts. No reply either — silence gives strangers
        # nothing to probe. The offset still advances so the foreign update is
        # not re-fetched on every run.
        path = tmp_path / "filters.json"
        original = json.dumps(Filters().to_dict())
        path.write_text(original, encoding="utf-8")
        store = StateStore(tmp_path)
        notifier = FakeNotifier([update(5, "/radius 25", chat_id=999)])

        result = process_commands(notifier, store, Filters(), path, chat_id=CHAT_ID)

        assert result.to_dict() == Filters().to_dict()
        assert notifier.replies == []
        assert path.read_text("utf-8") == original
        assert store.load("telegram_offset", None) == 6

    def test_a_matching_chat_id_may_arrive_as_an_int(self, tmp_path):
        # Telegram sends chat ids as integers; the configured id is an env
        # string. The comparison must not care.
        path = tmp_path / "filters.json"
        path.write_text(json.dumps(Filters().to_dict()), encoding="utf-8")
        notifier = FakeNotifier([update(1, "/radius 25", chat_id=111)])

        result = process_commands(
            notifier, StateStore(tmp_path), Filters(), path, chat_id="111"
        )

        assert result.max_drive_minutes == 25
