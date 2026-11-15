"""Mars reference constants and spherical geometry.

All map data used by MARS-X (Mars Trek tiles, MOLA MEGDR, the Mars 2020 CTX
DTM) is referenced to the IAU 2000 Mars *sphere* of radius 3396.19 km with
planetocentric latitude and east-positive longitude. We therefore do all
horizontal geometry on that sphere. Nothing here may fall back to Earth
(WGS84) constants.
"""
from __future__ import annotations

import math

MARS_RADIUS_M = 3_396_190.0      # IAU 2000 mean equatorial radius (sphere used by Trek/MOLA/CTX DTM)
MARS_GRAVITY = 3.721             # m/s^2, mean surface gravity
SOL_SECONDS = 88_775.244         # mean solar day
MARS_SEMI_MAJOR_AU = 1.523679
MARS_ECCENTRICITY = 0.0934
LS_PERIHELION_DEG = 251.0
SOLAR_CONSTANT_1AU = 1361.0      # W/m^2


def norm_lon(lon: float) -> float:
    """Normalise to east-positive [-180, 180)."""
    return (lon + 180.0) % 360.0 - 180.0


def lon360(lon: float) -> float:
    return lon % 360.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * MARS_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def great_circle_points(lon1: float, lat1: float, lon2: float, lat2: float, n: int) -> list[tuple[float, float]]:
    """n points (inclusive of both ends) along the great circle."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = haversine_m(lon1, lat1, lon2, lat2) / MARS_RADIUS_M
    if d < 1e-12 or n < 2:
        return [(lon1, lat1)] * max(n, 1)
    out = []
    for i in range(n):
        f = i / (n - 1)
        a = math.sin((1 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)
        x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
        y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
        z = a * math.sin(p1) + b * math.sin(p2)
        out.append((norm_lon(math.degrees(math.atan2(y, x))), math.degrees(math.atan2(z, math.hypot(x, y)))))
    return out


def deg_per_m_lat() -> float:
    return math.degrees(1.0 / MARS_RADIUS_M)


def deg_per_m_lon(lat: float) -> float:
    return math.degrees(1.0 / (MARS_RADIUS_M * max(0.01, math.cos(math.radians(lat)))))


def solar_flux_toa(ls_deg: float) -> float:
    """Top-of-atmosphere solar irradiance at Mars for areocentric longitude Ls (derived, W/m^2)."""
    nu = math.radians(ls_deg - LS_PERIHELION_DEG)
    r = MARS_SEMI_MAJOR_AU * (1 - MARS_ECCENTRICITY ** 2) / (1 + MARS_ECCENTRICITY * math.cos(nu))
    return SOLAR_CONSTANT_1AU / r ** 2
