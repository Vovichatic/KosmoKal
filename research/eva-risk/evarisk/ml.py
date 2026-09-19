"""Inference adapter for the validated historical radiation model.

The shipped table contains out-of-sample CatBoost predictions for the official
May-June 2024 holdout.  Keeping inference results next to the API makes the
demo fast and reproducible without loading a multi-gigabyte feature table on
every server start.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import statistics
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .orbit import propagate


MODEL_ID = "catboost-q99-6h-high-recall"
THRESHOLD = 0.24403569575955641
ASSET = Path(__file__).with_name("assets") / "radiation_forecast_2024.csv.gz"
LIVE_MODEL = Path(__file__).with_name("assets") / "live_goes_q99_6h.cbm"
LIVE_METADATA = Path(__file__).with_name("assets") / "live_goes_q99_6h.json"
ENERGY_TO_FEATURE = {
    ">=10 MeV": "proton_flux_proxy_gt10_mev",
    ">=50 MeV": "proton_flux_proxy_gt50_mev",
    ">=100 MeV": "proton_flux_proxy_gt100_mev",
}
LAG_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "3h": 180,
               "6h": 360, "12h": 720, "1d": 1440}
ROLL_MINUTES = {"1h": 60, "6h": 360, "1d": 1440}


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


class LiveRadiationForecaster:
    """Build deployable features from NOAA records and run CatBoost locally."""

    def __init__(self, model_path: Path = LIVE_MODEL, metadata_path: Path = LIVE_METADATA) -> None:
        self.model = None
        self.metadata: dict[str, Any] = {}
        if not model_path.exists() or not metadata_path.exists():
            return
        try:
            from catboost import CatBoostClassifier

            self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.model = CatBoostClassifier()
            self.model.load_model(model_path)
        except (ImportError, OSError, ValueError):
            self.model = None

    @property
    def available(self) -> bool:
        return self.model is not None

    @staticmethod
    def _nearest(history: list[tuple[datetime, float]], moment: datetime,
                 tolerance_min: float = 20.0) -> float:
        if not history:
            return math.nan
        timestamp, value = min(history, key=lambda item: abs(item[0] - moment))
        return value if abs(timestamp - moment).total_seconds() <= tolerance_min * 60 else math.nan

    def predict(self, moment: datetime, proton_records: list, kp_records: list,
                tle: tuple[str, str]) -> dict | None:
        results = self.predict_many([moment], proton_records, kp_records, tle)
        return results[0] if results else None

    def predict_many(self, moments: list[datetime], proton_records: list,
                     kp_records: list, tle: tuple[str, str]) -> list[dict | None]:
        if not self.available:
            return [None for _ in moments]
        moments = [moment.astimezone(timezone.utc) for moment in moments]
        if not moments:
            return []
        cutoff = min(moments)
        histories: dict[str, list[tuple[datetime, float]]] = {value: [] for value in ENERGY_TO_FEATURE.values()}
        for record in proton_records:
            feature = ENERGY_TO_FEATURE.get(str(record.payload.get("energy", "")).strip())
            if feature and record.observed_at is not None and record.observed_at <= cutoff:
                histories[feature].append((record.observed_at.astimezone(timezone.utc), float(record.payload["flux"])))
        for values in histories.values():
            values.sort(key=lambda item: item[0])
        available_times = [timestamp for values in histories.values() for timestamp, _ in values]
        if not available_times or any(not values for values in histories.values()):
            return [None for _ in moments]
        anchor = min(max(values, key=lambda item: item[0])[0] for values in histories.values())
        base_values: dict[str, float] = {}
        usable_kp = [record for record in kp_records if record.observed_at and record.observed_at <= anchor]
        base_values["Kp"] = float(max(usable_kp, key=lambda record: record.observed_at).payload["kp"]) if usable_kp else math.nan

        for source, history in histories.items():
            base_values[source] = self._nearest(history, anchor)
            for label, minutes in LAG_MINUTES.items():
                base_values[f"{source}_lag_{label}"] = self._nearest(history, anchor - timedelta(minutes=minutes))
            for label, minutes in ROLL_MINUTES.items():
                window = [value for timestamp, value in history
                          if anchor - timedelta(minutes=minutes) <= timestamp < anchor]
                base_values[f"{source}_roll_{label}_mean"] = statistics.fmean(window) if window else math.nan
                base_values[f"{source}_roll_{label}_std"] = statistics.stdev(window) if len(window) > 1 else math.nan
                base_values[f"{source}_roll_{label}_min"] = min(window) if window else math.nan
                base_values[f"{source}_roll_{label}_max"] = max(window) if window else math.nan

        features = self.metadata["features"]
        rows: list[list[float]] = []
        for moment, point in zip(moments, propagate(tle[0], tle[1], moments)):
            minute = moment.hour * 60 + moment.minute
            day = moment.timetuple().tm_yday + minute / 1440.0
            values = dict(base_values)
            values.update({
                "latitude": point.lat_deg,
                "longitude": point.lon_deg,
                "altitude": point.alt_km,
                "longitude_sin": math.sin(math.radians(point.lon_deg)),
                "longitude_cos": math.cos(math.radians(point.lon_deg)),
                "minute_of_day_sin": math.sin(2 * math.pi * minute / 1440),
                "minute_of_day_cos": math.cos(2 * math.pi * minute / 1440),
                "day_of_year_sin": math.sin(2 * math.pi * day / 365.25),
                "day_of_year_cos": math.cos(2 * math.pi * day / 365.25),
            })
            rows.append([values.get(name, math.nan) for name in features])
        raw_probabilities = self.model.predict_proba(rows)[:, 1]
        calibration = self.metadata.get("calibration", {})
        threshold = float(self.metadata["validation"]["threshold"])
        results: list[dict] = []
        for moment, raw_probability in zip(moments, raw_probabilities):
            if calibration.get("kind") == "platt":
                z = calibration["coefficient"] * float(raw_probability) + calibration["intercept"]
                probability = 1.0 / (1.0 + math.exp(-z))
            else:
                probability = float(raw_probability)
            lead_h = max(0.0, (moment - anchor).total_seconds() / 3600)
            confidence = "high" if lead_h <= 6 else "medium" if lead_h <= 12 else "low"
            results.append({
                "model": self.metadata["model"],
                "horizon_h": self.metadata["horizon_h"],
                "probability": round(probability, 4),
                "threshold": round(threshold, 4),
                "alert": probability >= threshold,
                "level": "high" if probability >= 0.7 else "elevated" if probability >= threshold else "low",
                "matched_at": anchor.isoformat(),
                "telemetry_age_min": round((moment - anchor).total_seconds() / 60, 1),
                "projection": lead_h > 0.25,
                "confidence": confidence,
                "metrics": self.metadata["test"],
                "scope": "live GOES/Kp + SGP4; external telemetry is persisted for future candidate windows",
            })
        return results

    def status(self) -> dict:
        test = self.metadata.get("test", {})
        return {
            "available": self.available,
            "model": self.metadata.get("model"),
            "horizon_h": self.metadata.get("horizon_h"),
            "history_h": self.metadata.get("history_h"),
            "threshold": round(float(self.metadata.get("validation", {}).get("threshold", 0)), 4),
            "test": test,
        }


@lru_cache(maxsize=1)
def live_radiation_forecaster() -> LiveRadiationForecaster:
    return LiveRadiationForecaster()
