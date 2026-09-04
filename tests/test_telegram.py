from apt_scout.models import Listing, Occupancy
from apt_scout.notify.telegram import TelegramNotifier, format_listing


class FakeClient:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def post(self, url, json=None):
        self.calls.append((url, json))
        return FakeResponse(self.ok)


class FakeResponse:
    def __init__(self, ok):
        self.status_code = 200 if ok else 500

    def json(self):
        return {"ok": self.status_code == 200}


def listing(**overrides) -> Listing:
    base = dict(
        source="yad2",
        source_id="1",
        url="https://yad2.co.il/item/1",
        price=4800,
        rooms=3.0,
        size_sqm=70.0,
        drive_minutes=11.4,
        distance_km=3.4,
        city="תל אביב",
        address_text="הרצל 10 תל אביב",
        occupancy=Occupancy.WHOLE,
    )
    base.update(overrides)
    return Listing(**base)


class TestFormatting:
    def test_includes_the_key_facts(self):
        text = format_listing(listing())
        assert "4,800" in text
        assert "3" in text
        assert "70" in text
        assert "yad2.co.il/item/1" in text

    def test_shows_drive_time_rounded(self):
        assert "11 " in format_listing(listing()) or "11'" in format_listing(listing())

    def test_shows_distance_when_known(self):
        text = format_listing(listing(distance_km=3.4))
        assert "📍" in text
        assert "3.4" in text

    def test_omits_distance_when_unknown(self):
        text = format_listing(listing(distance_km=None))
        assert "📍" not in text

    def test_marks_missing_price_explicitly(self):
        text = format_listing(listing(price=None))
        assert "?" in text or "לא צוין" in text

    def test_omits_drive_time_when_unknown(self):
        text = format_listing(listing(drive_minutes=None))
        assert "None" not in text

    def test_never_contains_the_word_none(self):
        text = format_listing(
            listing(price=None, rooms=None, size_sqm=None, address_text=None)
        )
        assert "None" not in text

    def test_marks_a_sublet_with_a_prefix_line(self):
        text = format_listing(listing(is_sublet=True))
        assert text.startswith("🔁 סאבלט")

    def test_omits_the_sublet_line_for_an_ordinary_listing(self):
        text = format_listing(listing(is_sublet=False))
        assert "סאבלט" not in text

    def test_escapes_ampersands_in_the_url_for_html_mode(self):
        text = format_listing(listing(url="https://y/item?a=1&b=2"))
        assert "a=1&amp;b=2" in text
        assert "a=1&b=2" not in text


class TestSending:
    def test_sends_a_photo_when_one_exists(self):
        client = FakeClient()
        notifier = TelegramNotifier("TOKEN", "CHAT", client=client)

        assert notifier.send_listing(listing(photos=["https://img/1.jpg"])) is True

        url, payload = client.calls[0]
        assert url.endswith("/sendPhoto")
        assert payload["photo"] == "https://img/1.jpg"
        assert payload["chat_id"] == "CHAT"

    def test_sends_text_when_there_is_no_photo(self):
        client = FakeClient()
        notifier = TelegramNotifier("TOKEN", "CHAT", client=client)

        notifier.send_listing(listing(photos=[]))

        assert client.calls[0][0].endswith("/sendMessage")

    def test_token_is_in_the_url_not_the_payload(self):
        client = FakeClient()
        TelegramNotifier("SECRET", "CHAT", client=client).send_text("hi")
        url, payload = client.calls[0]
        assert "SECRET" in url
        assert "SECRET" not in str(payload)

    def test_falls_back_to_text_when_the_photo_send_fails(self):
        # A dead photo URL makes sendPhoto fail; the alert itself must still
        # arrive as plain text.
        class PhotoRejectingClient(FakeClient):
            def post(self, url, json=None):
                self.calls.append((url, json))
                return FakeResponse(ok=not url.endswith("/sendPhoto"))

        client = PhotoRejectingClient()
        notifier = TelegramNotifier("TOKEN", "CHAT", client=client)

        assert notifier.send_listing(listing(photos=["https://img/1.jpg"])) is True

        endpoints = [url.rsplit("/", 1)[1] for url, _ in client.calls]
        assert endpoints == ["sendPhoto", "sendMessage"]

    def test_returns_false_on_api_failure(self):
        notifier = TelegramNotifier("T", "C", client=FakeClient(ok=False))
        assert notifier.send_listing(listing()) is False

    def test_returns_false_when_the_client_raises(self):
        class Boom:
            def post(self, url, json=None):
                raise RuntimeError("network down")

        notifier = TelegramNotifier("T", "C", client=Boom())
        assert notifier.send_listing(listing()) is False


from apt_scout.neighborhoods.knowledge import KnowledgeBase
from apt_scout.notify.telegram import format_listing


def test_format_adds_a_neighborhood_line_when_resolved():
    from apt_scout.models import Listing

    kb = KnowledgeBase.from_dict(
        {"bavli": {"names": ["בבלי"], "city": "תל אביב יפו", "reputation": "sought_after", "summary": "s",
                   "pros": ["a", "b"], "cons": ["c", "d"], "tags": ["quiet", "green", "expensive"], "sources": ["x"]}}
    )
    item = Listing(source="yad2", source_id="1", url="https://y/1", address_text="בבלי 5", neighborhood="bavli")
    text = format_listing(item, kb)
    assert "🏘 בבלי · מבוקשת מאוד · שקטה, ירוקה" in text


def test_format_without_a_neighborhood_is_unchanged():
    from apt_scout.models import Listing

    item = Listing(source="yad2", source_id="1", url="https://y/1", address_text="בבלי 5")
    assert "🏘" not in format_listing(item, None)
