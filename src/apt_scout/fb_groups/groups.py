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
