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
