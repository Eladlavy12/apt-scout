from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from .drivetime import CENTRE

_EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres.

    Pure math, no network — used as a hard straight-line cap alongside the
    OSRM drive-time filter, which alone lets far-away addresses slip through
    on the free-flow (no-traffic) time estimate.
    """
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    d_lat = lat2_r - lat1_r
    d_lon = lon2_r - lon1_r
    a = sin(d_lat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(d_lon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(a))


def distance_from_centre_km(
    lat: float | None, lon: float | None, centre: tuple[float, float] = CENTRE
) -> float | None:
    """Straight-line distance from the centre point, or None when unknown."""
    if lat is None or lon is None:
        return None
    return round(haversine_km(centre[0], centre[1], lat, lon), 2)
