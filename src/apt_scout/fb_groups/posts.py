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
