"""Источники NOAA SWPC. Единицы, каденция и задержка публикации объявлены явно."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..provenance import Record, OBSERVATION, EXTERNAL_FORECAST
from .base import HttpSource


def _ts(raw: str) -> datetime:
    raw = raw.strip().replace("Z", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"не разобрано время: {raw!r}")


class GoesProtons(HttpSource):
    source_id = "swpc.goes.protons"
    title = "GOES SEISS, интегральный поток протонов"
    units = "pfu (частиц·см⁻²·с⁻¹·ср⁻¹)"
    cadence_s = 300
    publication_lag_s = 180
    kind = OBSERVATION
    homepage = "https://services.swpc.noaa.gov/json/goes/primary/"
    url = "https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json"

    def parse(self, payload: Any, fetched_at: datetime) -> list[Record]:
        out: list[Record] = []
        for row in payload:
            if str(row.get("energy", "")).strip() not in (">=10 MeV", ">=50 MeV", ">=100 MeV"):
                continue
            t = _ts(row["time_tag"])
            out.append(Record(
                source_id=self.source_id, kind=OBSERVATION, units=self.units,
                url=self.url,
                payload={"energy": row["energy"], "flux": float(row["flux"]),
                         "satellite": row.get("satellite")},
                observed_at=t, issued_at=t, fetched_at=fetched_at,
                note="поток на геостационаре; связь с орбитой МКС требует модели обрезания",
            ))
        return out


class PlanetaryKp(HttpSource):
    source_id = "swpc.kp"
    title = "Планетарный K-индекс"
    units = "Kp, 0–9"
    cadence_s = 60
    publication_lag_s = 120
    kind = OBSERVATION
    homepage = "https://services.swpc.noaa.gov/json/"
    url = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"

    def parse(self, payload: Any, fetched_at: datetime) -> list[Record]:
        out = []
        for row in payload:
            t = _ts(row["time_tag"])
            out.append(Record(
                source_id=self.source_id, kind=OBSERVATION, units=self.units, url=self.url,
                payload={"kp": float(row.get("kp_index", row.get("estimated_kp", 0)))},
                observed_at=t, issued_at=t, fetched_at=fetched_at))
        return out


class SwpcAlerts(HttpSource):
    source_id = "swpc.alerts"
    title = "Предупреждения и сводки SWPC"
    units = "текст, шкалы S/G/R"
    cadence_s = 900
    publication_lag_s = 300
    kind = EXTERNAL_FORECAST
    homepage = "https://services.swpc.noaa.gov/products/alerts.json"
    url = "https://services.swpc.noaa.gov/products/alerts.json"

    def parse(self, payload: Any, fetched_at: datetime) -> list[Record]:
        out = []
        for row in payload:
            issued = _ts(row["issue_datetime"])
            msg = row.get("message", "")
            out.append(Record(
                source_id=self.source_id, kind=EXTERNAL_FORECAST, units=self.units,
                url=self.url,
                payload={"product_id": row.get("product_id"), "message": msg,
                         "scales": _scales(msg)},
                issued_at=issued, observed_at=issued, fetched_at=fetched_at,
                note="внешний прогноз, не наш расчёт"))
        return out


def _scales(message: str) -> dict[str, int | None]:
    """Грубый разбор шкал S/G/R из текста бюллетеня."""
    res: dict[str, int | None] = {"S": None, "G": None, "R": None}
    up = message.upper()
    for letter in res:
        for level in range(5, 0, -1):
            if f"{letter}{level}" in up:
                res[letter] = level
                break
    return res
