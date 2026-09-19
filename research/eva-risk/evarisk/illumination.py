"""Cylindrical Earth shadow, low precision solar ephemeris (planning constraint).

Meeus-style solar longitude approximation; no external ephemeris download.
This models lighting, not thermal injury. Boundary precision is the sampling step.
"""
import math
from .orbit import _gmst_rad, RE_KM


def sun_unit_ecef(t):
    d = t.timestamp() / 86400 + 2440587.5 - 2451545.0
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    longitude = math.radians((280.459 + 0.98564736 * d + 1.915 * math.sin(g)
                              + 0.020 * math.sin(2 * g)) % 360)
    obliquity = math.radians(23.439 - 0.00000036 * d)
    x, y, z = math.cos(longitude), math.cos(obliquity) * math.sin(longitude), math.sin(obliquity) * math.sin(longitude)
    theta = _gmst_rad(t)
    return (x * math.cos(theta) + y * math.sin(theta),
            -x * math.sin(theta) + y * math.cos(theta), z)


def in_shadow(point):
    lat, lon = math.radians(point.lat_deg), math.radians(point.lon_deg)
    radius = RE_KM + point.alt_km
    vector = (radius * math.cos(lat) * math.cos(lon), radius * math.cos(lat) * math.sin(lon), radius * math.sin(lat))
    sun = sun_unit_ecef(point.t)
    along = sum(a * b for a, b in zip(vector, sun))
    return along < 0 and radius * radius - along * along < RE_KM * RE_KM


def state_intervals(points, predicate):
    """Half-open cells; total exposure never exceeds the requested duration."""
    result = []
    for left, right in zip(points, points[1:]):
        if not predicate(left):
            continue
        if result and result[-1][1] == left.t:
            result[-1] = (result[-1][0], right.t)
        else:
            result.append((left.t, right.t))
    return result
