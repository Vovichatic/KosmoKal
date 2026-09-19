#!/usr/bin/env python3
"""Select a recency-weighted CatBoost on validation, then evaluate once on test."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score


INPUT = Path("analysis/catboost_timeseries/output_extended/catboost_timeseries_dataset.csv.gz")
OUTPUT = Path("analysis/catboost_timeseries/output_weighted")
TARGET = "target_high_q99_6h"
CATEGORICAL = ["instrument_id", "Kp_status", "Dst_status"]
SEED = 42


def time_weights(timestamp: pd.Series, end: pd.Timestamp, half_life_days: int | None) -> np.ndarray:
    if half_life_days is None:
        return np.ones(len(timestamp), dtype=float)
    age_days = (end - timestamp).dt.total_seconds().clip(lower=0).to_numpy() / 86_400
    # A floor keeps every historical regime represented while preventing the
    # quiet 2020 period from dominating the much more relevant recent cycle.
    return np.maximum(0.10, np.exp2(-age_days / half_life_days))


def choose_threshold(y_true: pd.Series, probability: np.ndarray) -> float:
    candidates = np.linspace(0.05, 0.95, 181)
    scores = [f1_score(y_true, probability >= threshold, zero_division=0) for threshold in candidates]
    return float(candidates[int(np.argmax(scores))])


def score(y_true: pd.Series, probability: np.ndarray, threshold: float) -> dict[str, float]:
    prediction = probability >= threshold
    return {
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "pr_auc": float(average_precision_score(y_true, probability)),
        "f1": float(f1_score(y_true, prediction, zero_division=0)),
        "precision": float(precision_score(y_true, prediction, zero_division=0)),
        "recall": float(recall_score(y_true, prediction, zero_division=0)),
        "threshold": threshold,
    }


def model_params(iterations: int, verbose: bool | int) -> dict:
    return {
        "iterations": iterations,
        "depth": 7,
        "learning_rate": 0.04,
        "loss_function": "Logloss",
        "eval_metric": "PRAUC:type=Classic",
        "random_seed": SEED,
        "l2_leaf_reg": 8,
        "random_strength": 1.0,
        "allow_writing_files": False,
        "verbose": verbose,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(INPUT, compression="gzip", parse_dates=["timestamp"], low_memory=False)
    features = [column for column in data.columns if column not in {"timestamp", "split", TARGET}]
    train = data.loc[data["split"] == "train"].copy()
    valid = data.loc[data["split"] == "valid"].copy()
    test = data.loc[data["split"] == "test"].copy()
    train_end = pd.Timestamp("2024-04-17 18:00", tz="UTC")

    candidates = []
    fitted = {}
    for half_life in (None, 180, 365, 730):
        model = CatBoostClassifier(
            **model_params(700, 100), od_type="Iter", od_wait=80
        )
        model.fit(
            train[features],
            train[TARGET].astype(int),
            cat_features=CATEGORICAL,
            sample_weight=time_weights(train["timestamp"], train_end, half_life),
            eval_set=(valid[features], valid[TARGET].astype(int)),
            use_best_model=True,
        )
        probability = model.predict_proba(valid[features])[:, 1]
        threshold = choose_threshold(valid[TARGET].astype(int), probability)
        row = {
            "half_life_days": half_life,
            "best_iterations": max(1, model.get_best_iteration() + 1),
            **score(valid[TARGET].astype(int), probability, threshold),
        }
        candidates.append(row)
        fitted[str(half_life)] = model
        print(json.dumps(row), flush=True)

    # PR-AUC is the selection criterion because April has a rare positive class.
    selected = max(candidates, key=lambda row: row["pr_auc"])
    half_life = selected["half_life_days"]
    final_train = pd.concat([train, valid], ignore_index=True)
    final_end = pd.Timestamp("2024-04-30 18:00", tz="UTC")
    final_model = CatBoostClassifier(**model_params(selected["best_iterations"], False))
    final_model.fit(
        final_train[features],
        final_train[TARGET].astype(int),
        cat_features=CATEGORICAL,
        sample_weight=time_weights(final_train["timestamp"], final_end, half_life),
    )
    test_probability = final_model.predict_proba(test[features])[:, 1]
    result = {
        "selection_criterion": "validation_pr_auc",
        "candidates": candidates,
        "selected_half_life_days": half_life,
        "test": score(test[TARGET].astype(int), test_probability, selected["threshold"]),
    }
    final_model.save_model(OUTPUT / "catboost_q99_6h_weighted.cbm")
    (OUTPUT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

