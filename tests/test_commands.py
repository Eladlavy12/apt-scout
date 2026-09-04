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

    def test_km_sets_the_max_distance(self):
        updated, _ = apply_command(Filters(), "km", ["8"])
        assert updated.max_distance_km == 8

    def test_km_bad_arguments_explain_the_usage_and_change_nothing(self):
        original = Filters()
        updated, reply = apply_command(original, "km", ["abc"])
        assert updated.to_dict() == original.to_dict()
        assert "/km" in reply

    def test_rooms_sets_the_minimum(self):
        updated, _ = apply_command(Filters(), "rooms", ["3"])
        assert updated.min_rooms == 3

    def test_size_sets_the_minimum(self):
        updated, _ = apply_command(Filters(), "size", ["60"])
        assert updated.min_size_sqm == 60

    def test_sublets_on_shows_sublets(self):
        updated, reply = apply_command(Filters(), "sublets", ["on"])
        assert updated.exclude_sublets is False
        assert "מוצגים" in reply

    def test_sublets_off_hides_sublets(self):
        updated, reply = apply_command(Filters(exclude_sublets=False), "sublets", ["off"])
        assert updated.exclude_sublets is True
        assert "מוסתרים" in reply

    def test_sublets_bad_arguments_explain_the_usage_and_change_nothing(self):
        original = Filters()
        updated, reply = apply_command(original, "sublets", ["maybe"])
        assert updated.to_dict() == original.to_dict()
        assert "/sublets" in reply

    def test_sublets_missing_arguments_explain_the_usage(self):
        original = Filters()
        updated, reply = apply_command(original, "sublets", [])
        assert updated.to_dict() == original.to_dict()
        assert "/sublets" in reply

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
        assert "/price" in reply and "/radius" in reply and "/km" in reply


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


from apt_scout.neighborhoods.knowledge import KnowledgeBase


def knowledge() -> KnowledgeBase:
    def entry(names, city):
        return {"names": names, "city": city, "reputation": "mixed", "summary": "s",
                "pros": ["a", "b"], "cons": ["c", "d"], "tags": ["noisy"], "sources": ["x"]}

    return KnowledgeBase.from_dict(
        {"florentin": entry(["פלורנטין", "Florentin"], "תל אביב יפו"),
         "hatikva": entry(["התקווה", "HaTikva"], "תל אביב יפו")}
    )


class TestCities:
    def test_sets_the_city_list_from_hebrew_names(self):
        updated, reply = apply_command(Filters(), "cities", ["תל", "אביב,", "גבעתיים"])
        assert updated.cities == ["תל אביב יפו", "גבעתיים"]
        assert "גבעתיים" in reply

    def test_accepts_english_and_odd_spacing(self):
        updated, _ = apply_command(Filters(), "cities", ["Ramat", "Gan", ",", "tel-aviv"])
        assert updated.cities == ["רמת גן", "תל אביב יפו"]

    def test_all_clears_the_restriction(self):
        updated, reply = apply_command(Filters(), "cities", ["all"])
        assert updated.cities == []
        assert "כל הערים" in reply

    def test_unknown_city_changes_nothing_and_lists_the_options(self):
        original = Filters()
        updated, reply = apply_command(original, "cities", ["חולון"])
        assert updated.to_dict() == original.to_dict()
        assert "רמת גן" in reply and "חולון" in reply

    def test_no_arguments_explains_the_usage(self):
        _, reply = apply_command(Filters(), "cities", [])
        assert "/cities" in reply


class TestExcludeInclude:
    def test_exclude_adds_by_any_alias(self):
        updated, reply = apply_command(Filters(), "exclude", ["florentin"], knowledge())
        assert updated.excluded_neighborhoods == ["florentin"]
        assert "פלורנטין" in reply

    def test_exclude_is_idempotent(self):
        once, _ = apply_command(Filters(), "exclude", ["פלורנטין"], knowledge())
        twice, _ = apply_command(once, "exclude", ["פלורנטין"], knowledge())
        assert twice.excluded_neighborhoods == ["florentin"]

    def test_include_removes(self):
        excluded = Filters(excluded_neighborhoods=["florentin", "hatikva"])
        updated, _ = apply_command(excluded, "include", ["התקווה"], knowledge())
        assert updated.excluded_neighborhoods == ["florentin"]

    def test_unknown_name_changes_nothing(self):
        original = Filters()
        updated, reply = apply_command(original, "exclude", ["נרניה"], knowledge())
        assert updated.to_dict() == original.to_dict()
        assert "נרניה" in reply

    def test_without_a_knowledge_base_the_command_is_refused(self):
        original = Filters()
        updated, reply = apply_command(original, "exclude", ["florentin"])
        assert updated.to_dict() == original.to_dict()
        assert reply


class TestStatusShowsNeighborhoods:
    def test_status_lists_cities_and_exclusions(self):
        f = Filters(cities=["גבעתיים"], excluded_neighborhoods=["florentin"])
        _, reply = apply_command(f, "status", [], knowledge())
        assert "גבעתיים" in reply
        assert "פלורנטין" in reply

    def test_status_with_no_restriction(self):
        _, reply = apply_command(Filters(cities=[]), "status", [])
        assert "כל הערים" in reply


def test_process_commands_forwards_the_knowledge_base(tmp_path):
    class Notifier:
        def __init__(self):
            self.sent = []

        def get_updates(self, offset=None):
            return [{"update_id": 1, "message": {"chat": {"id": 7}, "text": "/exclude florentin"}}]

        def send_text(self, text):
            self.sent.append(text)
            return True

    store = StateStore(tmp_path)
    path = tmp_path / "filters.json"
    result = process_commands(Notifier(), store, Filters(), path, chat_id="7", knowledge=knowledge())
    assert result.excluded_neighborhoods == ["florentin"]
    assert json.loads(path.read_text(encoding="utf-8"))["excluded_neighborhoods"] == ["florentin"]
