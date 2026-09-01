from __future__ import annotations

from datetime import datetime

from .state import StateStore

CADENCE = "cadence"

# Hourly crons drift by a few minutes; without slack a run that fires at
# :57 instead of :00 for a 1h-cadence source would be skipped and pushed a
# full cycle later. 5 minutes absorbs that drift without meaningfully
# changing how often a source is actually polled.
SLACK_SECONDS = 300


class CadenceGate:
    """Per-source "is it time to run yet" gate, persisted in state.

    Each source declares its own cadence (in hours) in sources.json; this
    lets a slow-changing board be polled less often than a fast one without
    every source being forced onto the same schedule as the workflow cron.
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def is_due(self, source: str, cadence_hours: float, now: datetime) -> bool:
        last_ran = self._store.load(CADENCE, {}).get(source)
        if not last_ran:
            return True
        try:
            last = datetime.fromisoformat(last_ran)
        except ValueError:
            # Unreadable timestamp must not wedge a source into never running.
            return True
        elapsed = (now - last).total_seconds()
        return elapsed >= cadence_hours * 3600 - SLACK_SECONDS

    def mark_ran(self, source: str, now: datetime) -> None:
        data = self._store.load(CADENCE, {})
        data[source] = now.isoformat()
        self._store.save(CADENCE, data)
