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
