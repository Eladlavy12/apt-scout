from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apt_scout.fb_groups.browser import VisitResult, records_from_extraction, visit_group

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
FIXTURE = (Path(__file__).parent / "fixtures" / "fb_group_page.html").resolve()


class TestRecordsFromExtraction:
    def test_builds_records_and_drops_orphans(self):
        raw = {"posts": [
            {"post_id": "1", "text": "hello", "time_label": "5 שעות", "photos": ["https://scontent.x/a.jpg"]},
            {"post_id": None, "text": "orphan", "time_label": None, "photos": []},
        ]}
        recs = records_from_extraction(raw, "g", NOW)
        assert [r["post_id"] for r in recs] == ["1"]
        assert recs[0]["url"] == "https://www.facebook.com/groups/g/posts/1/"
        assert recs[0]["posted_at"] == (NOW - timedelta(hours=5)).isoformat()

    def test_tolerates_garbage(self):
        assert records_from_extraction({}, "g", NOW) == []
        assert records_from_extraction({"posts": "nope"}, "g", NOW) == []


def _chrome_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            b.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _chrome_available(), reason="stock Chrome not available for Playwright")
class TestVisitGroupOnFixture:
    def test_extracts_posts_from_the_fixture(self):
        result = visit_group("testgroup", NOW, url=FIXTURE.as_uri(), headless=True)
        assert result.outcome == "ok", result.error
        assert result.title.startswith("דירות בדיקה")
        by_id = {p["post_id"]: p for p in result.posts}
        assert set(by_id) == {"1111", "2222"}
        # "See more" was expanded before the text was read
        assert "כניסה מיידית" in by_id["1111"]["text"]
        assert "052-1234567" in by_id["1111"]["text"]
        assert by_id["1111"]["photos"] == ["https://scontent.xx.fbcdn.net/v/t1.jpg"]
        assert by_id["1111"]["posted_at"] == (NOW - timedelta(hours=5)).isoformat()
        assert by_id["2222"]["posted_at"] == (NOW - timedelta(days=1)).isoformat()

    def test_a_login_redirect_is_reported_as_blocked(self, tmp_path):
        # The file name must not contain "login": that would trip the URL
        # route abort and hide whether the form-marker detection works.
        page = tmp_path / "wall.html"
        page.write_text('<html><body><form action="/login/device-based/regular/login/"><input name="email"></form></body></html>', encoding="utf-8")
        result = visit_group("testgroup", NOW, url=page.as_uri(), headless=True)
        assert result.outcome == "blocked"
        assert result.posts == []

    def test_a_page_without_posts_is_empty(self, tmp_path):
        page = tmp_path / "empty.html"
        page.write_text("<html><body><p>nothing</p></body></html>", encoding="utf-8")
        assert visit_group("testgroup", NOW, url=page.as_uri(), headless=True).outcome == "empty"


def test_visit_never_raises_on_a_bad_url():
    result = visit_group("testgroup", NOW, url="http://127.0.0.1:9/", timeout_ms=3000, headless=True)
    assert result.outcome in ("error", "blocked")
    assert isinstance(result, VisitResult)
