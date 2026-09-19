"""Inference adapter for the validated historical radiation model.

The shipped table contains out-of-sample CatBoost predictions for the official
May-June 2024 holdout.  Keeping inference results next to the API makes the
demo fast and reproducible without loading a multi-gigabyte feature table on
every server start.
"""
from __future__ import annotations

import csv
import gzip
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


MODEL_ID = "catboost-q99-6h-high-recall"
THRESHOLD = 0.24403569575955641
ASSET = Path(__file__).with_name("assets") / "radiation_forecast_2024.csv.gz"


@dataclass(frozen=True)
class RadiationForecast:
    timestamp: datetime
    probability: float
    observed: bool

    def as_dict(self) -> dict:
        is_alert = self.probability >= THRESHOLD
        return {
            "model": MODEL_ID,
            "horizon_h": 6,
            "probability": round(self.probability, 4),
            "threshold": round(THRESHOLD, 4),
            "alert": is_alert,
            "level": "high" if self.probability >= 0.65 else "elevated" if is_alert else "low",
            "matched_at": self.timestamp.isoformat(),
            "observed_high_risk": self.observed,
            "metrics": {"recall": 0.8564, "precision": 0.7028, "pr_auc": 0.8614},
            "scope": "out-of-sample historical replay, 2024-05-01..2024-06-30",
        }


class HistoricalRadiationForecaster:
    def __init__(self, path: Path = ASSET) -> None:
        self.path = path
        self._times: list[datetime] = []
        self._rows: dict[datetime, RadiationForecast] = {}
        if not path.exists():
            return
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                timestamp = datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc)
                self._times.append(timestamp)
                self._rows[timestamp] = RadiationForecast(
                    timestamp=timestamp,
                    probability=float(row["probability"]),
                    observed=row["observed_high_risk"] == "1",
                )
        self._times.sort()

    @property
    def available(self) -> bool:
        return bool(self._times)

    def predict(self, moment: datetime) -> RadiationForecast | None:
        if not self._times:
            return None
        moment = moment.astimezone(timezone.utc)
        index = bisect_left(self._times, moment)
        candidates = self._times[max(0, index - 1):min(len(self._times), index + 1)]
        if not candidates:
            return None
        nearest = min(candidates, key=lambda value: abs(value - moment))
        if abs(nearest - moment).total_seconds() > 5 * 60:
            return None
        return self._rows[nearest]

    def status(self) -> dict:
        return {
            "available": self.available,
            "model": MODEL_ID,
            "horizon_h": 6,
            "threshold": round(THRESHOLD, 4),
            "coverage": {
                "start": self._times[0].isoformat() if self._times else None,
                "end": self._times[-1].isoformat() if self._times else None,
            },
        }


@lru_cache(maxsize=1)
def radiation_forecaster() -> HistoricalRadiationForecaster:
    return HistoricalRadiationForecaster()
