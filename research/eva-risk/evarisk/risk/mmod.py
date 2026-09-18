"""Линия B: микрометеороиды, мусор и сближения.

Пуассоновская модель: вероятность отсутствия пробоя PNP = exp(-F·A·T).
Здесь длительность работ входит явно — единственная компонента, где
сокращение ВКД даёт точно предсказуемый выигрыш.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..provenance import Record, Store, TEAM_COMPUTATION

SEC_PER_YEAR = 3.155_76e7
DEFAULT_FLUX_PER_M2_YEAR = 3.0   # частицы выше баллистического предела скафандра
DEFAULT_AREA_M2 = 2.0            # скафандр + ранец, эффективная площадь
PNP_REQUIREMENT = 0.995          # типовое требование на один выход
TCA_GUARD_MIN = 30.0             # окно исключения вокруг момента сближения


def pnp(duration_h: float,
        flux_per_m2_year: float = DEFAULT_FLUX_PER_M2_YEAR,
        area_m2: float = DEFAULT_AREA_M2) -> float:
    n = flux_per_m2_year / SEC_PER_YEAR * area_m2 * duration_h * 3600.0
    return math.exp(-n)


@dataclass
class MmodAssessment:
    pnp: float
    p_penetration: float
    meets_requirement: bool
    conjunction_overlap_min: float
    conjunctions: list[dict]
    record: Record


def assess_mmod(
    start: datetime,
    duration_h: float,
    conjunctions: list[dict] | None = None,
    flux_per_m2_year: float = DEFAULT_FLUX_PER_M2_YEAR,
    area_m2: float = DEFAULT_AREA_M2,
    parents: tuple[str, ...] = (),
    store: Store | None = None,
) -> MmodAssessment:
    p_no = pnp(duration_h, flux_per_m2_year, area_m2)
    end = start + timedelta(hours=duration_h)

    overlap_min = 0.0
    hits: list[dict] = []
    for c in conjunctions or []:
        tca: datetime = c["tca"]
        lo = tca - timedelta(minutes=TCA_GUARD_MIN)
        hi = tca + timedelta(minutes=TCA_GUARD_MIN)
        a, b = max(lo, start), min(hi, end)
        if b > a:
            mins = (b - a).total_seconds() / 60.0
            overlap_min += mins
            hits.append({**c, "overlap_min": mins})

    rec = Record(
        source_id="team.mmod", kind=TEAM_COMPUTATION, units="вероятность / мин",
        payload={"pnp": p_no, "duration_h": duration_h,
                 "flux_per_m2_year": flux_per_m2_year, "area_m2": area_m2,
                 "conjunction_overlap_min": overlap_min},
        observed_at=start, issued_at=start, parents=parents,
        note=("Pc сближения относится к станции и каталожному объекту; "
              "это НЕ вероятность попадания фрагмента в космонавта"))
    if store is not None:
        store.put(rec)

    return MmodAssessment(
        pnp=p_no, p_penetration=1.0 - p_no,
        meets_requirement=p_no >= PNP_REQUIREMENT,
        conjunction_overlap_min=overlap_min, conjunctions=hits, record=rec)
