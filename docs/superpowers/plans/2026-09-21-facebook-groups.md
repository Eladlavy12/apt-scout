# Facebook Groups Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest posts from 17 public Facebook rental groups through an anonymous headed Chrome on the user's PC, feed them to the cloud pipeline as a new `fb_groups` source with cross-group dedup, and keep a per-group yield ledger surfaced in the portal and Telegram.

**Architecture:** A PC-side collector (`apt_scout.fb_groups`) rotates through groups with rate-limit backoff and writes provider-agnostic post records to `state/feeds/facebook_groups.json` plus its own counters to `state/fb_groups_rotation.json`. The cloud adapter turns posts into listings (seeker posts dropped), a new text-hash strong fingerprint merges cross-posts, and the pipeline credits matches to the first group that carried an apartment in `state/fb_groups_yield.json`. One writer per state file.

**Tech Stack:** Python 3.11+, playwright (`channel="chrome"`, headed, off-screen), pytest; vanilla DOM-only JS in the portal; PowerShell 5.1 scheduled task.

Spec: `docs/superpowers/specs/2026-09-21-facebook-groups-design.md`.

## Global Constraints

- Dependencies stay `httpx>=0.27`, `beautifulsoup4>=4.12` (+ optional `playwright`); no new packages.
- Adapters and enrichers never raise; the collector never raises past one group; missing values are `None`; filters fail open on unknown values.
- Never store an author name, profile link or avatar; phones only as salted hashes; `PUBLIC_FIELDS` is the only path to the portal; portal JS is DOM-only (no `innerHTML`), URLs through `safeHttpUrl`.
- Post record fields, exactly: `group_id, post_id, url, text, posted_at, photos, fetched_at`. Feed file: `{"source": "fb_groups", "fetched_at": iso, "posts": [...]}`.
- Rotation file `state/fb_groups_rotation.json` (PC-owned): `{"groups": {id: {"last_visit", "last_outcome", "visits", "blocked", "posts_seen"}}, "blocked_until", "backoff_hours"}`. Yield file `state/fb_groups_yield.json` (cloud-owned): `{id: {"offers", "listings", "matched", "last_matched_at"}, "_clusters": [...], "_offers": [...], "_listings": [...]}`.
- Source name `fb_groups`; `Listing.source_id = f"{group_id}:{post_id}"`; new field `Listing.group_id: str | None`.
- Config keys in `config/sources.json` → `fb_groups`: `enabled`, `cadence_hours` 1, `feed_file` `state/feeds/facebook_groups.json`, `feed_max_age_hours` 24, `batch_size` 3, `min_hours_between_visits` 5, `max_post_age_days` 3, `backoff_hours_initial` 1, `backoff_hours_max` 24, `visit_gap_seconds` 20. The recovery probe had not lifted the block after 80 min at planning time; these are the spec's placeholders and Task 10 adjusts them to the measured value.
- The collector must abort navigation to `/login` (never render it: it triggers a Windows passkey prompt) and position the Chrome window off-screen (`--window-position=-32000,-32000`).
- No live Facebook call in any test or on CI.
- Windows dev box: interpreter `C:\Github\Apt-scout\.venv\Scripts\python.exe`, no `python` on PATH, PowerShell 5.1 (no `&&`), never print Hebrew to the console (cp1252). Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## File Structure

| Path | Responsibility |
|---|---|
| `config/facebook_groups.json` | the 17 groups (create) |
| `src/apt_scout/fb_groups/__init__.py` | package (create, empty) |
| `src/apt_scout/fb_groups/groups.py` | `Group`, `load_groups()` (create) |
| `src/apt_scout/fb_groups/posts.py` | `parse_relative_time()`, `Post` record helpers, `merge_feed()`, `read_feed()`, `write_feed()` (create) |
| `src/apt_scout/fb_groups/rotation.py` | `Rotation` state: pick, record, backoff (create) |
| `src/apt_scout/fb_groups/browser.py` | `visit_group()` with Playwright + `EXTRACT_JS` (create) |
| `src/apt_scout/fb_groups/collect.py` | `run_collection()` orchestration (create) |
| `src/apt_scout/fb_groups/__main__.py` | CLI (create) |
| `src/apt_scout/fb_groups/ledger.py` | `YieldLedger` (cloud side) + `ledger_rows()` merge view (create) |
| `src/apt_scout/enrich/seeker.py` | `is_seeker_text()` (create) |
| `src/apt_scout/adapters/fb_groups.py` | `FbGroupsAdapter` (create) |
| `src/apt_scout/cluster/fingerprints.py` | `texthash:` strong key (modify) |
| `src/apt_scout/models.py`, `portal/builder.py` | `group_id` field + `PUBLIC_FIELDS` + `data/groups.json` (modify) |
| `src/apt_scout/pipeline.py` | yield ledger hooks (modify) |
| `src/apt_scout/notify/commands.py`, `notify/telegram.py` | `/groups`, group line (modify) |
| `src/apt_scout/__main__.py` | wiring (modify) |
| `src/apt_scout/portal/assets/{app.js,index.html,style.css}` | badge, footer table (modify) |
| `scripts/local_yad2_feed.ps1`, `scripts/fb_groups_smoke.py`, `README.md` | (modify/create) |
| `tests/test_fb_groups_*.py`, `tests/fixtures/fb_group_page.html` | tests (create) |

---

### Task 1: Groups config, post records, relative time, feed merge

**Files:**
- Create: `config/facebook_groups.json`, `src/apt_scout/fb_groups/__init__.py`, `src/apt_scout/fb_groups/groups.py`, `src/apt_scout/fb_groups/posts.py`
- Test: `tests/test_fb_groups_posts.py`

**Interfaces (produced):**
- `groups.py`: `@dataclass(frozen=True) Group(id: str, name: str, enabled: bool)`; `load_groups(path: Path) -> list[Group]` (raises `ValueError` on a malformed file; ids unique); `group_url(group_id) -> str` = `https://www.facebook.com/groups/{id}/`.
- `posts.py`: `parse_relative_time(label: str | None, now: datetime) -> datetime | None`; `post_record(group_id, post_id, text, relative_time, photos, now) -> dict` (builds the spec record; `url` = `https://www.facebook.com/groups/{group_id}/posts/{post_id}/`); `read_feed(path) -> dict | None` (None when missing/invalid/wrong source); `merge_feed(existing_posts: list[dict], new_posts: list[dict], now: datetime, max_age_days: float, group_ids: set[str]) -> list[dict]`; `write_feed(path: Path, posts: list[dict], now: datetime) -> None` (atomic tmp + `os.replace`, `sort_keys=True`, `ensure_ascii=False`, indent 2).

- [ ] **Step 1: Write the failing tests**

`tests/test_fb_groups_posts.py`:

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apt_scout.fb_groups.groups import Group, group_url, load_groups
from apt_scout.fb_groups.posts import (
    merge_feed,
    parse_relative_time,
    post_record,
    read_feed,
    write_feed,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


class TestGroups:
    def test_loads_the_committed_config(self):
        groups = load_groups(Path("config/facebook_groups.json"))
        ids = [g.id for g in groups]
        assert len(ids) == 17
        assert len(set(ids)) == 17
        assert "ApartmentsTelAviv" in ids
        assert "101875683484689" in ids
        assert all(isinstance(g, Group) for g in groups)

    def test_rejects_duplicate_ids(self, tmp_path):
        path = tmp_path / "g.json"
        path.write_text(json.dumps({"groups": [{"id": "a", "name": "", "enabled": True}, {"id": "a", "name": "", "enabled": True}]}), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate"):
            load_groups(path)

    def test_group_url(self):
        assert group_url("tlvrent") == "https://www.facebook.com/groups/tlvrent/"


@pytest.mark.parametrize(
    "label, expected",
    [
        ("5 שעות", NOW - timedelta(hours=5)),
        ("שעה", NOW - timedelta(hours=1)),
        ("12 דקות", NOW - timedelta(minutes=12)),
        ("דקה", NOW - timedelta(minutes=1)),
        ("אתמול ב-14:30", NOW - timedelta(days=1)),
        ("3 ימים", NOW - timedelta(days=3)),
        ("יום", NOW - timedelta(days=1)),
        ("5h", NOW - timedelta(hours=5)),
        ("2d", NOW - timedelta(days=2)),
        ("Yesterday at 3:15 PM", NOW - timedelta(days=1)),
        ("Just now", NOW),
        ("עכשיו", NOW),
    ],
)
def test_relative_time(label, expected):
    assert parse_relative_time(label, NOW) == expected


@pytest.mark.parametrize("label", [None, "", "September 3", "3 בספטמבר", "garbage"])
def test_relative_time_unknown_is_none(label):
    assert parse_relative_time(label, NOW) is None


class TestPostRecord:
    def test_builds_the_spec_record(self):
        rec = post_record("tlvrent", "123", " דירה \n\n יפה ", "5 שעות", ["https://scontent.x/a.jpg"], NOW)
        assert rec == {
            "group_id": "tlvrent",
            "post_id": "123",
            "url": "https://www.facebook.com/groups/tlvrent/posts/123/",
            "text": "דירה \n\n יפה",
            "posted_at": (NOW - timedelta(hours=5)).isoformat(),
            "photos": ["https://scontent.x/a.jpg"],
            "fetched_at": NOW.isoformat(),
        }

    def test_unknown_time_is_null(self):
        assert post_record("g", "1", "x", None, [], NOW)["posted_at"] is None


class TestMergeFeed:
    def _post(self, group, pid, fetched, text="t", posted=None):
        return {"group_id": group, "post_id": pid, "url": f"https://www.facebook.com/groups/{group}/posts/{pid}/",
                "text": text, "posted_at": posted, "photos": [], "fetched_at": fetched.isoformat()}

    def test_upserts_by_group_and_post_id(self):
        old = self._post("g", "1", NOW - timedelta(hours=6), text="old")
        new = self._post("g", "1", NOW, text="new")
        merged = merge_feed([old], [new], NOW, 3, {"g"})
        assert [p["text"] for p in merged] == ["new"]

    def test_keeps_the_newer_fetch_when_old_arrives_late(self):
        newer = self._post("g", "1", NOW, text="new")
        older = self._post("g", "1", NOW - timedelta(hours=1), text="old")
        assert merge_feed([newer], [older], NOW, 3, {"g"})[0]["text"] == "new"

    def test_drops_posts_older_than_the_window(self):
        stale = self._post("g", "1", NOW - timedelta(days=1), posted=(NOW - timedelta(days=4)).isoformat())
        fresh = self._post("g", "2", NOW - timedelta(days=1), posted=(NOW - timedelta(days=2)).isoformat())
        assert [p["post_id"] for p in merge_feed([stale, fresh], [], NOW, 3, {"g"})] == ["2"]

    def test_posts_without_posted_at_age_by_fetched_at(self):
        stale = self._post("g", "1", NOW - timedelta(days=4))
        assert merge_feed([stale], [], NOW, 3, {"g"}) == []

    def test_drops_posts_from_removed_groups(self):
        assert merge_feed([self._post("gone", "1", NOW)], [], NOW, 3, {"g"}) == []

    def test_sorted_newest_first(self):
        a = self._post("g", "a", NOW, posted=(NOW - timedelta(hours=9)).isoformat())
        b = self._post("g", "b", NOW, posted=(NOW - timedelta(hours=1)).isoformat())
        assert [p["post_id"] for p in merge_feed([], [a, b], NOW, 3, {"g"})] == ["b", "a"]


class TestFeedFile:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "feeds" / "facebook_groups.json"
        write_feed(path, [{"group_id": "g", "post_id": "1", "url": "u", "text": "t", "posted_at": None, "photos": [], "fetched_at": NOW.isoformat()}], NOW)
        data = read_feed(path)
        assert data["source"] == "fb_groups"
        assert data["fetched_at"] == NOW.isoformat()
        assert data["posts"][0]["post_id"] == "1"
        assert not path.with_suffix(".json.tmp").exists()

    def test_missing_or_foreign_file_is_none(self, tmp_path):
        assert read_feed(tmp_path / "nope.json") is None
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"source": "yad2", "posts": []}), encoding="utf-8")
        assert read_feed(bad) is None
        bad.write_text("{not json", encoding="utf-8")
        assert read_feed(bad) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fb_groups_posts.py -q`
Expected: `ModuleNotFoundError: No module named 'apt_scout.fb_groups'`.

- [ ] **Step 3: Write the config**

The user's two lists contain 17 unique ids (three appear twice). `config/facebook_groups.json`; names may stay `""` (the collector records the page title in the rotation file on first visit):

```json
{
  "groups": [
    {"id": "ApartmentsTelAviv", "name": "דירות להשכרה ריקות או שותפים בתל אביב", "enabled": true},
    {"id": "101875683484689", "name": "דירות מפה לאוזן בתל אביב", "enabled": true},
    {"id": "333022240594651", "name": "דירות להשכרה במחירים שפויים תל אביב", "enabled": true},
    {"id": "295395253832427", "name": "", "enabled": true},
    {"id": "184920528370332", "name": "", "enabled": true},
    {"id": "458499457501175", "name": "", "enabled": true},
    {"id": "tel.aviv.dirot", "name": "", "enabled": true},
    {"id": "340827733093253", "name": "", "enabled": true},
    {"id": "457465901082882", "name": "", "enabled": true},
    {"id": "664805529032361", "name": "", "enabled": true},
    {"id": "305724686290054", "name": "", "enabled": true},
    {"id": "tlvapartment", "name": "", "enabled": true},
    {"id": "telavivrentals", "name": "", "enabled": true},
    {"id": "291753646078748", "name": "", "enabled": true},
    {"id": "tlvrent", "name": "", "enabled": true},
    {"id": "nadlan247", "name": "", "enabled": true},
    {"id": "1196843027043598", "name": "", "enabled": true}
  ]
}
```

- [ ] **Step 4: Implement `groups.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

GROUP_URL = "https://www.facebook.com/groups/{group_id}/"


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    enabled: bool


def group_url(group_id: str) -> str:
    return GROUP_URL.format(group_id=group_id)


def load_groups(path: Path) -> list[Group]:
    """Read config/facebook_groups.json. Malformed input is a ValueError:
    this file is hand-edited and a silent skip would hide a typo."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw.get("groups") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ValueError("facebook_groups.json must have a 'groups' list")
    groups: list[Group] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip():
            raise ValueError(f"bad group entry: {entry!r}")
        gid = entry["id"].strip()
        if gid in seen:
            raise ValueError(f"duplicate group id: {gid}")
        seen.add(gid)
        groups.append(Group(id=gid, name=str(entry.get("name") or ""), enabled=bool(entry.get("enabled", True))))
    return groups
```

- [ ] **Step 5: Implement `posts.py`**

```python
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..normalise.text import normalise_text

POST_URL = "https://www.facebook.com/groups/{group_id}/posts/{post_id}/"
SOURCE = "fb_groups"

# Facebook shows a relative label ("5 שעות", "3d", "Yesterday at 3:15 PM");
# the exact minute is not needed, only the age for the freshness window.
_NUMBER_UNIT = re.compile(
    r"^(?P<n>\d+)?\s*(?P<unit>דק|שע|ימים|יום|m|h|d|min|hr|hour|day)",
    re.IGNORECASE,
)


def parse_relative_time(label: str | None, now: datetime) -> datetime | None:
    if not label:
        return None
    text = normalise_text(label).lower().strip()
    if text in ("עכשיו", "just now", "now") or text.startswith("just now"):
        return now
    if text.startswith("אתמול") or text.startswith("yesterday"):
        return now - timedelta(days=1)
    if text in ("שעה", "שעה אחת"):
        return now - timedelta(hours=1)
    if text in ("דקה", "דקה אחת"):
        return now - timedelta(minutes=1)
    if text in ("יום", "יום אחד"):
        return now - timedelta(days=1)
    match = _NUMBER_UNIT.match(text)
    if not match or match.group("n") is None:
        return None
    count = int(match.group("n"))
    unit = match.group("unit")
    if unit.startswith(("דק", "m")):
        return now - timedelta(minutes=count)
    if unit.startswith(("שע", "h")):
        return now - timedelta(hours=count)
    return now - timedelta(days=count)


def post_record(group_id, post_id, text, relative_time, photos, now) -> dict:
    posted = parse_relative_time(relative_time, now)
    return {
        "group_id": group_id,
        "post_id": str(post_id),
        "url": POST_URL.format(group_id=group_id, post_id=post_id),
        "text": (text or "").strip(),
        "posted_at": posted.isoformat() if posted else None,
        "photos": [p for p in (photos or []) if isinstance(p, str)],
        "fetched_at": now.isoformat(),
    }


def _when(post: dict) -> datetime | None:
    for key in ("posted_at", "fetched_at"):
        raw = post.get(key)
        if isinstance(raw, str):
            try:
                value = datetime.fromisoformat(raw)
            except ValueError:
                continue
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def merge_feed(existing_posts, new_posts, now, max_age_days, group_ids) -> list[dict]:
    """Upsert new posts over the existing window; drop old and orphaned ones."""
    by_key: dict[tuple[str, str], dict] = {}
    for post in list(existing_posts) + list(new_posts):
        if not isinstance(post, dict):
            continue
        key = (str(post.get("group_id")), str(post.get("post_id")))
        current = by_key.get(key)
        if current is None or str(post.get("fetched_at") or "") >= str(current.get("fetched_at") or ""):
            by_key[key] = post
    cutoff = now - timedelta(days=max_age_days)
    kept = [
        post for post in by_key.values()
        if post.get("group_id") in group_ids and (_when(post) or cutoff) >= cutoff
    ]
    kept.sort(key=lambda p: (_when(p) or cutoff).isoformat(), reverse=True)
    return kept


def read_feed(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("source") != SOURCE or not isinstance(raw.get("posts"), list):
        return None
    return raw


def write_feed(path: Path, posts: list[dict], now: datetime) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"source": SOURCE, "fetched_at": now.isoformat(), "posts": posts},
                   ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)
```

Note on `_when`: a post with neither timestamp parses as `cutoff` and is kept; the test `test_posts_without_posted_at_age_by_fetched_at` relies on `fetched_at` being present, which the collector always sets.

- [ ] **Step 6: Run tests, then commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fb_groups_posts.py -q`
Expected: all pass.

```bash
git add config/facebook_groups.json src/apt_scout/fb_groups tests/test_fb_groups_posts.py
git commit -m "feat: Facebook groups config, post records and feed merge

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Rotation and backoff state

**Files:**
- Create: `src/apt_scout/fb_groups/rotation.py`
- Test: `tests/test_fb_groups_rotation.py`

**Interfaces (produced):**
- `class Rotation`: `__init__(self, path: Path)` loads or starts empty; `is_blocked(now) -> bool`; `blocked_until -> datetime | None`; `pick(groups: list[Group], now, batch_size: int, min_gap_hours: float) -> list[Group]` (enabled, not visited within the gap, least-recent first, never-visited first); `record(group_id, outcome: str, posts_seen: int, now)` (outcome in `ok|blocked|error|empty`; increments `visits`, `blocked` when blocked, `posts_seen`); `note_block(now, initial_hours, max_hours)` (sets `blocked_until = now + backoff_hours` using the current `backoff_hours` (default initial), then doubles it capped); `note_ok(initial_hours)` (resets `backoff_hours`, clears `blocked_until`); `save()`; `group_state(group_id) -> dict`; `data -> dict` (the raw state, for the ledger view).

- [ ] **Step 1: Write the failing tests**

```python
import json
from datetime import datetime, timedelta, timezone

from apt_scout.fb_groups.groups import Group
from apt_scout.fb_groups.rotation import Rotation

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
G = [Group("a", "", True), Group("b", "", True), Group("c", "", False), Group("d", "", True)]


def rot(tmp_path):
    return Rotation(tmp_path / "rot.json")


class TestPick:
    def test_never_visited_first_then_least_recent(self, tmp_path):
        r = rot(tmp_path)
        r.record("a", "ok", 3, NOW - timedelta(hours=10))
        r.record("b", "ok", 3, NOW - timedelta(hours=20))
        picked = [g.id for g in r.pick(G, NOW, batch_size=3, min_gap_hours=5)]
        assert picked == ["d", "b", "a"]

    def test_respects_the_minimum_gap_and_batch_size(self, tmp_path):
        r = rot(tmp_path)
        r.record("a", "ok", 1, NOW - timedelta(hours=1))
        picked = [g.id for g in r.pick(G, NOW, batch_size=1, min_gap_hours=5)]
        assert picked == ["b"]

    def test_skips_disabled_groups(self, tmp_path):
        assert "c" not in [g.id for g in rot(tmp_path).pick(G, NOW, 10, 5)]


class TestBackoff:
    def test_block_sets_blocked_until_and_doubles(self, tmp_path):
        r = rot(tmp_path)
        r.note_block(NOW, initial_hours=1, max_hours=24)
        assert r.blocked_until == NOW + timedelta(hours=1)
        assert r.is_blocked(NOW + timedelta(minutes=30))
        assert not r.is_blocked(NOW + timedelta(hours=2))
        r.note_block(NOW + timedelta(hours=2), initial_hours=1, max_hours=24)
        assert r.blocked_until == NOW + timedelta(hours=4)

    def test_backoff_is_capped(self, tmp_path):
        r = rot(tmp_path)
        for i in range(10):
            r.note_block(NOW + timedelta(days=i), initial_hours=1, max_hours=24)
        assert r.data["backoff_hours"] == 24

    def test_success_resets(self, tmp_path):
        r = rot(tmp_path)
        r.note_block(NOW, 1, 24)
        r.note_block(NOW, 1, 24)
        r.note_ok(initial_hours=1)
        assert r.blocked_until is None
        assert r.data["backoff_hours"] == 1


class TestRecordAndPersist:
    def test_counters_and_round_trip(self, tmp_path):
        r = rot(tmp_path)
        r.record("a", "ok", 5, NOW)
        r.record("a", "blocked", 0, NOW + timedelta(hours=6))
        r.save()
        again = Rotation(tmp_path / "rot.json")
        state = again.group_state("a")
        assert state["visits"] == 2
        assert state["blocked"] == 1
        assert state["posts_seen"] == 5
        assert state["last_outcome"] == "blocked"
        assert state["last_visit"] == (NOW + timedelta(hours=6)).isoformat()

    def test_corrupt_file_starts_empty(self, tmp_path):
        (tmp_path / "rot.json").write_text("{oops", encoding="utf-8")
        assert Rotation(tmp_path / "rot.json").data["groups"] == {}
```

- [ ] **Step 2: Run to verify failure** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `rotation.py`**

```python
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .groups import Group

OUTCOMES = ("ok", "blocked", "error", "empty")


def _parse(raw) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Rotation:
    """Which group to visit next, and Facebook-wide backoff. PC-owned file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self.data: dict = {"groups": {}, "blocked_until": None, "backoff_hours": None}
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("groups"), dict):
                    self.data.update(loaded)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass

    @property
    def blocked_until(self) -> datetime | None:
        return _parse(self.data.get("blocked_until"))

    def is_blocked(self, now: datetime) -> bool:
        until = self.blocked_until
        return until is not None and now < until

    def group_state(self, group_id: str) -> dict:
        return self.data["groups"].setdefault(
            group_id,
            {"last_visit": None, "last_outcome": None, "visits": 0, "blocked": 0, "posts_seen": 0},
        )

    def pick(self, groups: list[Group], now: datetime, batch_size: int, min_gap_hours: float) -> list[Group]:
        gap = timedelta(hours=min_gap_hours)
        due: list[tuple[datetime, Group]] = []
        for group in groups:
            if not group.enabled:
                continue
            last = _parse(self.group_state(group.id).get("last_visit"))
            if last is not None and now - last < gap:
                continue
            due.append((last or datetime.min.replace(tzinfo=timezone.utc), group))
        due.sort(key=lambda item: (item[0], item[1].id))
        return [group for _, group in due[:batch_size]]

    def record(self, group_id: str, outcome: str, posts_seen: int, now: datetime) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        state = self.group_state(group_id)
        state["last_visit"] = now.isoformat()
        state["last_outcome"] = outcome
        state["visits"] += 1
        state["posts_seen"] += int(posts_seen)
        if outcome == "blocked":
            state["blocked"] += 1

    def note_block(self, now: datetime, initial_hours: float, max_hours: float) -> None:
        hours = self.data.get("backoff_hours") or initial_hours
        self.data["blocked_until"] = (now + timedelta(hours=hours)).isoformat()
        self.data["backoff_hours"] = min(hours * 2, max_hours)

    def note_ok(self, initial_hours: float) -> None:
        self.data["blocked_until"] = None
        self.data["backoff_hours"] = initial_hours

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)
```

Check the backoff test arithmetic: first `note_block` with `backoff_hours=None` uses 1 h → `blocked_until = NOW+1h`, stores 2. Second call at NOW+2h uses 2 h → NOW+4h. Matches the test.

- [ ] **Step 4: Run tests, commit**

```bash
git add src/apt_scout/fb_groups/rotation.py tests/test_fb_groups_rotation.py
git commit -m "feat: Facebook groups rotation and backoff state

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Browser visit and DOM extraction

**Files:**
- Create: `src/apt_scout/fb_groups/browser.py`, `tests/fixtures/fb_group_page.html`
- Test: `tests/test_fb_groups_browser.py`

**Interfaces (produced):**
- `@dataclass VisitResult(outcome: str, posts: list[dict], title: str | None = None, error: str | None = None)`; `outcome` in `ok|blocked|error|empty`.
- `visit_group(group_id: str, now: datetime, *, url: str | None = None, timeout_ms: int = 45000, headless: bool = False) -> VisitResult` — never raises. `url` overrides the group URL (tests point it at a `file://` fixture).
- `records_from_extraction(raw: dict, group_id: str, now: datetime) -> list[dict]` — pure; turns the JS result into post records via `post_record` (Task 1); posts with no `post_id` are dropped.
- `EXPAND_JS`, `EXTRACT_JS` string constants.

- [ ] **Step 1: Write the fixture**

`tests/fixtures/fb_group_page.html` — hand-written, mirrors the stable parts of Facebook's markup (article roles, permalink anchors, a "See more" button). Anonymised text:

```html
<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><title>דירות בדיקה | Facebook</title></head>
<body>
<div role="feed">
  <div role="article">
    <h3><a href="/groups/testgroup/user/1/">Someone</a></h3>
    <a href="/groups/testgroup/posts/1111/" aria-label="5 שעות">5 שעות</a>
    <div data-ad-comet-preview="message">
      <div>להשכרה בפלורנטין 3 חדרים 4,900 ₪ <span id="tail1" style="display:none">כניסה מיידית, טלפון 052-1234567</span>
        <div role="button" onclick="document.getElementById('tail1').style.display='inline'; this.remove();">עוד</div>
      </div>
    </div>
    <img src="https://scontent.xx.fbcdn.net/v/t1.jpg">
    <img src="https://static.xx.fbcdn.net/rsrc.php/emoji.png">
  </div>
  <div role="article">
    <a href="/groups/testgroup/posts/2222/" aria-label="אתמול ב-14:30">אתמול ב-14:30</a>
    <div data-ad-comet-preview="message"><div>מחפשת דירה 2 חדרים עד 5000</div></div>
  </div>
  <div role="article">
    <a href="/groups/testgroup/user/9/">no permalink here</a>
    <div data-ad-comet-preview="message"><div>orphan text</div></div>
  </div>
</div>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

```python
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
```

- [ ] **Step 3: Run to verify failure** (`ModuleNotFoundError`).

- [ ] **Step 4: Implement `browser.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .groups import group_url
from .posts import post_record

# Off-screen so an hourly unattended visit never steals focus on the PC.
_CHROME_ARGS = ["--window-position=-32000,-32000", "--window-size=1280,900"]
_LOGIN_MARKER = "/login"

# Click every "See more" inside each post first; Facebook renders the full
# text on click even without a session.
EXPAND_JS = """() => {
  let clicked = 0;
  for (const art of document.querySelectorAll('[role=article]')) {
    for (const b of art.querySelectorAll('[role=button]')) {
      const t = (b.textContent || '').trim();
      if (t === 'עוד' || t === 'הצג עוד' || t === 'See more' || t === 'See More') {
        try { b.click(); clicked += 1; } catch (e) {}
      }
    }
  }
  return clicked;
}"""

# Stable hooks only: ARIA roles, permalink href shapes, the message
# container's data attribute, and the CDN host of real photos. No CSS
# class names (they are minified and rotate).
EXTRACT_JS = """() => {
  const posts = [];
  for (const art of document.querySelectorAll('[role=article]')) {
    let postId = null, timeLabel = null;
    for (const a of art.querySelectorAll('a[href]')) {
      const href = a.getAttribute('href') || '';
      const m = href.match(/\\/posts\\/(\\d+)/) || href.match(/\\/permalink\\/(\\d+)/) || href.match(/[?&]multi_permalinks=(\\d+)/);
      if (m) { postId = m[1]; timeLabel = a.getAttribute('aria-label') || a.textContent || null; break; }
    }
    const msg = art.querySelector('[data-ad-comet-preview="message"], [data-ad-preview="message"]');
    const text = ((msg ? msg.innerText : art.innerText) || '').trim();
    const photos = [];
    for (const img of art.querySelectorAll('img[src]')) {
      const src = img.getAttribute('src') || '';
      if (/^https:\\/\\/scontent[^/]*\\.fbcdn\\.net\\//.test(src)) photos.push(src);
    }
    posts.push({post_id: postId, text, time_label: timeLabel, photos});
  }
  const login = !!document.querySelector('form[action*="login"], #login_form, input[name="email"][type], input#email');
  return {posts, title: document.title || null, login, articles: posts.length};
}"""


@dataclass
class VisitResult:
    outcome: str  # ok | blocked | error | empty
    posts: list[dict] = field(default_factory=list)
    title: str | None = None
    error: str | None = None


def records_from_extraction(raw: dict, group_id: str, now: datetime) -> list[dict]:
    posts = raw.get("posts") if isinstance(raw, dict) else None
    if not isinstance(posts, list):
        return []
    records: list[dict] = []
    for item in posts:
        if not isinstance(item, dict) or not item.get("post_id"):
            continue
        records.append(post_record(group_id, item["post_id"], item.get("text") or "", item.get("time_label"), item.get("photos") or [], now))
    return records


def visit_group(group_id: str, now: datetime, *, url: str | None = None, timeout_ms: int = 45000, headless: bool = False) -> VisitResult:
    """One anonymous visit: fresh context, login redirect aborted, posts read."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return VisitResult("error", error=f"playwright missing: {exc}")

    target = url or group_url(group_id)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=headless, args=_CHROME_ARGS)
            try:
                context = browser.new_context(locale="he-IL", viewport={"width": 1280, "height": 900})
                page = context.new_page()
                page.route(f"**{_LOGIN_MARKER}**", lambda route: route.abort())
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as exc:  # noqa: BLE001
                    if "ERR_FAILED" in str(exc) or "abort" in str(exc).lower():
                        return VisitResult("blocked", error="login redirect aborted")
                    return VisitResult("error", error=str(exc)[:200])
                if _LOGIN_MARKER in page.url:
                    return VisitResult("blocked", error="redirected to login")
                try:
                    page.wait_for_selector("[role=article]", timeout=15000)
                except Exception:  # noqa: BLE001 - no posts is a legitimate outcome
                    pass
                page.evaluate(EXPAND_JS)
                page.wait_for_timeout(800)
                raw = page.evaluate(EXTRACT_JS)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - a browser failure is an outcome, not a crash
        return VisitResult("error", error=str(exc)[:200])

    title = raw.get("title") if isinstance(raw, dict) else None
    posts = records_from_extraction(raw, group_id, now)
    if not posts:
        if isinstance(raw, dict) and raw.get("login"):
            return VisitResult("blocked", title=title, error="login form shown")
        return VisitResult("empty", title=title)
    return VisitResult("ok", posts=posts, title=title)
```

- [ ] **Step 5: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fb_groups_browser.py -q`
Expected: all pass on the dev PC (Chrome present). If the fixture test fails on "See more", check that the click ran before extraction (the `wait_for_timeout(800)`), not by widening selectors.

- [ ] **Step 6: Commit**

```bash
git add src/apt_scout/fb_groups/browser.py tests/fixtures/fb_group_page.html tests/test_fb_groups_browser.py
git commit -m "feat: anonymous Facebook group visit and post extraction

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Collector orchestration and CLI

**Files:**
- Create: `src/apt_scout/fb_groups/collect.py`, `src/apt_scout/fb_groups/__main__.py`
- Modify: `config/sources.json` (add the `fb_groups` block)
- Test: `tests/test_fb_groups_collect.py`

**Interfaces (produced):**
- `@dataclass CollectSettings(batch_size=3, min_hours_between_visits=5.0, max_post_age_days=3.0, backoff_hours_initial=1.0, backoff_hours_max=24.0, visit_gap_seconds=20.0, feed_file="state/feeds/facebook_groups.json", rotation_file="state/fb_groups_rotation.json", groups_file="config/facebook_groups.json")`; `settings_from_config(config: dict) -> CollectSettings` (keys as in Global Constraints; unknown keys ignored).
- `@dataclass CollectionReport(visited: list[str], outcomes: dict[str, str], posts_added: int, feed_size: int, skipped: str | None)`.
- `run_collection(repo_root: Path, now: datetime, settings: CollectSettings, visit=visit_group, sleep=time.sleep) -> CollectionReport` — never raises except on feed write failure (`OSError`).
- CLI: `python -m apt_scout.fb_groups --repo .` → prints one summary line; exit 1 only on feed write failure.
- `config/sources.json` gains:

```json
  "fb_groups": {
    "enabled": true,
    "cadence_hours": 1,
    "feed_file": "state/feeds/facebook_groups.json",
    "feed_max_age_hours": 24,
    "rotation_file": "state/fb_groups_rotation.json",
    "groups_file": "config/facebook_groups.json",
    "batch_size": 3,
    "min_hours_between_visits": 5,
    "max_post_age_days": 3,
    "backoff_hours_initial": 1,
    "backoff_hours_max": 24,
    "visit_gap_seconds": 20
  }
```

- [ ] **Step 1: Write the failing tests**

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apt_scout.fb_groups.browser import VisitResult
from apt_scout.fb_groups.collect import CollectSettings, run_collection, settings_from_config
from apt_scout.fb_groups.posts import read_feed
from apt_scout.fb_groups.rotation import Rotation

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def repo(tmp_path, groups=("a", "b", "c", "d")):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "facebook_groups.json").write_text(
        json.dumps({"groups": [{"id": g, "name": "", "enabled": True} for g in groups]}), encoding="utf-8")
    return tmp_path


def post(group, pid, now=NOW):
    return {"group_id": group, "post_id": pid, "url": f"https://www.facebook.com/groups/{group}/posts/{pid}/",
            "text": "t", "posted_at": None, "photos": [], "fetched_at": now.isoformat()}


class FakeVisit:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, group_id, now, **kwargs):
        self.calls.append(group_id)
        return self.results.get(group_id, VisitResult("empty"))


def settings(**kw):
    base = dict(batch_size=2, min_hours_between_visits=5, visit_gap_seconds=0)
    base.update(kw)
    return CollectSettings(**base)


class TestRun:
    def test_visits_a_batch_and_writes_the_feed(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({"a": VisitResult("ok", [post("a", "1"), post("a", "2")], title="Group A"), "b": VisitResult("ok", [post("b", "9")])})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == ["a", "b"]
        assert report.posts_added == 3 and report.feed_size == 3
        feed = read_feed(root / "state" / "feeds" / "facebook_groups.json")
        assert {p["post_id"] for p in feed["posts"]} == {"1", "2", "9"}
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        assert rot.group_state("a")["posts_seen"] == 2
        assert rot.group_state("a")["name"] == "Group A"
        assert rot.group_state("a")["last_outcome"] == "ok"

    def test_a_block_ends_the_batch_and_sets_backoff(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({"a": VisitResult("blocked", error="login")})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == ["a"]
        assert report.outcomes == {"a": "blocked"}
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        assert rot.blocked_until == NOW + timedelta(hours=1)
        assert rot.group_state("a")["blocked"] == 1

    def test_a_blocked_period_skips_the_run(self, tmp_path):
        root = repo(tmp_path)
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        rot.note_block(NOW - timedelta(minutes=10), 1, 24)
        rot.save()
        visit = FakeVisit({})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == []
        assert report.skipped and "blocked" in report.skipped

    def test_rotation_moves_on_next_run(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({g: VisitResult("ok", [post(g, "1")]) for g in "abcd"})
        run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        run_collection(root, NOW + timedelta(hours=1), settings(), visit=visit, sleep=lambda s: None)
        assert visit.calls == ["a", "b", "c", "d"]

    def test_existing_feed_is_merged_not_replaced(self, tmp_path):
        root = repo(tmp_path)
        first = FakeVisit({"a": VisitResult("ok", [post("a", "1")])})
        run_collection(root, NOW, settings(batch_size=1), visit=first, sleep=lambda s: None)
        second = FakeVisit({"b": VisitResult("ok", [post("b", "2", NOW + timedelta(hours=6))])})
        report = run_collection(root, NOW + timedelta(hours=6), settings(batch_size=1), visit=second, sleep=lambda s: None)
        assert report.feed_size == 2

    def test_an_error_in_one_group_does_not_stop_the_batch(self, tmp_path):
        root = repo(tmp_path)
        visit = FakeVisit({"a": VisitResult("error", error="boom"), "b": VisitResult("ok", [post("b", "1")])})
        report = run_collection(root, NOW, settings(), visit=visit, sleep=lambda s: None)
        assert report.outcomes == {"a": "error", "b": "ok"}

    def test_success_resets_backoff(self, tmp_path):
        root = repo(tmp_path)
        rot = Rotation(root / "state" / "fb_groups_rotation.json")
        rot.note_block(NOW - timedelta(hours=3), 1, 24)
        rot.save()
        visit = FakeVisit({"a": VisitResult("ok", [post("a", "1")])})
        run_collection(root, NOW, settings(batch_size=1), visit=visit, sleep=lambda s: None)
        assert Rotation(root / "state" / "fb_groups_rotation.json").data["backoff_hours"] == 1


def test_settings_from_config_reads_known_keys():
    s = settings_from_config({"batch_size": 4, "visit_gap_seconds": 1, "unknown": 5})
    assert s.batch_size == 4 and s.visit_gap_seconds == 1 and s.min_hours_between_visits == 5


def test_sources_json_has_the_block():
    cfg = json.loads(Path("config/sources.json").read_text(encoding="utf-8"))["fb_groups"]
    assert cfg["feed_file"] == "state/feeds/facebook_groups.json"
    assert cfg["rotation_file"] == "state/fb_groups_rotation.json"
```

- [ ] **Step 2: Run to verify failure** (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `collect.py`**

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .browser import visit_group
from .groups import load_groups
from .posts import merge_feed, read_feed, write_feed
from .rotation import Rotation


@dataclass
class CollectSettings:
    batch_size: int = 3
    min_hours_between_visits: float = 5.0
    max_post_age_days: float = 3.0
    backoff_hours_initial: float = 1.0
    backoff_hours_max: float = 24.0
    visit_gap_seconds: float = 20.0
    feed_file: str = "state/feeds/facebook_groups.json"
    rotation_file: str = "state/fb_groups_rotation.json"
    groups_file: str = "config/facebook_groups.json"


def settings_from_config(config: dict) -> CollectSettings:
    known = {f.name for f in fields(CollectSettings)}
    return CollectSettings(**{k: v for k, v in config.items() if k in known})


@dataclass
class CollectionReport:
    visited: list[str] = field(default_factory=list)
    outcomes: dict[str, str] = field(default_factory=dict)
    posts_added: int = 0
    feed_size: int = 0
    skipped: str | None = None


def run_collection(repo_root: Path, now: datetime, settings: CollectSettings, visit=visit_group, sleep=time.sleep) -> CollectionReport:
    """One hourly pass: a few least-recently-visited groups, then the feed.

    A login redirect ends the batch and starts the Facebook-wide backoff;
    one group's error never stops the next. The feed keeps a rolling
    window of recent posts, so a group not visited this hour is still
    represented by its last visit.
    """
    repo_root = Path(repo_root)
    report = CollectionReport()
    groups = load_groups(repo_root / settings.groups_file)
    rotation = Rotation(repo_root / settings.rotation_file)

    if rotation.is_blocked(now):
        report.skipped = f"blocked until {rotation.blocked_until.isoformat()}"
        return report

    new_posts: list[dict] = []
    batch = rotation.pick(groups, now, settings.batch_size, settings.min_hours_between_visits)
    for index, group in enumerate(batch):
        if index > 0:
            sleep(settings.visit_gap_seconds)
        result = visit(group.id, now)
        report.visited.append(group.id)
        report.outcomes[group.id] = result.outcome
        rotation.record(group.id, result.outcome, len(result.posts), now)
        if result.title and not group.name:
            rotation.group_state(group.id)["name"] = result.title.replace(" | Facebook", "").strip()
        if result.outcome == "blocked":
            rotation.note_block(now, settings.backoff_hours_initial, settings.backoff_hours_max)
            break
        if result.outcome == "ok":
            rotation.note_ok(settings.backoff_hours_initial)
            new_posts.extend(result.posts)

    rotation.save()

    feed_path = repo_root / settings.feed_file
    existing = read_feed(feed_path)
    existing_posts = existing["posts"] if existing else []
    merged = merge_feed(existing_posts, new_posts, now, settings.max_post_age_days, {g.id for g in groups})
    if new_posts or existing is None:
        write_feed(feed_path, merged, now)
    report.posts_added = len(new_posts)
    report.feed_size = len(merged)
    return report
```

`__main__.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .collect import run_collection, settings_from_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apt-scout-fb-groups")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    root = Path(args.repo)
    sources = json.loads((root / "config" / "sources.json").read_text(encoding="utf-8"))
    settings = settings_from_config(sources.get("fb_groups", {}))
    try:
        report = run_collection(root, datetime.now(timezone.utc), settings)
    except OSError as exc:
        print(f"ERROR: could not write the feed: {exc}", file=sys.stderr)
        return 1
    if report.skipped:
        print(f"fb_groups: skipped ({report.skipped})")
    else:
        outcomes = ", ".join(f"{g}={o}" for g, o in report.outcomes.items()) or "no group due"
        print(f"fb_groups: visited {len(report.visited)} ({outcomes}); posts_added={report.posts_added} feed_size={report.feed_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: the summary line prints group ids only (ASCII), never titles, so the Windows console is safe.

- [ ] **Step 4: Add the `fb_groups` block to `config/sources.json`** (JSON above; keep the file valid — it is a plain object of sources).

- [ ] **Step 5: Run tests; commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fb_groups_collect.py tests/test_main.py -q` (test_main loads sources.json; it must still pass since unknown sources are ignored until the adapter exists — if `build_runtime` complains about an unknown source, check `__main__` only iterates adapters, not sources).

```bash
git add src/apt_scout/fb_groups/collect.py src/apt_scout/fb_groups/__main__.py config/sources.json tests/test_fb_groups_collect.py
git commit -m "feat: Facebook groups collector CLI with rotation and backoff

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Seeker classifier and text-hash fingerprint

**Files:**
- Create: `src/apt_scout/enrich/seeker.py`
- Modify: `src/apt_scout/cluster/fingerprints.py`
- Test: `tests/test_seeker.py`, `tests/test_fingerprints.py`

**Interfaces (produced):**
- `is_seeker_text(text: str | None) -> bool`: True when any `SEEKER_TERMS` phrase occurs in the first 200 characters of the normalised, lower-cased text AND `parse_price(text)` is None.
- `fingerprints()` emits `texthash:<sha1>` in `strong` when `normalise_text(raw_text).lower()` has ≥ `_MIN_TEXTHASH_LENGTH = 80` characters.

- [ ] **Step 1: Write the failing tests**

`tests/test_seeker.py`:

```python
import pytest

from apt_scout.enrich.seeker import is_seeker_text


@pytest.mark.parametrize("text", [
    "מחפשת דירה 2 חדרים במרכז תל אביב, כניסה מיידית",
    "מחפשים דירה לזוג, כניסה בנובמבר",
    "היי! מחפש/ת דירת 3 חדרים ברמת גן",
    "Looking for a 2 bedroom apartment in Tel Aviv, budget flexible",
    "Looking for an apartment near Dizengoff",
    "WANTED: studio in Florentin",
    "דרושה דירה להשכרה בגבעתיים",
    "מעוניינת לשכור דירה קטנה",
])
def test_seeker_posts(text):
    assert is_seeker_text(text) is True


@pytest.mark.parametrize("text", [
    "להשכרה דירת 3 חדרים בפלורנטין, 4,900 ₪",
    "דירה מקסימה, מחפשים שוכרים רציניים, 5,200 ש\"ח",   # offer that contains a seeker-ish word AND a price
    "מחפש דירה? יש לי אחת בשבילך! 4800 ₪",
    None,
    "",
])
def test_offer_posts(text):
    assert is_seeker_text(text) is False


def test_only_the_opening_counts():
    tail = "x" * 250 + " מחפשת דירה"
    assert is_seeker_text(tail) is False
```

Append to `tests/test_fingerprints.py`:

```python
class TestTextHashFingerprint:
    LONG = "להשכרה דירת 3 חדרים משופצת בפלורנטין, קומה 2, מרפסת שמש, מזגנים בכל החדרים, כניסה מיידית, ללא תיווך"

    def test_identical_long_text_shares_a_strong_key(self):
        a = fingerprints(make_listing(source="fb_groups", source_id="g1:1", raw_text=self.LONG), SALT)
        b = fingerprints(make_listing(source="fb_groups", source_id="g2:2", raw_text=self.LONG + "  "), SALT)
        keys_a = {k for k in a["strong"] if k.startswith("texthash:")}
        assert keys_a and keys_a == {k for k in b["strong"] if k.startswith("texthash:")}

    def test_short_text_gets_no_texthash(self):
        fp = fingerprints(make_listing(raw_text="דירה יפה 3 חדרים"), SALT)
        assert not any(k.startswith("texthash:") for k in fp["strong"])

    def test_different_text_differs(self):
        a = fingerprints(make_listing(raw_text=self.LONG), SALT)
        b = fingerprints(make_listing(raw_text=self.LONG.replace("קומה 2", "קומה 3")), SALT)
        assert [k for k in a["strong"] if k.startswith("texthash:")] != [k for k in b["strong"] if k.startswith("texthash:")]
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`src/apt_scout/enrich/seeker.py`:

```python
from __future__ import annotations

from ..normalise.price import parse_price
from ..normalise.text import normalise_text

# Group feeds mix offers with "looking for" posts. A seeker post opens with
# one of these and states no price; an offer that merely says "מחפשים
# שוכרים" almost always carries a price, which keeps it.
SEEKER_TERMS = [
    "מחפש דירה", "מחפשת דירה", "מחפשים דירה", "מחפש/ת", "דרושה דירה",
    "מעוניין לשכור", "מעוניינת לשכור",
    "looking for a", "looking for an", "wanted:",
]
_OPENING_CHARS = 200


def is_seeker_text(text: str | None) -> bool:
    cleaned = normalise_text(text).lower()
    if not cleaned:
        return False
    opening = cleaned[:_OPENING_CHARS]
    if not any(term in opening for term in SEEKER_TERMS):
        return False
    return parse_price(text) is None
```

Seekers who state a budget ("עד 5000", "budget 5k") read as offers under the spec's no-price rule; that is a known, accepted miss.

`fingerprints.py`: add near the other constants `_MIN_TEXTHASH_LENGTH = 80`, and inside `fingerprints()` after the exturl loop:

```python
    normalised = normalise_text(raw_text).lower()
    if len(normalised) >= _MIN_TEXTHASH_LENGTH:
        # Cross-posted ads usually carry the exact same text; identical
        # long text is as good as a shared phone number.
        strong.append("texthash:" + hashlib.sha1(normalised.encode("utf-8")).hexdigest())
```

- [ ] **Step 4: Run tests; commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_seeker.py tests/test_fingerprints.py tests/test_cluster_engine.py tests/test_pipeline.py -q`

```bash
git add src/apt_scout/enrich/seeker.py src/apt_scout/cluster/fingerprints.py tests/test_seeker.py tests/test_fingerprints.py
git commit -m "feat: seeker-post classifier and text-hash dedup fingerprint

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `Listing.group_id`, the cloud adapter, runtime wiring

**Files:**
- Create: `src/apt_scout/adapters/fb_groups.py`
- Modify: `src/apt_scout/models.py` (after `neighborhood`), `src/apt_scout/portal/builder.py` (`PUBLIC_FIELDS`), `src/apt_scout/__main__.py` (adapter list)
- Test: `tests/test_fb_groups_adapter.py`, `tests/test_serialise.py`, `tests/test_portal_builder.py`

**Interfaces (produced):**
- `Listing.group_id: str | None = None` (serialises via `asdict`; legacy dicts deserialise to None; in `PUBLIC_FIELDS` after `"neighborhood"`).
- `class FbGroupsAdapter` with `name = "fb_groups"` and `fetch(fetcher, config, since) -> AdapterResult`. Reads `config["feed_file"]` relative to `config["repo_root"]`; freshness `config.get("feed_max_age_hours", 24)`; `config.get("max_post_age_days", 3)`; `config.get("rotation_file")` for the block note. Errors (never raises): `"no feed file"`, `"feed is stale (fetched_at …)"`, `"feed unreadable"`. Detail on success: `"local feed from <fetched_at>"` plus `"; חסום עד HH:MM"` when the rotation file's `blocked_until` is in the future.
- Module-level `listing_from_post(post: dict, now: datetime, max_post_age_days: float) -> Listing | None` (None for seeker, too old, or missing ids).

- [ ] **Step 1: Write the failing tests**

`tests/test_fb_groups_adapter.py`:

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apt_scout.adapters.fb_groups import FbGroupsAdapter, listing_from_post
from apt_scout.models import Listing, Occupancy

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def post(**over):
    base = {"group_id": "tlvrent", "post_id": "55", "url": "https://www.facebook.com/groups/tlvrent/posts/55/",
            "text": "להשכרה בפלורנטין\n3 חדרים, 4,900 ₪, כניסה מיידית", "posted_at": (NOW - timedelta(hours=3)).isoformat(),
            "photos": ["https://scontent.x/a.jpg"], "fetched_at": NOW.isoformat()}
    base.update(over)
    return base


class TestListingFromPost:
    def test_maps_the_record(self):
        item = listing_from_post(post(), NOW, 3)
        assert item.source == "fb_groups"
        assert item.source_id == "tlvrent:55"
        assert item.group_id == "tlvrent"
        assert item.url.endswith("/posts/55/")
        assert item.title == "להשכרה בפלורנטין"
        assert item.raw_text.startswith("להשכרה")
        assert item.photos == ["https://scontent.x/a.jpg"]
        assert item.occupancy is Occupancy.UNSURE
        assert item.posted_at == NOW - timedelta(hours=3)
        assert item.price is None  # parsing happens in enrichment, not here

    def test_title_is_capped(self):
        item = listing_from_post(post(text="x" * 300), NOW, 3)
        assert len(item.title) == 120

    def test_seeker_posts_are_dropped(self):
        assert listing_from_post(post(text="מחפשת דירה 2 חדרים במרכז"), NOW, 3) is None

    def test_old_posts_are_dropped(self):
        assert listing_from_post(post(posted_at=(NOW - timedelta(days=4)).isoformat()), NOW, 3) is None

    def test_missing_posted_at_ages_by_fetched_at(self):
        assert listing_from_post(post(posted_at=None, fetched_at=(NOW - timedelta(days=5)).isoformat()), NOW, 3) is None
        assert listing_from_post(post(posted_at=None), NOW, 3) is not None

    def test_missing_ids_are_dropped(self):
        assert listing_from_post(post(post_id=None), NOW, 3) is None
        assert listing_from_post({"text": "x"}, NOW, 3) is None


def repo_with_feed(tmp_path, posts, fetched_at=NOW, rotation=None):
    feed = tmp_path / "state" / "feeds" / "facebook_groups.json"
    feed.parent.mkdir(parents=True)
    feed.write_text(json.dumps({"source": "fb_groups", "fetched_at": fetched_at.isoformat(), "posts": posts}, ensure_ascii=False), encoding="utf-8")
    if rotation is not None:
        (tmp_path / "state" / "fb_groups_rotation.json").write_text(json.dumps(rotation), encoding="utf-8")
    return {"repo_root": str(tmp_path), "feed_file": "state/feeds/facebook_groups.json", "feed_max_age_hours": 24,
            "max_post_age_days": 3, "rotation_file": "state/fb_groups_rotation.json", "enabled": True}


class TestAdapter:
    def test_reads_a_fresh_feed(self, tmp_path):
        config = repo_with_feed(tmp_path, [post(), post(post_id="56"), post(post_id="57", text="מחפש דירה בבקשה")])
        result = FbGroupsAdapter().fetch(None, config, since=None)
        assert result.error is None
        assert [l.source_id for l in result.listings] == ["tlvrent:55", "tlvrent:56"]
        assert result.detail.startswith("local feed from")

    def test_stale_feed_is_an_error(self, tmp_path):
        config = repo_with_feed(tmp_path, [post()], fetched_at=NOW - timedelta(hours=30))
        result = FbGroupsAdapter().fetch(None, config, since=None)
        assert result.listings == []
        assert "stale" in result.error

    def test_missing_feed_is_an_error(self, tmp_path):
        config = {"repo_root": str(tmp_path), "feed_file": "state/feeds/facebook_groups.json"}
        assert "no feed" in FbGroupsAdapter().fetch(None, config, since=None).error

    def test_block_state_shows_in_the_detail(self, tmp_path):
        until = NOW + timedelta(hours=2)
        config = repo_with_feed(tmp_path, [post()], rotation={"groups": {}, "blocked_until": until.isoformat(), "backoff_hours": 2})
        detail = FbGroupsAdapter(now=lambda: NOW).fetch(None, config, since=None).detail
        assert "חסום עד" in detail

    def test_never_raises_on_garbage(self, tmp_path):
        feed = tmp_path / "state" / "feeds" / "facebook_groups.json"
        feed.parent.mkdir(parents=True)
        feed.write_text("{nope", encoding="utf-8")
        config = {"repo_root": str(tmp_path), "feed_file": "state/feeds/facebook_groups.json"}
        assert FbGroupsAdapter().fetch(None, config, since=None).error
```

Append to `tests/test_serialise.py`:

```python
def test_group_id_round_trips_and_defaults():
    original = Listing(source="fb_groups", source_id="g:1", url="https://f/1", group_id="g")
    assert deserialise_listing(serialise_listing(original)).group_id == "g"
    data = serialise_listing(Listing(source="yad2", source_id="1", url="https://y/1"))
    del data["group_id"]
    assert deserialise_listing(data).group_id is None
```

Append inside `TestPublicDict` in `tests/test_portal_builder.py`:

```python
    def test_publishes_the_group_id(self):
        assert listing_to_public_dict(listing(group_id="tlvrent"))["group_id"] == "tlvrent"
```

- [ ] **Step 2: Run to verify failure** (`TypeError: unexpected keyword 'group_id'`, `ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`models.py`, after the `neighborhood` field:

```python
    # For fb_groups listings: the config id of the group the post came from.
    group_id: str | None = None
```

`portal/builder.py`: add `"group_id",` after `"neighborhood",` in `PUBLIC_FIELDS`.

`src/apt_scout/adapters/fb_groups.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..enrich.seeker import is_seeker_text
from ..fb_groups.posts import read_feed
from ..models import Listing, Occupancy
from .base import AdapterResult

DEFAULT_FEED_MAX_AGE_HOURS = 24
DEFAULT_MAX_POST_AGE_DAYS = 3
_TITLE_CHARS = 120


def _parse(raw) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def listing_from_post(post: dict, now: datetime, max_post_age_days: float) -> Listing | None:
    """One feed record -> one Listing, or None when it is not an offer.

    Parsing of price/rooms/size is left to the enrichment chain, exactly as
    for Marketplace; this only shapes the record and drops seekers and
    stale posts. A post with no timestamp ages by its fetch time.
    """
    if not isinstance(post, dict):
        return None
    group_id, post_id, url = post.get("group_id"), post.get("post_id"), post.get("url")
    if not (isinstance(group_id, str) and group_id and isinstance(post_id, str) and post_id and isinstance(url, str)):
        return None
    text = post.get("text") if isinstance(post.get("text"), str) else ""
    if is_seeker_text(text):
        return None
    posted_at = _parse(post.get("posted_at"))
    aged_by = posted_at or _parse(post.get("fetched_at"))
    if aged_by is not None and now - aged_by > timedelta(days=max_post_age_days):
        return None
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    photos = [p for p in (post.get("photos") or []) if isinstance(p, str)]
    return Listing(
        source="fb_groups",
        source_id=f"{group_id}:{post_id}",
        url=url,
        title=first_line[:_TITLE_CHARS] or None,
        raw_text=text or None,
        photos=photos,
        occupancy=Occupancy.UNSURE,
        posted_at=posted_at,
        group_id=group_id,
    )


class FbGroupsAdapter:
    """Reads the PC-collected feed; no network path of its own."""

    name = "fb_groups"

    def __init__(self, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._now = now

    def fetch(self, fetcher, config: dict, since: datetime | None) -> AdapterResult:
        try:
            repo_root = Path(config.get("repo_root", "."))
            feed_path = repo_root / config.get("feed_file", "state/feeds/facebook_groups.json")
            if not feed_path.exists():
                return AdapterResult(source=self.name, error="no feed file")
            feed = read_feed(feed_path)
            if feed is None:
                return AdapterResult(source=self.name, error="feed unreadable")
            now = self._now()
            fetched_at = _parse(feed.get("fetched_at"))
            max_age = timedelta(hours=config.get("feed_max_age_hours", DEFAULT_FEED_MAX_AGE_HOURS))
            if fetched_at is None or now - fetched_at > max_age:
                return AdapterResult(source=self.name, error=f"feed is stale (fetched_at {feed.get('fetched_at')})")

            max_post_age = config.get("max_post_age_days", DEFAULT_MAX_POST_AGE_DAYS)
            listings = [item for item in (listing_from_post(p, now, max_post_age) for p in feed["posts"]) if item]

            detail = f"local feed from {feed.get('fetched_at')}"
            blocked_until = self._blocked_until(repo_root / config.get("rotation_file", "state/fb_groups_rotation.json"))
            if blocked_until is not None and blocked_until > now:
                detail += f"; חסום עד {blocked_until.astimezone(timezone(timedelta(hours=3))).strftime('%H:%M')}"
            limit = config.get("max_results")
            if limit:
                listings = listings[:limit]
            return AdapterResult(source=self.name, listings=listings, detail=detail)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return AdapterResult(source=self.name, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _blocked_until(path: Path) -> datetime | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return _parse(raw.get("blocked_until")) if isinstance(raw, dict) else None
```

The Israel offset is hard-coded as UTC+3 for the display string only; the portal renders its own times client-side. (Israel is UTC+2 in winter; a one-hour drift in a footer note is acceptable and noted in the code comment.)

`__main__.py`: `from .adapters.fb_groups import FbGroupsAdapter` and add `FbGroupsAdapter(),` after `FbMarketplaceAdapter(budget),`. Every source config already gets `repo_root`.

- [ ] **Step 4: Run tests; commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fb_groups_adapter.py tests/test_serialise.py tests/test_portal_builder.py tests/test_main.py tests/test_pipeline.py -q`

```bash
git add src/apt_scout/adapters/fb_groups.py src/apt_scout/models.py src/apt_scout/portal/builder.py src/apt_scout/__main__.py tests/test_fb_groups_adapter.py tests/test_serialise.py tests/test_portal_builder.py
git commit -m "feat: fb_groups adapter reading the PC-collected feed

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Yield ledger and pipeline hooks

**Files:**
- Create: `src/apt_scout/fb_groups/ledger.py`
- Modify: `src/apt_scout/pipeline.py`, `src/apt_scout/__main__.py`
- Test: `tests/test_fb_groups_ledger.py`

**Interfaces (produced):**
- `class YieldLedger(store: StateStore)`; state key `YIELD = "fb_groups_yield"`. Methods: `count_offer(group_id, stable_id) -> bool`, `count_listing(group_id, stable_id) -> bool`, `credit_match(cluster_id, group_id, now) -> bool` (each returns True when it counted, False when already counted); `save()`; `rows(groups: list[Group], rotation: dict) -> list[dict]` — one row per config group: `{"id","name","enabled","visits","blocked","posts_seen","last_visit","offers","listings","matched","last_matched_at"}`, name = config name or rotation `name` or id; sorted by `matched` desc, `listings` desc, id. Id sets `_offers`, `_listings`, `_clusters` capped at the newest 5000 entries.
- `format_groups_report(rows, blocked_until: datetime | None) -> str` (Hebrew, plain text for Telegram).
- `run_pipeline(..., yield_ledger: YieldLedger | None = None)`: after enrichment, every `fb_groups` listing → `count_offer`; with `price` or `rooms` → `count_listing`. After `filters.matches(canonical)` succeeds: `member = min(cluster.members, key=(first_seen_at or now, _source_rank(source), stable_id))`; if `member.source == "fb_groups"` → `credit_match(cluster.cluster_id, member.group_id, now)`. `save()` once at the end.
- `__main__.build_runtime` creates `YieldLedger(store)` and stores it on `Runtime.yield_ledger`; `main()` passes it to `run_pipeline`; `Runtime.groups` = `load_groups(repo_root / "config" / "facebook_groups.json")` (empty list if missing).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `ledger.py`**

```python
from __future__ import annotations

from datetime import datetime

from ..state import StateStore
from .groups import Group

YIELD = "fb_groups_yield"
_ID_CAP = 5000
_COUNTERS = ("offers", "listings", "matched")


class YieldLedger:
    """Per-group counts the cloud owns: offers, listings, matched.

    Visit counts live in the PC-owned rotation file; `rows()` merges both.
    Every counter is once-only per id so re-runs and carry-forward never
    double count.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store
        data = store.load(YIELD, {})
        self._data: dict = data if isinstance(data, dict) else {}
        for key in ("_offers", "_listings", "_clusters"):
            if not isinstance(self._data.get(key), list):
                self._data[key] = []
        self._sets = {key: set(self._data[key]) for key in ("_offers", "_listings", "_clusters")}

    def _row(self, group_id: str) -> dict:
        row = self._data.get(group_id)
        if not isinstance(row, dict):
            row = {"offers": 0, "listings": 0, "matched": 0, "last_matched_at": None}
            self._data[group_id] = row
        return row

    def _count(self, set_key: str, counter: str, group_id: str, item_id: str) -> bool:
        if item_id in self._sets[set_key]:
            return False
        self._sets[set_key].add(item_id)
        self._data[set_key].append(item_id)
        self._row(group_id)[counter] += 1
        return True

    def count_offer(self, group_id: str, stable_id: str) -> bool:
        return self._count("_offers", "offers", group_id, stable_id)

    def count_listing(self, group_id: str, stable_id: str) -> bool:
        return self._count("_listings", "listings", group_id, stable_id)

    def credit_match(self, cluster_id: str, group_id: str, now: datetime) -> bool:
        if not self._count("_clusters", "matched", group_id, cluster_id):
            return False
        self._row(group_id)["last_matched_at"] = now.isoformat()
        return True

    def save(self) -> None:
        for key in ("_offers", "_listings", "_clusters"):
            self._data[key] = self._data[key][-_ID_CAP:]
        self._store.save(YIELD, self._data)

    def rows(self, groups: list[Group], rotation: dict) -> list[dict]:
        rot_groups = rotation.get("groups") if isinstance(rotation, dict) else {}
        rot_groups = rot_groups if isinstance(rot_groups, dict) else {}
        rows = []
        for group in groups:
            rot = rot_groups.get(group.id) or {}
            row = self._data.get(group.id) if isinstance(self._data.get(group.id), dict) else {}
            rows.append({
                "id": group.id,
                "name": group.name or rot.get("name") or group.id,
                "enabled": group.enabled,
                "visits": int(rot.get("visits") or 0),
                "blocked": int(rot.get("blocked") or 0),
                "posts_seen": int(rot.get("posts_seen") or 0),
                "last_visit": rot.get("last_visit"),
                "offers": int(row.get("offers") or 0),
                "listings": int(row.get("listings") or 0),
                "matched": int(row.get("matched") or 0),
                "last_matched_at": row.get("last_matched_at"),
            })
        rows.sort(key=lambda r: (-r["matched"], -r["listings"], r["id"]))
        return rows


def format_groups_report(rows: list[dict], blocked_until: datetime | None) -> str:
    lines = ["קבוצות פייסבוק (תואמות / מודעות / פוסטים / ביקורים):"]
    for row in rows:
        flag = "" if row["enabled"] else " (כבויה)"
        lines.append(f"{row['matched']} / {row['listings']} / {row['posts_seen']} / {row['visits']} — {row['name']}{flag}")
    if blocked_until is not None:
        lines.append(f"פייסבוק חסום עד {blocked_until.strftime('%d/%m %H:%M')} UTC")
    return "\n".join(lines)
```

- [ ] **Step 4: Pipeline hooks**

In `pipeline.py`: import `from .cluster.engine import Cluster, ClusterEngine, _source_rank` (add `_source_rank` to the import; it exists in `engine.py`). Signature gains `yield_ledger: Any | None = None`. After the enrichment loop (right before the carry-forward cache block):

```python
    if yield_ledger is not None:
        for listing in enriched:
            if listing.source == "fb_groups" and listing.group_id:
                yield_ledger.count_offer(listing.group_id, listing.stable_id())
                if listing.price is not None or listing.rooms is not None:
                    yield_ledger.count_listing(listing.group_id, listing.stable_id())
```

Right after `report.matched += 1`:

```python
        if yield_ledger is not None:
            earliest = min(
                cluster.members,
                key=lambda m: (m.first_seen_at or now, _source_rank(m.source), m.stable_id()),
            )
            if earliest.source == "fb_groups" and earliest.group_id:
                yield_ledger.credit_match(cluster.cluster_id, earliest.group_id, now)
```

Before `return report`: `if yield_ledger is not None: yield_ledger.save()`.

Note: `first_seen_at` on members is set by the pipeline for fetched listings and preserved for restored ones, so the earliest member is the first source that carried the apartment. Two members with equal timestamps (same run) fall back to source priority, where `fb_groups` is unknown and sorts last, so a same-run yad2+group pair credits yad2 (i.e., nothing). Add `"fb_groups"` to `_SOURCE_PRIORITY` in `engine.py` after `"fb_marketplace"` so its rank is deterministic.

`__main__.py`: `Runtime` gains `yield_ledger: Any = None` and `groups: list = field(default_factory=list)` (import `field`); `build_runtime` sets `yield_ledger=YieldLedger(store)` and `groups=load_groups(repo_root / "config" / "facebook_groups.json") if that file exists else []`; `main()` passes `yield_ledger=runtime.yield_ledger` to `run_pipeline`.

- [ ] **Step 5: Run tests; commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fb_groups_ledger.py tests/test_pipeline.py tests/test_cluster_engine.py tests/test_main.py -q`

```bash
git add src/apt_scout/fb_groups/ledger.py src/apt_scout/pipeline.py src/apt_scout/cluster/engine.py src/apt_scout/__main__.py tests/test_fb_groups_ledger.py
git commit -m "feat: per-group yield ledger credited to the first group that carried an apartment

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Telegram `/groups` and the group line in alerts

**Files:**
- Modify: `src/apt_scout/notify/commands.py`, `src/apt_scout/notify/telegram.py`, `src/apt_scout/__main__.py`
- Test: `tests/test_commands.py`, `tests/test_telegram.py`

**Interfaces (produced):**
- `apply_command(filters, command, args, knowledge=None, groups_text: str | None = None)`: `/groups` replies with `groups_text` or `"אין עדיין נתונים על קבוצות פייסבוק."`; filters unchanged. `USAGE` gains `"/groups — תפוקת קבוצות הפייסבוק\n"` before `/pause`.
- `process_commands(..., knowledge=None, groups_text: str | None = None)` forwards it.
- `format_listing(listing, knowledge=None, group_names: dict[str, str] | None = None)`: when `listing.group_id` is set, a line `👥 קבוצה: <name or id>` after the source line's predecessor (place it right before `מקור:`). `TelegramNotifier(..., knowledge=None, group_names=None)`.
- `__main__.main()` computes `groups_text = format_groups_report(runtime.yield_ledger.rows(runtime.groups, rotation_data), blocked_until)` where `rotation_data = runtime.store.load("fb_groups_rotation", {})` and `blocked_until` parsed from it (reuse `Rotation(repo_root / "state" / "fb_groups_rotation.json").blocked_until`), and passes it to `process_commands`; `group_names = {g.id: g.name or g.id for g in runtime.groups}` goes to the notifier.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_commands.py`:

```python
class TestGroupsCommand:
    def test_replies_with_the_report(self):
        filters, reply = apply_command(Filters(), "groups", [], None, groups_text="קבוצה א: 3")
        assert reply == "קבוצה א: 3"
        assert filters.to_dict() == Filters().to_dict()

    def test_without_data(self):
        _, reply = apply_command(Filters(), "groups", [])
        assert "אין עדיין" in reply

    def test_usage_mentions_groups(self):
        _, reply = apply_command(Filters(), "nonsense", [])
        assert "/groups" in reply
```

Append to `tests/test_telegram.py`:

```python
def test_format_adds_the_group_name():
    from apt_scout.models import Listing
    item = Listing(source="fb_groups", source_id="tlvrent:1", url="https://f/1", group_id="tlvrent")
    text = format_listing(item, None, group_names={"tlvrent": "TLV Rent"})
    assert "👥 קבוצה: TLV Rent" in text


def test_format_falls_back_to_the_group_id():
    from apt_scout.models import Listing
    item = Listing(source="fb_groups", source_id="x:1", url="https://f/1", group_id="x")
    assert "👥 קבוצה: x" in format_listing(item, None)
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`commands.py`: in `USAGE` add `"/groups — תפוקת קבוצות הפייסבוק\n"` before the `/pause` line. `apply_command` signature: `(filters, command, args, knowledge=None, groups_text=None)`; add before the final `return filters, USAGE`:

```python
    if command == "groups":
        return filters, groups_text or "אין עדיין נתונים על קבוצות פייסבוק."
```

`process_commands` gains `groups_text: str | None = None` and passes it: `apply_command(filters, command, args, knowledge, groups_text)`.

`telegram.py`: `format_listing(listing, knowledge=None, group_names=None)`; before `lines.append(f"מקור: {listing.source}")`:

```python
    if listing.group_id:
        name = (group_names or {}).get(listing.group_id) or listing.group_id
        lines.append("👥 קבוצה: " + html.escape(name))
```

`TelegramNotifier.__init__(..., knowledge=None, group_names=None)` stores `self._group_names`; `send_listing` calls `format_listing(listing, self._knowledge, self._group_names)`.

`__main__.py`: in `build_runtime`, pass `group_names={g.id: g.name or g.id for g in groups}` to `TelegramNotifier`; in `main()` before `process_commands`:

```python
    rotation = Rotation(Path(args.repo) / "state" / "fb_groups_rotation.json")
    groups_text = format_groups_report(
        runtime.yield_ledger.rows(runtime.groups, rotation.data), rotation.blocked_until
    ) if runtime.groups else None
```

and pass `groups_text=groups_text`.

- [ ] **Step 4: Run tests; commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_commands.py tests/test_telegram.py tests/test_main.py -q`

```bash
git add src/apt_scout/notify/commands.py src/apt_scout/notify/telegram.py src/apt_scout/__main__.py tests/test_commands.py tests/test_telegram.py
git commit -m "feat: /groups report and group name in alerts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Portal — group badge, post link, groups table

**Files:**
- Modify: `src/apt_scout/portal/builder.py`, `src/apt_scout/__main__.py`, `src/apt_scout/portal/assets/index.html`, `src/apt_scout/portal/assets/app.js`, `src/apt_scout/portal/assets/style.css`
- Test: `tests/test_portal_builder.py`, `tests/test_portal_assets.py`

**Interfaces (produced):**
- `build_portal(..., knowledge=None, groups: list[dict] | None = None)` writes `data/groups.json` = `{id: {name, enabled, visits, blocked, posts_seen, offers, listings, matched, last_matched_at, last_visit}}` (`{}` when None). `main()` passes the ledger rows.
- DOM: `#groups` `<details>` in the footer with `<table id="groups-table">`; card badge `.badge.group`; link text `לפוסט בקבוצה` for `fb_groups` items.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_portal_builder.py`:

```python
class TestGroupsFile:
    def test_publishes_group_rows_by_id(self, tmp_path):
        rows = [{"id": "tlvrent", "name": "TLV", "enabled": True, "visits": 2, "blocked": 0, "posts_seen": 5,
                 "offers": 3, "listings": 2, "matched": 1, "last_matched_at": None, "last_visit": None}]
        build_portal(tmp_path, [listing()], {}, Filters(), NOW, groups=rows)
        data = json.loads((tmp_path / "data" / "groups.json").read_text(encoding="utf-8"))
        assert data["tlvrent"]["matched"] == 1 and data["tlvrent"]["name"] == "TLV"

    def test_empty_without_groups(self, tmp_path):
        build_portal(tmp_path, [listing()], {}, Filters(), NOW)
        assert json.loads((tmp_path / "data" / "groups.json").read_text(encoding="utf-8")) == {}
```

Append to `tests/test_portal_assets.py`:

```python
class TestGroupsUi:
    def test_html_has_the_groups_table(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="groups"' in html and 'id="groups-table"' in html

    def test_js_loads_groups_and_renders_badge(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert 'fetch("data/groups.json")' in js
        assert "badge group" in js
        assert "לפוסט בקבוצה" in js
        assert "innerHTML" not in js
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`builder.py`: signature `groups: list[dict] | None = None`; after the neighborhoods file:

```python
    # Per-group yield rows for the footer table; no PII (config ids/names only).
    (output_dir / "data" / "groups.json").write_text(
        json.dumps({row["id"]: {k: v for k, v in row.items() if k != "id"} for row in (groups or [])}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

`__main__.py`: `build_portal(..., knowledge=runtime.knowledge, groups=runtime.yield_ledger.rows(runtime.groups, rotation.data))` (reuse the `rotation` built in Task 8's `main()`; move its construction above the pipeline call).

`index.html`: replace `<footer id="health"></footer>` with

```html
  <footer>
    <div id="health"></div>
    <details id="groups">
      <summary>קבוצות פייסבוק</summary>
      <table id="groups-table"></table>
    </details>
  </footer>
```

`app.js`:
- top: `let groupsInfo = {};`
- in `card(item)`, right after the source badge:

```js
  if (item.group_id) {
    const badgeGroup = document.createElement("span");
    badgeGroup.className = "badge group";
    const info = groupsInfo[item.group_id];
    badgeGroup.textContent = "קבוצה: " + (info && info.name ? info.name : item.group_id);
    body.appendChild(badgeGroup);
  }
```

- the original-ad link: `link.textContent = item.source === "fb_groups" ? "לפוסט בקבוצה" : "למודעה המקורית";`
- new function:

```js
function renderGroupsTable() {
  const table = document.getElementById("groups-table");
  table.replaceChildren();
  const rows = Object.entries(groupsInfo);
  if (!rows.length) {
    document.getElementById("groups").hidden = true;
    return;
  }
  const head = document.createElement("tr");
  ["קבוצה", "ביקורים", "חסימות", "פוסטים", "מודעות", "תואמות", "תואמת לאחרונה"].forEach((t) => {
    const th = document.createElement("th");
    th.textContent = t;
    head.appendChild(th);
  });
  table.appendChild(head);
  rows.sort((a, b) => (b[1].matched || 0) - (a[1].matched || 0));
  rows.forEach(([id, g]) => {
    const tr = document.createElement("tr");
    if (g.enabled === false) tr.className = "disabled";
    const last = g.last_matched_at ? new Date(g.last_matched_at).toLocaleDateString("he-IL") : "—";
    [g.name || id, g.visits || 0, g.blocked || 0, g.posts_seen || 0, g.listings || 0, g.matched || 0, last].forEach((v) => {
      const td = document.createElement("td");
      td.textContent = String(v);
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
}
```

- loading: extend the `Promise.all` with a third tolerant fetch `fetch("data/groups.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({}))`, assign `groupsInfo = loadedGroups || {};` and call `renderGroupsTable()` after `renderHealth(...)`.

`style.css`:

```css
.badge.group { background: #6f42c1; border-color: #6f42c1; color: #fff; }
#groups { margin-top: .75rem; font-size: .8rem; color: var(--muted); }
#groups summary { cursor: pointer; }
#groups-table { border-collapse: collapse; margin-top: .5rem; }
#groups-table th, #groups-table td { padding: .2rem .6rem; border-bottom: 1px solid var(--line); text-align: right; }
#groups-table tr.disabled { opacity: .5; }
```

- [ ] **Step 4: Run tests, `node --check`, commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_portal_builder.py tests/test_portal_assets.py tests/test_portal_publish.py tests/test_main.py -q` and `node --check src/apt_scout/portal/assets/app.js`.

```bash
git add src/apt_scout/portal src/apt_scout/__main__.py tests/test_portal_builder.py tests/test_portal_assets.py
git commit -m "feat: portal group badge, post link and groups yield table

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: PC script, smoke test, docs, end-to-end check

**Files:**
- Modify: `scripts/local_yad2_feed.ps1`, `README.md`, `docs/superpowers/specs/2026-09-21-facebook-groups-design.md`, `C:\Users\eladl\.claude\projects\C--Github-Apt-scout\memory\apt-scout-project-state.md`
- Create: `scripts/fb_groups_smoke.py`

- [ ] **Step 1: PS1 script**

After the yad2 fetch block succeeds (after `if ($fetchExit -ne 0) { ... exit }`), add:

```powershell
Write-Log "collecting Facebook groups via $PythonExe -m apt_scout.fb_groups"
try {
    $fbOutput = (& $PythonExe -m apt_scout.fb_groups --repo $RepoRoot 2>&1 | Out-String).Trim()
    Write-Log "fb_groups exit=$LASTEXITCODE output: $fbOutput"
} catch {
    Write-Log "fb_groups collection failed (continuing with yad2 only): $($_.Exception.Message)"
}
```

Then generalise the commit: replace the single-file status/add with

```powershell
$FeedFiles = @("state/feeds/yad2.json", "state/feeds/facebook_groups.json", "state/fb_groups_rotation.json")
$statusOutput = (git status --porcelain -- $FeedFiles | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($statusOutput)) {
    Write-Log "no change to feed files; nothing to commit. === run end ==="
    exit 0
}
git add -- $FeedFiles
$commitOutput = (git commit -m "chore: local feeds" 2>&1 | Out-String).Trim()
```

Keep everything else. Test by running the script once by hand from an elevated-free prompt: `powershell -NoProfile -File scripts\local_yad2_feed.ps1` and read `%LOCALAPPDATA%\apt-scout\feed.log`. If Facebook is still blocked, the log shows `fb_groups: skipped (blocked until …)` or a `blocked` outcome and the run still commits yad2.

- [ ] **Step 2: Smoke script** `scripts/fb_groups_smoke.py`

```python
"""Manual check: visit ONE group anonymously and print the records (ids,
times, text lengths only). Never run on CI. Usage:
    .venv\\Scripts\\python.exe scripts\\fb_groups_smoke.py ApartmentsTelAviv
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from apt_scout.fb_groups.browser import visit_group  # noqa: E402

group = sys.argv[1] if len(sys.argv) > 1 else "ApartmentsTelAviv"
result = visit_group(group, datetime.now(timezone.utc))
print("outcome:", result.outcome, "| error:", result.error, "| title:", ascii(result.title))
for post in result.posts:
    print(post["post_id"], post["posted_at"], len(post["text"]), "chars", len(post["photos"]), "photos")
```

- [ ] **Step 3: Measured cadence**

Read the recovery probe result (the controller reports it). Set `batch_size` and `min_hours_between_visits` in `config/sources.json` so that the visits per hour from the PC stay well under the observed trigger (10 visits in ~5 minutes tripped it): with 17 groups and `batch_size` 3 the PC makes 3 visits per hour, 20 s apart; if the block lasted longer than 6 h, also set `backoff_hours_initial` to 6. Record the measurement and the chosen values in the spec's "Facts established by probing" section and in the README.

- [ ] **Step 4: README**

Sources table: add `| fb_groups | PC feed | 17 public groups (config/facebook_groups.json), visited anonymously a few per hour from the PC; posts parsed in the cloud; per-group yield in the portal footer and /groups. |`. New section `## Facebook groups` before `## Portal`: what the collector does, the rate limit and backoff, the yield ledger and how to drop a group (set `enabled: false`), the smoke script, the two state files and who writes them, and that no Facebook account is used. Commands table: `| /groups | Per-group yield: matched / listings / posts / visits |`.

- [ ] **Step 5: Spec amendment and memory**

Append `## Amendments (as built, <date>)` to the spec: 17 groups (not 18); discovered names live in the rotation file, not the config; measured block duration and chosen cadence. Add a memory bullet: fb_groups shipped, anonymous PC collector, block behaviour, the one-writer-per-file rule, `/groups`.

- [ ] **Step 6: End-to-end dry run**

Create a temporary feed by hand (three posts: an offer with price, a seeker, a cross-post of the offer's text under another group), run `.\.venv\Scripts\python.exe -m apt_scout --repo . --dry-run --build-portal --portal-dir site` with `$env:PYTHONPATH='src'`, and confirm: the offer appears once in `site/data/listings.json` with `sources` containing `fb_groups` and a `group_id`; the seeker is absent; `state/fb_groups_yield.json` credits the first group; `site/data/groups.json` exists. Then `git checkout -- state` to discard dry-run state changes except none of the new files should be committed from a dry run (revert them all).

- [ ] **Step 7: Full suite, commit, push**

Run `.\.venv\Scripts\python.exe -m pytest -q` (expect ~760 passed). Commit `scripts/`, `README.md`, spec, `config/sources.json` if changed:

```bash
git add scripts/local_yad2_feed.ps1 scripts/fb_groups_smoke.py README.md config/sources.json docs/superpowers/specs/2026-09-21-facebook-groups-design.md
git commit -m "docs: Facebook groups collector, cadence and yield ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Push is done by the controller after the whole-branch review.

---

## Self-review notes

- Spec coverage: §1 config + post record → Task 1; §2 collector (rotation, backoff, off-screen, login abort, extraction, feed merge, counters, never raises, PS1) → Tasks 2, 3, 4, 10; §3 adapter, seeker, texthash, `group_id` → Tasks 5, 6; §4 ledger, first-group credit, `_clusters`, portal table, `/groups` → Tasks 7, 8, 9; §5 badge/link/health detail → Tasks 6 (detail), 9; §6 tests → in every task; smoke script → Task 10.
- Deviations from the spec, deliberate: discovered group names are written to the rotation file, not back into `config/facebook_groups.json` (keeps the config human-owned); the group count is 17; `offers`/`listings` are counted in the pipeline (the adapter has no store) exactly as the spec's once-only rule requires.
- Type consistency: `VisitResult.posts` are post records (dicts), `run_collection` passes them to `merge_feed`; `listing_from_post` consumes the same dicts; `YieldLedger.rows(groups: list[Group], rotation: dict)` is called with `Rotation.data` in `__main__` and with plain dicts in tests; `format_groups_report(rows, blocked_until)` used by Task 8.
