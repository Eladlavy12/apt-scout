from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..normalise.text import normalise_text
from ..state import StateStore

CACHE = "geocache"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "apt-scout/0.1 (personal apartment search)"

# Sentinel distinguishing "looked up, no result" from "never looked up", so a
# permanently unresolvable address is not retried on every run forever.
_MISS = "miss"


class _TransportError(Exception):
    """The request itself failed — an outage, not an unresolvable address.

    Kept distinct from a genuine miss so a one-hour network blip does not get
    cached as "this address does not exist" forever.
    """


class Geocoder:
    """Address to coordinates via Nominatim, cached and rate limited."""

    def __init__(
        self,
        store: StateStore,
        client: Any = None,
        min_interval: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store
        self._cache: dict[str, Any] = store.load(CACHE, {})
        self._min_interval = min_interval
        self._sleep = sleep
        self._last_call = 0.0
        if client is None:
            import httpx

            client = httpx.Client(timeout=20.0)
        self._client = client

    def geocode(self, address: str | None) -> tuple[float, float] | None:
        key = normalise_text(address)
        if not key:
            return None

        if key in self._cache:
            cached = self._cache[key]
            return None if cached == _MISS else (cached[0], cached[1])

        self._throttle()
        try:
            result = self._lookup(key)
        except _TransportError:
            # Transient failure: not cached, so the next run retries.
            return None

        self._cache[key] = _MISS if result is None else [result[0], result[1]]
        self._store.save(CACHE, self._cache)
        return result

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def _lookup(self, address: str) -> tuple[float, float] | None:
        try:
            response = self._client.get(
                NOMINATIM_URL,
                params={
                    "q": address,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "il",
                },
                headers={"User-Agent": USER_AGENT},
            )
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - an outage must not fail a run
            raise _TransportError(str(exc)) from exc

        if not payload:
            return None
        try:
            return float(payload[0]["lat"]), float(payload[0]["lon"])
        except (KeyError, ValueError, TypeError):
            return None
