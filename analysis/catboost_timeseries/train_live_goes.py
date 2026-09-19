#!/usr/bin/env python3
"""Train the deployable live GOES/Kp radiation-warning model.

Unlike the research model, this variant intentionally uses only telemetry that
the API can retrieve at inference time: one day of GOES integral proton flux,
the latest planetary Kp, and calendar features.  The target is whether either
DOSTEL instrument exceeds its local Q99 during the next six hours.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, precision_score, recall_score, roc_auc_score
from sklearn.linear_model import LogisticRegression


INPUT = Path("analysis/catboost_timeseries/output_extended/catboost_timeseries_dataset.csv.gz")
OUTPUT = Path("research/eva-risk/evarisk/assets")
TARGET = "target_high_q99_6h"
SOURCES = (
    "proton_flux_proxy_gt10_mev",
    "proton_flux_proxy_gt50_mev",
    "proton_flux_proxy_gt100_mev",
)
LAGS = ("5m", "15m", "30m", "1h", "3h", "6h", "12h", "1d")
ROLLS = ("1h", "6h", "1d")
FEATURES = [
    *SOURCES,
    "Kp",
    "latitude", "longitude", "altitude", "longitude_sin", "longitude_cos",
    "minute_of_day_sin", "minute_of_day_cos",
    "day_of_year_sin", "day_of_year_cos",
    *(f"{source}_lag_{lag}" for source in SOURCES for lag in LAGS),
    *(f"{source}_roll_{window}_{stat}"
      for source in SOURCES for window in ROLLS for stat in ("mean", "std", "min", "max")),
]


def choose_threshold(y_true: pd.Series, probability: np.ndarray) -> float:
    best = (float("-inf"), 0.5)
    for threshold in np.linspace(0.05, 0.95, 181):
        predicted = probability >= threshold
        precision = precision_score(y_true, predicted, zero_division=0)
        recall = recall_score(y_true, predicted, zero_division=0)
        if precision < 0.55:
            continue
        f2 = 5 * precision * recall / max(1e-12, 4 * precision + recall)
        if f2 > best[0]:
            best = (f2, float(threshold))
    return best[1]


def evaluate(y_true: pd.Series, probability: np.ndarray, threshold: float) -> dict:
    predicted = probability >= threshold
    return {
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "pr_auc": float(average_precision_score(y_true, probability)),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "threshold": threshold,
        "positive_rate": float(y_true.mean()),
        "rows": int(len(y_true)),
    }


def main() -> None:
    columns = ["timestamp", "split", TARGET, *FEATURES]
    data = pd.read_csv(INPUT, compression="gzip", usecols=columns, parse_dates=["timestamp"])
    # Both DOSTEL instruments share the external telemetry.  A live warning is
    # positive when either instrument enters its locally extreme regime.
    grouped = data.groupby(["timestamp", "split"], as_index=False).agg(
        {TARGET: "max", **{feature: "first" for feature in FEATURES}}
    )
    train = grouped[grouped["split"] == "train"]
    valid = grouped[grouped["split"] == "valid"]
    test = grouped[grouped["split"] == "test"]

    selector = CatBoostClassifier(
        iterations=500, depth=6, learning_rate=0.04, loss_function="Logloss",
        eval_metric="AUC", random_seed=42, l2_leaf_reg=8,
        allow_writing_files=False, verbose=100, od_type="Iter", od_wait=60,
    )
    selector.fit(train[FEATURES], train[TARGET], eval_set=(valid[FEATURES], valid[TARGET]), use_best_model=True)
    valid_raw = selector.predict_proba(valid[FEATURES])[:, 1]
    calibrator = LogisticRegression(random_state=42).fit(valid_raw.reshape(-1, 1), valid[TARGET])
    valid_probability = calibrator.predict_proba(valid_raw.reshape(-1, 1))[:, 1]
    threshold = choose_threshold(valid[TARGET], valid_probability)
    iterations = max(1, selector.get_best_iteration() + 1)
    test_raw = selector.predict_proba(test[FEATURES])[:, 1]
    test_probability = calibrator.predict_proba(test_raw.reshape(-1, 1))[:, 1]
    metadata = {
        "model": "catboost-goes-kp-q99-6h-live-v1",
        "target": "either DOSTEL local-Q99 exceedance in the next 6 hours",
        "features": FEATURES,
        "history_h": 24,
        "horizon_h": 6,
        "iterations": iterations,
        "calibration": {
            "kind": "platt",
            "coefficient": float(calibrator.coef_[0, 0]),
            "intercept": float(calibrator.intercept_[0]),
        },
        "validation": evaluate(valid[TARGET], valid_probability, threshold),
        "test": evaluate(test[TARGET], test_probability, threshold),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    selector.save_model(OUTPUT / "live_goes_q99_6h.cbm")
    (OUTPUT / "live_goes_q99_6h.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
