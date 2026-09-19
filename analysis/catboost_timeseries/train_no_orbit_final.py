#!/usr/bin/env python3
"""Train the validation-selected no-orbit variant on the prepared long dataset."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score


INPUT = Path("analysis/catboost_timeseries/output_extended/catboost_timeseries_dataset.csv.gz")
OUTPUT = Path("analysis/catboost_timeseries/output_no_orbit")
TARGET = "target_high_q99_6h"
CATEGORICAL = ["instrument_id", "Kp_status", "Dst_status"]
ORBIT_LABELS = ("90m", "95m", "100m", "190m", "285m", "380m")


def choose_threshold(y: pd.Series, probability: np.ndarray) -> float:
    candidates = np.linspace(0.05, 0.95, 181)
    scores = [f1_score(y, probability >= threshold, zero_division=0) for threshold in candidates]
    return float(candidates[int(np.argmax(scores))])


def metrics(y: pd.Series, probability: np.ndarray, threshold: float) -> dict:
    prediction = probability >= threshold
    return {
        "roc_auc": float(roc_auc_score(y, probability)),
        "pr_auc": float(average_precision_score(y, probability)),
        "f1": float(f1_score(y, prediction, zero_division=0)),
        "precision": float(precision_score(y, prediction, zero_division=0)),
        "recall": float(recall_score(y, prediction, zero_division=0)),
        "threshold": threshold,
    }


def params(iterations: int, verbose: bool | int) -> dict:
    return dict(
        iterations=iterations, depth=7, learning_rate=0.04, loss_function="Logloss",
        eval_metric="AUC", random_seed=42, l2_leaf_reg=8, random_strength=1.0,
        allow_writing_files=False, verbose=verbose,
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(INPUT, compression="gzip", parse_dates=["timestamp"], low_memory=False)
    candidates = [column for column in data if column not in {"timestamp", "split", TARGET}]
    features = [
        column for column in candidates
        if "_orbit_diff_" not in column
        and not any(column.endswith(f"_lag_{label}") for label in ORBIT_LABELS)
    ]
    train = data[data["split"] == "train"]
    valid = data[data["split"] == "valid"]
    test = data[data["split"] == "test"]

    selector = CatBoostClassifier(**params(700, 100), od_type="Iter", od_wait=80)
    selector.fit(
        train[features], train[TARGET].astype(int), cat_features=CATEGORICAL,
        eval_set=(valid[features], valid[TARGET].astype(int)), use_best_model=True,
    )
    valid_probability = selector.predict_proba(valid[features])[:, 1]
    threshold = choose_threshold(valid[TARGET].astype(int), valid_probability)
    iterations = max(1, selector.get_best_iteration() + 1)

    final_train = pd.concat([train, valid], ignore_index=True)
    model = CatBoostClassifier(**params(iterations, False))
    model.fit(final_train[features], final_train[TARGET].astype(int), cat_features=CATEGORICAL)
    test_probability = model.predict_proba(test[features])[:, 1]
    result = {
        "feature_count": len(features),
        "best_iterations": iterations,
        "validation": metrics(valid[TARGET].astype(int), valid_probability, threshold),
        "test": metrics(test[TARGET].astype(int), test_probability, threshold),
    }
    model.save_model(OUTPUT / "catboost_q99_6h_no_orbit.cbm")
    (OUTPUT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
