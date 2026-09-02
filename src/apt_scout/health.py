from __future__ import annotations

from datetime import datetime, timezone

from .state import StateStore

HEALTH = "health"


class HealthTracker:
    """Per-source success and failure history.

    Exists so a silently broken scraper is visible rather than looking like a
    quiet rental market — the most dangerous failure mode this system has.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._data: dict = store.load(HEALTH, {})

    def record(
        self, source: str, ok: bool, error: str | None = None, detail: str | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        entry = self._data.setdefault(
            source,
            {
                "last_success": None,
                "last_failure": None,
                "consecutive_failures": 0,
                "last_error": None,
                "detail": None,
            },
        )
        if ok:
            entry["last_success"] = now
            entry["consecutive_failures"] = 0
            entry["last_error"] = None
            entry["detail"] = detail
        else:
            entry["last_failure"] = now
            entry["consecutive_failures"] += 1
            entry["last_error"] = error
            entry["detail"] = None
        self._store.save(HEALTH, self._data)

    def report(self) -> dict:
        return self._data

    def failing_sources(self, threshold: int = 3) -> list[str]:
        return sorted(
            source
            for source, entry in self._data.items()
            if entry["consecutive_failures"] >= threshold
        )
