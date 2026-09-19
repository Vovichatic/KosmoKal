#!/usr/bin/env python3
"""Tune the contribution of 2020-2022 history without touching final test."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score


INPUT = Path("analysis/catboost_timeseries/output_extended/catboost_timeseries_dataset.csv.gz")
OUTPUT = Path("analysis/catboost_timeseries/output_history_mix")
TARGET = "target_high_q99_6h"
CATEGORICAL = ["instrument_id", "Kp_status", "Dst_status"]
CUTOFF = pd.Timestamp("2023-01-01", tz="UTC")


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
        eval_metric="PRAUC:type=Classic", random_seed=42, l2_leaf_reg=8,
        random_strength=1.0, allow_writing_files=False, verbose=verbose,
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(INPUT, compression="gzip", parse_dates=["timestamp"], low_memory=False)
    features = [column for column in data if column not in {"timestamp", "split", TARGET}]
    train = data[data["split"] == "train"].copy()
    valid = data[data["split"] == "valid"].copy()
    test = data[data["split"] == "test"].copy()

    candidates = []
    for old_weight in (0.05, 0.10, 0.25, 0.50):
        weights = np.where(train["timestamp"] < CUTOFF, old_weight, 1.0)
        model = CatBoostClassifier(**params(700, 100), od_type="Iter", od_wait=80)
        model.fit(
            train[features], train[TARGET].astype(int), cat_features=CATEGORICAL,
            sample_weight=weights,
            eval_set=(valid[features], valid[TARGET].astype(int)), use_best_model=True,
        )
        probability = model.predict_proba(valid[features])[:, 1]
        threshold = choose_threshold(valid[TARGET].astype(int), probability)
        row = {
            "old_history_weight": old_weight,
            "best_iterations": max(1, model.get_best_iteration() + 1),
            **metrics(valid[TARGET].astype(int), probability, threshold),
        }
        candidates.append(row)
        print(json.dumps(row), flush=True)

    selected = max(candidates, key=lambda row: row["pr_auc"])
    final_train = pd.concat([train, valid], ignore_index=True)
    final_weights = np.where(final_train["timestamp"] < CUTOFF, selected["old_history_weight"], 1.0)
    model = CatBoostClassifier(**params(selected["best_iterations"], False))
    model.fit(
        final_train[features], final_train[TARGET].astype(int), cat_features=CATEGORICAL,
        sample_weight=final_weights,
    )
    test_probability = model.predict_proba(test[features])[:, 1]
    result = {
        "selection_criterion": "validation_pr_auc",
        "old_history_definition": "timestamp before 2023-01-01",
        "candidates": candidates,
        "selected_old_history_weight": selected["old_history_weight"],
        "test": metrics(test[TARGET].astype(int), test_probability, selected["threshold"]),
    }
    model.save_model(OUTPUT / "catboost_q99_6h_history_mix.cbm")
    (OUTPUT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

