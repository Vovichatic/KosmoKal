"""Орбитальные элементы МКС. Эпоха элементов и время публикации различаются."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..provenance import Record, OBSERVATION
from .base import HttpSource

ISS_NORAD = 25544


class IssElements(HttpSource):
    source_id = "celestrak.gp.iss"
    title = "GP-элементы МКС (NORAD 25544)"
    units = "TLE / OMM"
    cadence_s = 7200
    publication_lag_s = 1200
    kind = OBSERVATION
    homepage = "https://celestrak.org/NORAD/documentation/gp-data-formats.php"
    # Просим именно TLE. JSON/OMM CelesTrak не содержит TLE_LINE1/TLE_LINE2,
    # поэтому прежний адаптер успешно обновлялся, но расчёт продолжал молча
    # использовать демонстрационные элементы 2024 года.
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={ISS_NORAD}&FORMAT=tle"

    def _http_get(self, url: str) -> Any:
        import requests

        response = requests.get(url, headers={"User-Agent": "eva-risk/0.1"}, timeout=15)
        response.raise_for_status()
        lines = [line.strip() for line in response.text.splitlines() if line.strip()]
        line1 = next((line for line in lines if line.startswith("1 ")), None)
        line2 = next((line for line in lines if line.startswith("2 ")), None)
        if not line1 or not line2:
            raise ValueError("CelesTrak не вернул две строки TLE для МКС")
        return {"OBJECT_NAME": lines[0] if not lines[0].startswith("1 ") else "ISS (ZARYA)",
                "TLE_LINE1": line1, "TLE_LINE2": line2}

    def parse(self, payload: Any, fetched_at: datetime) -> list[Record]:
        rows = payload if isinstance(payload, list) else [payload]
        out = []
        for row in rows:
            if "EPOCH" in row:
                epoch = datetime.fromisoformat(row["EPOCH"].replace("Z", "+00:00"))
            else:
                # TLE: YYDDD.DDDDDDDD в колонках 19–32 первой строки.
                epoch_field = row["TLE_LINE1"][18:32]
                short_year = int(epoch_field[:2])
                year = 2000 + short_year if short_year < 57 else 1900 + short_year
                day = float(epoch_field[2:])
                epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1)
            out.append(Record(
                source_id=self.source_id, kind=OBSERVATION, units=self.units, url=self.url,
                payload=row, observed_at=epoch, issued_at=fetched_at, fetched_at=fetched_at,
                note="ЭПОХА элементов ≠ время публикации; для replay нужен CREATION_DATE"))
        return out
