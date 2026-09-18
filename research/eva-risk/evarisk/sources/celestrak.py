"""Орбитальные элементы МКС. Эпоха элементов и время публикации различаются."""
from __future__ import annotations

from datetime import datetime, timezone
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
    url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={ISS_NORAD}&FORMAT=json"

    def parse(self, payload: Any, fetched_at: datetime) -> list[Record]:
        rows = payload if isinstance(payload, list) else [payload]
        out = []
        for row in rows:
            epoch = datetime.fromisoformat(row["EPOCH"].replace("Z", "")).replace(
                tzinfo=timezone.utc)
            out.append(Record(
                source_id=self.source_id, kind=OBSERVATION, units=self.units, url=self.url,
                payload=row, observed_at=epoch, issued_at=fetched_at, fetched_at=fetched_at,
                note="ЭПОХА элементов ≠ время публикации; для replay нужен CREATION_DATE"))
        return out
