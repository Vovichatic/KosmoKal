"""Траектория МКС и переход «внешний поток → условия на орбите».

SGP4 даёт положение по GP-элементам. Дальше два физических множителя:
  * жёсткость геомагнитного обрезания (штёрмеровское приближение + подавление в бурю);
  * геометрический фактор Южно-Атлантической аномалии.
Без них поток на геостационаре к орбите МКС не относится (критерий Т2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

RE_KM = 6378.137
# Приближённый центр и оси ЮАА на высоте ~400 км (эллипс в геогр. координатах).
SAA = {"lat0": -26.0, "lon0": -45.0, "a_lat": 20.0, "a_lon": 45.0}


@dataclass
class OrbitPoint:
    t: datetime
    lat_deg: float
    lon_deg: float
    alt_km: float

    @property
    def in_saa(self) -> bool:
        dlat = (self.lat_deg - SAA["lat0"]) / SAA["a_lat"]
        dlon = (((self.lon_deg - SAA["lon0"] + 180) % 360) - 180) / SAA["a_lon"]
        return dlat * dlat + dlon * dlon <= 1.0


def _gmst_rad(t: datetime) -> float:
    jd = t.timestamp() / 86400.0 + 2440587.5
    d = jd - 2451545.0
    gmst_h = (18.697374558 + 24.06570982441908 * d) % 24.0
    return math.radians(gmst_h * 15.0)


def propagate(tle_line1: str, tle_line2: str, times: list[datetime]) -> list[OrbitPoint]:
    from sgp4.api import Satrec, jday

    sat = Satrec.twoline2rv(tle_line1, tle_line2)
    pts: list[OrbitPoint] = []
    for t in times:
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute,
                      t.second + t.microsecond * 1e-6)
        err, r, _v = sat.sgp4(jd, fr)
        if err != 0:
            raise RuntimeError(f"SGP4 error {err} at {t.isoformat()}")
        theta = _gmst_rad(t)
        x = r[0] * math.cos(theta) + r[1] * math.sin(theta)
        y = -r[0] * math.sin(theta) + r[1] * math.cos(theta)
        z = r[2]
        lon = math.degrees(math.atan2(y, x))
        hyp = math.hypot(x, y)
        lat = math.degrees(math.atan2(z, hyp))
        alt = math.sqrt(x * x + y * y + z * z) - RE_KM
        pts.append(OrbitPoint(t, lat, ((lon + 180) % 360) - 180, alt))
    return pts


def geomagnetic_latitude(lat_deg: float, lon_deg: float) -> float:
    """Дипольное приближение: полюс на 80.65°N, 72.68°W (эпоха ~2020)."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    plat, plon = math.radians(80.65), math.radians(-72.68)
    s = (math.sin(lat) * math.sin(plat)
         + math.cos(lat) * math.cos(plat) * math.cos(lon - plon))
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def cutoff_rigidity_gv(lat_deg: float, lon_deg: float, alt_km: float, kp: float) -> float:
    """Вертикальная жёсткость обрезания, ГВ. Штёрмер + эмпирическое подавление в бурю.

    Rc = 14.5 · cos⁴(λm) / (r/Re)²  минус подавление, растущее с Kp.
    Модель приближённая; в выгрузке помечается как team_computation.
    """
    lam = math.radians(geomagnetic_latitude(lat_deg, lon_deg))
    r_ratio = (RE_KM + alt_km) / RE_KM
    rc = 14.5 * (math.cos(lam) ** 4) / (r_ratio ** 2)
    suppression = 0.54 * math.exp(0.32 * max(0.0, kp))
    return max(0.0, rc - suppression)


def transmission(rc_gv: float, energy_mev: float) -> float:
    """Доля протонов данной энергии, доходящих до точки орбиты: 0 или 1 по жёсткости."""
    e = energy_mev
    m = 938.272
    p_c = math.sqrt(e * e + 2 * e * m)     # МэВ
    rigidity_gv = p_c / 1000.0             # заряд 1, ГВ
    if rigidity_gv >= rc_gv:
        return 1.0
    # мягкий край вместо ступеньки: полутень обрезания
    return max(0.0, 1.0 - (rc_gv - rigidity_gv) / max(rc_gv, 1e-6))


def saa_factor(point: OrbitPoint) -> float:
    """Множитель мощности дозы в ЮАА относительно фона."""
    return 12.0 if point.in_saa else 1.0


def time_grid(start: datetime, hours: float, step_s: int = 60) -> list[datetime]:
    n = int(hours * 3600 / step_s) + 1
    return [start + timedelta(seconds=i * step_s) for i in range(n)]


def demo_tle() -> tuple[str, str]:
    """Резервные элементы для офлайн-демо. Эпоха — май 2024."""
    return (
        "1 25544U 98067A   24132.51782528  .00016717  00000-0  30103-3 0  9004",
        "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49682159 27492",
    )
