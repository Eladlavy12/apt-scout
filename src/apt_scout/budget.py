from __future__ import annotations

from datetime import datetime
from typing import Any

from .state import StateStore

BUDGET = "budget"
WARNING_THRESHOLD = 0.8


class BudgetGuard:
    """Tracks monthly spend on paid sources and enforces a cap.

    Exists so a runaway paid-scraping source cannot silently rack up an API
    bill — the guard is consulted before spending and records every spend
    afterwards, resetting itself automatically when the calendar month rolls
    over.
    """

    def __init__(
        self,
        store: StateStore,
        monthly_cap_usd: float = 5.0,
        notifier: Any | None = None,
    ) -> None:
        self._store = store
        self._cap = monthly_cap_usd
        self._notifier = notifier
        self._data: dict = store.load(BUDGET, self._empty_month(""))

    @staticmethod
    def _month_key(now: datetime) -> str:
        return now.strftime("%Y-%m")

    @staticmethod
    def _empty_month(month: str) -> dict:
        return {"month": month, "spent_usd": 0.0, "by_source": {}, "warned": False}

    def _ensure_month(self, now: datetime) -> None:
        month = self._month_key(now)
        if self._data.get("month") != month:
            self._data = self._empty_month(month)
            self._store.save(BUDGET, self._data)

    def can_spend(self, source: str, now: datetime) -> bool:
        self._ensure_month(now)
        return self._data["spent_usd"] < self._cap

    def record(self, source: str, results: int, cost_usd: float, now: datetime) -> None:
        self._ensure_month(now)
        self._data["spent_usd"] += cost_usd
        by_source = self._data["by_source"]
        by_source[source] = by_source.get(source, 0.0) + cost_usd

        if not self._data["warned"] and self._data["spent_usd"] >= WARNING_THRESHOLD * self._cap:
            if self._warn():
                self._data["warned"] = True

        self._store.save(BUDGET, self._data)

    def _warn(self) -> bool:
        if self._notifier is None:
            return False
        spent = self._data["spent_usd"]
        text = f"⚠️ תקציב Apify: נוצלו {spent:g}$ מתוך {self._cap:g}$"
        return bool(self._notifier.send_text(text))

    def spent_this_month(self, now: datetime) -> float:
        self._ensure_month(now)
        return self._data["spent_usd"]
