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
