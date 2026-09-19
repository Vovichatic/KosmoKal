#!/usr/bin/env python3
"""Small CatBoost search focused on recall under a precision constraint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve, precision_score, recall_score, roc_auc_score


TARGET = "target_high_q99_6h"
CATEGORICAL = ["instrument_id", "Kp_status", "Dst_status"]
SEED = 42


CONFIGS = [
    {"name": "logloss_d6_regularized", "loss_function": "Logloss", "depth": 6, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.045},
    {"name": "logloss_d7_low_random", "loss_function": "Logloss", "depth": 7, "l2_leaf_reg": 5, "random_strength": 0.2, "learning_rate": 0.04},
    {"name": "logloss_d8_regularized", "loss_function": "Logloss", "depth": 8, "l2_leaf_reg": 10, "random_strength": 0.5, "learning_rate": 0.035},
    {"name": "crossentropy_d7", "loss_function": "CrossEntropy", "depth": 7, "l2_leaf_reg": 6, "random_strength": 0.5, "learning_rate": 0.04},
    {"name": "logloss_d7_positive110", "loss_function": "Logloss", "depth": 7, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.04, "class_weights": [1.0, 1.10]},
    {"name": "logloss_d7_rsm80", "loss_function": "Logloss", "depth": 7, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.04, "rsm": 0.8},
]

FINE_CONFIGS = [
    {"name": "logloss_d7_positive105", "loss_function": "Logloss", "depth": 7, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.04, "class_weights": [1.0, 1.05]},
    {"name": "logloss_d7_positive110", "loss_function": "Logloss", "depth": 7, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.04, "class_weights": [1.0, 1.10]},
    {"name": "logloss_d7_positive115", "loss_function": "Logloss", "depth": 7, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.04, "class_weights": [1.0, 1.15]},
    {"name": "logloss_d7_positive120", "loss_function": "Logloss", "depth": 7, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.04, "class_weights": [1.0, 1.20]},
    {"name": "logloss_d6_positive110", "loss_function": "Logloss", "depth": 6, "l2_leaf_reg": 8, "random_strength": 0.5, "learning_rate": 0.045, "class_weights": [1.0, 1.10]},
    {"name": "logloss_d8_positive110", "loss_function": "Logloss", "depth": 8, "l2_leaf_reg": 10, "random_strength": 0.5, "learning_rate": 0.035, "class_weights": [1.0, 1.10]},
]

EXTERNAL_CONFIGS = [FINE_CONFIGS[1], FINE_CONFIGS[2]]


def recall_threshold(y_true: np.ndarray, probability: np.ndarray, min_precision: float) -> tuple[float, dict[str, float]]:
    precision, recall, thresholds = precision_recall_curve(y_true, probability)
    eligible = np.flatnonzero(precision[:-1] >= min_precision)
    if len(eligible):
        best_recall = recall[eligible].max()
        eligible = eligible[np.isclose(recall[eligible], best_recall)]
        index = int(eligible[np.argmax(precision[eligible])])
    else:
        beta2 = 5 * precision[:-1] * recall[:-1] / np.maximum(4 * precision[:-1] + recall[:-1], 1e-12)
        index = int(np.argmax(beta2))
    threshold = float(thresholds[index])
    return threshold, {"precision": float(precision[index]), "recall": float(recall[index])}


def metrics(y_true: np.ndarray, probability: np.ndarray, threshold: float) -> dict[str, float]:
    prediction = probability >= threshold
    precision = precision_score(y_true, prediction, zero_division=0)
    recall = recall_score(y_true, prediction, zero_division=0)
    f2 = 5 * precision * recall / max(4 * precision + recall, 1e-12)
    return {
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "pr_auc": float(average_precision_score(y_true, probability)),
        "precision": float(precision),
        "recall": float(recall),
        "f2": float(f2),
        "threshold": float(threshold),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("analysis/catboost_timeseries/output_v3/catboost_timeseries_dataset.csv.gz"))
    parser.add_argument("--output-dir", type=Path, default=Path("analysis/catboost_timeseries/output_recall_search"))
    parser.add_argument("--min-validation-precision", type=float, default=0.60)
    parser.add_argument("--iterations", type=int, default=700)
    parser.add_argument("--profile", choices=["broad", "fine", "external", "single115"], default="broad")
    parser.add_argument("--feature-group", choices=["all", "base", "mpsh", "ace"], default="all")
    args = parser.parse_args()

    columns = pd.read_csv(args.dataset, nrows=0).columns.tolist()
    features = [column for column in columns if column not in {"timestamp", "split", TARGET}]
    if args.feature_group == "base":
        features = [column for column in features if "mpsh_" not in column and "ace_" not in column]
    elif args.feature_group == "mpsh":
        features = [column for column in features if "ace_" not in column]
    elif args.feature_group == "ace":
        features = [column for column in features if "mpsh_" not in column]
    frame = pd.read_csv(
        args.dataset,
        usecols=["timestamp", "split", TARGET, *features],
        low_memory=False,
    )
    categorical = [column for column in CATEGORICAL if column in features]
    for column in categorical:
        frame[column] = frame[column].fillna("missing").astype(str)
    train = frame.loc[frame["split"] == "train"]
    valid = frame.loc[frame["split"] == "valid"]
    test = frame.loc[frame["split"] == "test"]
    y_valid = valid[TARGET].to_numpy(int)
    y_test = test[TARGET].to_numpy(int)

    results = []
    best = None
    configs = {
        "broad": CONFIGS,
        "fine": FINE_CONFIGS,
        "external": EXTERNAL_CONFIGS,
        "single115": [FINE_CONFIGS[2]],
    }[args.profile]
    for config in configs:
        params = {key: value for key, value in config.items() if key != "name"}
        model = CatBoostClassifier(
            iterations=args.iterations,
            # AUC gives a materially more stable stopping point on the April
            # block; recall/precision and PR-AUC are still used for selection.
            eval_metric="AUC",
            custom_metric=["PRAUC:type=Classic", "Recall", "Precision"],
            bootstrap_type="Bayesian",
            bagging_temperature=0.7,
            border_count=128,
            random_seed=SEED,
            verbose=False,
            allow_writing_files=False,
            **params,
        )
        model.fit(
            train[features], train[TARGET].astype(int), cat_features=categorical,
            eval_set=(valid[features], valid[TARGET].astype(int)),
            early_stopping_rounds=80, use_best_model=True,
        )
        valid_probability = model.predict_proba(valid[features])[:, 1]
        threshold, operating_point = recall_threshold(
            y_valid, valid_probability, args.min_validation_precision
        )
        valid_metrics = metrics(y_valid, valid_probability, threshold)
        row = {
            "name": config["name"],
            "params": params,
            "best_iteration": int(model.get_best_iteration()),
            "validation": valid_metrics,
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        key = (valid_metrics["recall"], valid_metrics["pr_auc"], valid_metrics["precision"])
        if best is None or key > best[0]:
            best = (key, row)

    assert best is not None
    chosen = best[1]
    params = chosen["params"]
    final_train = pd.concat([train, valid], ignore_index=True)
    final_model = CatBoostClassifier(
        iterations=chosen["best_iteration"] + 1,
        bootstrap_type="Bayesian",
        bagging_temperature=0.7,
        border_count=128,
        random_seed=SEED,
        verbose=False,
        allow_writing_files=False,
        **params,
    )
    final_model.fit(final_train[features], final_train[TARGET].astype(int), cat_features=categorical)
    test_probability = final_model.predict_proba(test[features])[:, 1]
    test_metrics = metrics(y_test, test_probability, chosen["validation"]["threshold"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    final_model.save_model(args.output_dir / "catboost_q99_6h_recall.cbm")
    payload = {
        "selection": "maximum validation recall subject to precision constraint",
        "min_validation_precision": args.min_validation_precision,
        "feature_count": len(features),
        "feature_group": args.feature_group,
        "candidates": results,
        "selected": chosen,
        "test": test_metrics,
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(payload, indent=2) + "\n")
    pd.DataFrame(
        {"timestamp": test["timestamp"], TARGET: y_test, "probability": test_probability}
    ).to_csv(args.output_dir / "test_predictions.csv", index=False)
    print(json.dumps({"selected": chosen["name"], "test": test_metrics}, indent=2), flush=True)


if __name__ == "__main__":
    main()
