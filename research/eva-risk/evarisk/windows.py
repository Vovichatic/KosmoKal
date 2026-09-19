"""Сравнение окон ВКД: вектор из четырёх компонент и Парето-фронт.

Скалярной «оценки опасности» нет. Если два окна несравнимы — так и говорим,
вместо того чтобы выдумывать победителя (критерий О3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .orbit import OrbitPoint, propagate, time_grid
from .provenance import Record, Store, TEAM_COMPUTATION
from .risk import assess_mmod, assess_space_weather, fuse

# Веса фаз ВКД: насколько космонавт уязвим именно в этой фазе (граф 2).
PHASES = [
    ("преддыхание", 2.0, 0.2),
    ("шлюзование", 40 / 60, 0.6),
    ("работа 1", 2.0, 1.0),
    ("работа 2", 2.0, 1.0),
    ("возврат", 40 / 60, 0.6),
]


def phase_profile(n_points: int, duration_h: float) -> list[float]:
    """Вес уязвимости по точкам сетки, растянутый на фактическую длительность."""
    total = sum(p[1] for p in PHASES)
    out: list[float] = []
    for i in range(n_points):
        frac = i / max(1, n_points - 1)
        acc = 0.0
        w = PHASES[-1][2]
        for _name, dur, weight in PHASES:
            acc += dur / total
            if frac <= acc:
                w = weight
                break
        out.append(w)
    return out


@dataclass
class WindowScore:
    start: datetime
    duration_h: float
    dose_usv: float
    p_penetration: float
    conjunction_overlap_min: float
    completeness: float
    weather_combined: float
    kp_max: float
    saa_minutes: float
    explanation: str
    record: Record | None = None
    dominated_by: list[datetime] = field(default_factory=list)

    @property
    def objectives(self) -> tuple[float, float, float, float]:
        """Меньше — лучше по первым трём, больше — лучше по полноте."""
        return (self.dose_usv, self.p_penetration,
                self.conjunction_overlap_min, -self.completeness)

    def dominates(self, other: "WindowScore") -> bool:
        a, b = self.objectives, other.objectives
        return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def completeness(statuses: dict[str, bool], ages_s: dict[str, float],
                 staleness_limit_s: dict[str, float]) -> float:
    """Доля механизмов, обеспеченных достаточно свежими данными."""
    if not statuses:
        return 0.0
    ok = 0
    for sid, usable in statuses.items():
        if not usable:
            continue
        age = ages_s.get(sid)
        limit = staleness_limit_s.get(sid, 6 * 3600)
        if age is not None and 0 <= age <= limit:
            ok += 1
    return ok / len(statuses)


def score_window(
    start: datetime,
    duration_h: float,
    tle: tuple[str, str],
    proton_records: list[Record],
    kp_records: list[Record],
    scales: dict[str, int | None],
    conjunctions: list[dict],
    data_completeness: float,
    store: Store | None = None,
    step_s: int = 60,
    include_micrometeoroids: bool = True,
    include_debris: bool = True,
) -> WindowScore:
    grid = time_grid(start, duration_h, step_s)
    points: list[OrbitPoint] = propagate(tle[0], tle[1], grid)
    weights = phase_profile(len(points), duration_h)

    sw = assess_space_weather(points, proton_records, kp_records, weights, store)
    mm = assess_mmod(
        start, duration_h, conjunctions if include_debris else [],
        flux_per_m2_year=3.0 if include_micrometeoroids else 0.0,
        parents=(sw.record.hash,), store=store,
    )
    severity = min(1.0, sw.dose_usv / 500.0)
    fz = fuse(scales, mm.p_penetration, severity)

    expl = (
        f"доза-прокси {sw.dose_usv:.0f} мкЗв за {duration_h:.1f} ч; "
        f"P(пробой) {mm.p_penetration:.2e}; "
        f"пересечение с TCA {mm.conjunction_overlap_min:.0f} мин; "
        f"полнота данных {data_completeness:.0%}. {fz.explanation}"
    )
    rec = None
    if store is not None:
        rec = Record(
            source_id="team.window", kind=TEAM_COMPUTATION, units="вектор оценок",
            payload={"start": start.isoformat(), "duration_h": duration_h,
                     "dose_usv": sw.dose_usv, "pnp": mm.pnp,
                     "overlap_min": mm.conjunction_overlap_min,
                     "completeness": data_completeness,
                     "weather_combined": fz.combined_weather},
            observed_at=start, issued_at=start,
            parents=(sw.record.hash, mm.record.hash))
        store.put(rec)

    return WindowScore(
        start=start, duration_h=duration_h, dose_usv=sw.dose_usv,
        p_penetration=mm.p_penetration,
        conjunction_overlap_min=mm.conjunction_overlap_min,
        completeness=data_completeness, weather_combined=fz.combined_weather,
        kp_max=sw.kp_max, saa_minutes=sw.saa_minutes, explanation=expl, record=rec)


def pareto_front(scores: list[WindowScore]) -> list[WindowScore]:
    front: list[WindowScore] = []
    for s in scores:
        dominators = [o.start for o in scores if o is not s and o.dominates(s)]
        s.dominated_by = dominators
        if not dominators:
            front.append(s)
    return front


MIN_COMPLETENESS = 1.0


def recommend(scores: list[WindowScore]) -> dict:
    """Три допустимых исхода, включая честное «оснований недостаточно»."""
    front = pareto_front(scores)
    if not front:
        return {"verdict": "нет данных", "front": [], "reason": "окна не рассчитаны"}
    if max(s.completeness for s in front) < MIN_COMPLETENESS:
        return {"verdict": "оснований для выбора недостаточно", "front": front,
                "reason": ("ни по одному окну нет достаточно свежих данных "
                           "по обоим механизмам")}
    if len(front) == 1:
        return {"verdict": "рекомендуется окно", "front": front,
                "choice": front[0], "reason": front[0].explanation}
    return {"verdict": "варианты требуют выбора компромисса", "front": front,
            "reason": ("окна не доминируют друг друга: "
                       + "; ".join(f"{s.start:%H:%M} — доза {s.dose_usv:.0f} мкЗв, "
                                   f"пересечение {s.conjunction_overlap_min:.0f} мин"
                                   for s in front[:4]))}


def candidate_starts(earliest: datetime, search_h: float,
                     step_min: int = 30) -> list[datetime]:
    n = int(search_h * 60 / step_min) + 1
    return [earliest + timedelta(minutes=i * step_min) for i in range(n)]
