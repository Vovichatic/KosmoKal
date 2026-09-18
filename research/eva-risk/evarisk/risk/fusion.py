"""Байесовская сеть: связанные сигналы не увеличивают риск несколько раз.

Шкалы NOAA S, G и R часто порождены одной вспышкой. Складывать их баллы
значит завысить риск втрое. Сеть с явным узлом общей причины этого не делает.

Структура (граф 1 документа):
    flare -> radio_blackout (R)
    flare -> sep (S)
    flare -> cme -> geomagnetic (G)
"""
from __future__ import annotations

from dataclasses import dataclass, field

# P(эффект | вспышка есть/нет). Калибруется по архиву; значения — стартовые.
CPT = {
    "radio_blackout": {True: 0.75, False: 0.02},
    "sep":            {True: 0.35, False: 0.01},
    "cme":            {True: 0.55, False: 0.05},
}
P_GEO_GIVEN_CME = {True: 0.60, False: 0.04}
P_FLARE_PRIOR = 0.08


@dataclass
class FusionResult:
    p_flare: float
    per_mechanism: dict[str, float]
    combined_weather: float
    naive_sum: float
    double_counting_avoided: float
    explanation: str
    components: dict[str, float] = field(default_factory=dict)


class CausalNet:
    """Точный вывод перебором: сеть из пяти узлов, MCMC не нужен."""

    def posterior_flare(self, obs: dict[str, bool]) -> float:
        num = den = 0.0
        for flare in (True, False):
            p = P_FLARE_PRIOR if flare else 1 - P_FLARE_PRIOR
            for effect in ("radio_blackout", "sep"):
                if effect in obs:
                    pe = CPT[effect][flare]
                    p *= pe if obs[effect] else 1 - pe
            if "geomagnetic" in obs:
                pg = 0.0
                for cme in (True, False):
                    pc = CPT["cme"][flare] if cme else 1 - CPT["cme"][flare]
                    pe = P_GEO_GIVEN_CME[cme]
                    pg += pc * (pe if obs["geomagnetic"] else 1 - pe)
                p *= pg
            den += p
            if flare:
                num += p
        return num / den if den else 0.0

    def fuse(self, scales: dict[str, int | None], mmod_p: float,
             sw_severity: float) -> FusionResult:
        obs = {
            "radio_blackout": bool(scales.get("R")),
            "sep": bool(scales.get("S")),
            "geomagnetic": bool(scales.get("G")),
        }
        p_flare = self.posterior_flare(obs)

        # Вклад каждого механизма после вывода по сети: общая причина
        # объясняет сигналы, поэтому вклад НЕ равен сумме отдельных тревог.
        per: dict[str, float] = {}
        for key, name in (("S", "sep"), ("G", "geomagnetic"), ("R", "radio_blackout")):
            level = scales.get(key) or 0
            raw = min(1.0, level / 5.0)
            shared = p_flare * CPT["sep" if name == "sep" else
                                   ("cme" if name == "geomagnetic" else
                                    "radio_blackout")][True]
            per[name] = raw * (1.0 - 0.5 * shared)

        per["sep"] = max(per["sep"], min(1.0, sw_severity))

        # noisy-OR по механизмам космической погоды
        combined = 1.0
        for v in per.values():
            combined *= (1.0 - v)
        combined = 1.0 - combined

        naive = min(1.0, sum(per.values()))
        expl = (
            f"апостериорная вероятность общей вспышки {p_flare:.2f}; "
            f"noisy-OR по погоде {combined:.3f} против наивной суммы {naive:.3f}"
        )
        return FusionResult(
            p_flare=p_flare, per_mechanism=per, combined_weather=combined,
            naive_sum=naive, double_counting_avoided=max(0.0, naive - combined),
            explanation=expl,
            # MMOD остаётся ОТДЕЛЬНОЙ компонентой и не сливается с погодой
            components={"weather": combined, "mmod": mmod_p})


def fuse(scales: dict[str, int | None], mmod_p: float, sw_severity: float) -> FusionResult:
    return CausalNet().fuse(scales, mmod_p, sw_severity)
