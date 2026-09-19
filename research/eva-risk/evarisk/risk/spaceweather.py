"""Линия A: космическая погода. Собственный расчёт, не пересказ предупреждения."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..orbit import OrbitPoint, cutoff_rigidity_gv, saa_factor, transmission
from ..provenance import Record, Store, TEAM_COMPUTATION

# Репрезентативные энергии каналов GOES и их вес в мощности дозы за скафандром.
CHANNELS = {">=10 MeV": (10.0, 0.15), ">=50 MeV": (50.0, 0.35), ">=100 MeV": (100.0, 0.50)}
BASELINE_USV_H = 20.0  # фоновая мощность дозы вне ЮАА и вне события, мкЗв/ч


@dataclass
class SpaceWeatherAssessment:
    hazard: list[float]            # мощность дозы, мкЗв/ч, по точкам сетки
    dose_usv: float                # интеграл по окну с весами фаз
    peak_usv_h: float
    saa_minutes: float
    kp_max: float
    record: Record


def _flux_at(records: list[Record], t: datetime, energy_label: str) -> float:
    best, best_dt = 0.0, None
    for r in records:
        if r.payload.get("energy") != energy_label or r.observed_at is None:
            continue
        dt = (t - r.observed_at).total_seconds()
        if dt < 0:
            continue
        if best_dt is None or dt < best_dt:
            best, best_dt = float(r.payload["flux"]), dt
    return best


def _kp_at(records: list[Record], t: datetime) -> float:
    best, best_dt = 0.0, None
    for r in records:
        if r.observed_at is None:
            continue
        dt = (t - r.observed_at).total_seconds()
        if dt < 0:
            continue
        if best_dt is None or dt < best_dt:
            best, best_dt = float(r.payload["kp"]), dt
    return best


def assess_space_weather(
    points: list[OrbitPoint],
    proton_records: list[Record],
    kp_records: list[Record],
    phase_weights: list[float],
    store: Store | None = None,
) -> SpaceWeatherAssessment:
    """Мощность дозы по траектории = фон·ЮАА + вклад SEP через обрезание."""
    hazard: list[float] = []
    kp_max = 0.0
    saa_points = 0
    parents: set[str] = set()

    for p in points:
        kp = _kp_at(kp_records, p.t)
        kp_max = max(kp_max, kp)
        rc = cutoff_rigidity_gv(p.lat_deg, p.lon_deg, p.alt_km, kp)
        sep = 0.0
        for label, (energy, weight) in CHANNELS.items():
            flux = _flux_at(proton_records, p.t, label)
            sep += weight * flux * transmission(rc, energy)
        saa = saa_factor(p)
        if p.in_saa:
            saa_points += 1
        hazard.append(BASELINE_USV_H * saa + sep)

    for r in proton_records + kp_records:
        parents.add(r.hash)

    step_h = 0.0
    if len(points) > 1:
        step_h = (points[1].t - points[0].t).total_seconds() / 3600.0
    weighted = [h * w for h, w in zip(hazard, phase_weights)]
    dose = sum((a + b) / 2 for a, b in zip(weighted, weighted[1:])) * step_h

    rec = Record(
        source_id="team.spaceweather", kind=TEAM_COMPUTATION, units="мкЗв (прокси)",
        payload={"dose_usv": dose, "peak_usv_h": max(hazard) if hazard else 0.0,
                 "kp_max": kp_max, "saa_points": saa_points},
        observed_at=points[0].t if points else None,
        issued_at=points[0].t if points else None,
        parents=tuple(sorted(parents)),
        note=("прокси-оценка внешней обстановки на траектории, "
              "НЕ доза конкретного человека и не допуск к ВКД"))
    if store is not None:
        store.put(rec)

    return SpaceWeatherAssessment(
        hazard=hazard, dose_usv=dose, peak_usv_h=max(hazard) if hazard else 0.0,
        saa_minutes=saa_points * step_h * 60, kp_max=kp_max, record=rec)
