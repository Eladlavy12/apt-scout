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
