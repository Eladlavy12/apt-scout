from __future__ import annotations

from typing import Any

from ..state import StateStore

CACHE = "drivecache"

# Ort Singalovski, Yad Eliyahu, Tel Aviv.
CENTRE = (32.056581, 34.804087)

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"

# Three decimal places is roughly 100 m, which keeps the cache hit rate high
# without meaningfully changing the driving time.
_PRECISION = 3

_MISS = "miss"


class DriveTimeCalculator:
    """Driving minutes from the centre point, via OSRM, cached.

    This implements the user's actual criterion — "15 minutes drive" — rather
    than approximating it with a straight-line radius, which misjudges badly
    near the Ayalon and the river.
    """

    def __init__(self, store: StateStore, client: Any = None, centre: tuple[float, float] = CENTRE) -> None:
        self._store = store
        self._cache: dict = store.load(CACHE, {})
        self._centre = centre
        if client is None:
            import httpx

            client = httpx.Client(timeout=20.0)
        self._client = client

    def minutes_from_centre(self, lat: float | None, lon: float | None) -> float | None:
        if lat is None or lon is None:
            return None

        key = f"{round(lat, _PRECISION)},{round(lon, _PRECISION)}"
        if key in self._cache:
            cached = self._cache[key]
            return None if cached == _MISS else cached

        minutes = self._query(lat, lon)
        self._cache[key] = _MISS if minutes is None else minutes
        self._store.save(CACHE, self._cache)
        return minutes

    def _query(self, lat: float, lon: float) -> float | None:
        # OSRM expects lon,lat — the opposite of the usual convention.
        coords = f"{self._centre[1]},{self._centre[0]};{lon},{lat}"
        url = OSRM_URL.format(coords=coords)
        try:
            response = self._client.get(url, params={"overview": "false"})
            payload = response.json()
            routes = payload.get("routes") or []
            if not routes:
                return None
            duration = routes[0].get("duration")
        except Exception:  # noqa: BLE001 - a routing outage must not fail a run
            return None

        if not isinstance(duration, (int, float)):
            return None
        return round(duration / 60.0, 1)
