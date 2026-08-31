from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SEEN = "seen"
NOTIFIED = "notified"


class StateStore:
    """JSON state on disk, committed to git by the workflow.

    Git gives us durability, history, and diffability for free, which is why
    there is no database. Writes are atomic so an interrupted run cannot leave
    truncated state behind.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def load(self, name: str, default: Any) -> Any:
        path = self._path(name)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # Corrupt state must not stop a run; git history holds the good copy.
            return default

    def save(self, name: str, data: Any) -> None:
        path = self._path(name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def first_seen(self) -> dict[str, str]:
        """Mapping of stable id to first-seen ISO timestamp.

        The legacy on-disk form was a bare list of ids; it is read as entries
        with an empty timestamp, so old state keeps working after an upgrade.
        """
        raw = self.load(SEEN, {})
        if isinstance(raw, list):
            return {item: "" for item in raw}
        return dict(raw)

    def seen_ids(self) -> set[str]:
        return set(self.first_seen())

    def record_seen(self, entries: dict[str, str]) -> None:
        """Merge NEW entries into the seen map.

        An id that is already recorded keeps its original timestamp — the
        whole point of storing it is that it never changes afterwards.
        """
        self.save(SEEN, {**entries, **self.first_seen()})

    def mark_seen(self, ids: Iterable[str]) -> None:
        self.record_seen({item: "" for item in ids})

    def notified_ids(self) -> set[str]:
        return set(self.load(NOTIFIED, []))

    def mark_notified(self, ids: Iterable[str]) -> None:
        self.save(NOTIFIED, sorted(self.notified_ids() | set(ids)))
