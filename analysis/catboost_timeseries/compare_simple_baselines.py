#!/usr/bin/env python3
"""Compare the 6-hour model with simple current-state warning rules.

All thresholds are fixed without looking at the May-June 2024 test labels.
The DOSTEL threshold is the train-calibrated local Q99 represented by
``q99_margin > 0``. The GOES threshold is the 99th percentile of the derived
>10 MeV proxy on train; this proxy is not the official NOAA integral pfu.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


TARGET = "target_high_q99_6h"
GOES = "proton_flux_proxy_gt10_mev"


def binary_metrics(y_true: pd.Series, prediction: pd.Series) -> dict[str, object]:
    prediction = prediction.astype(bool)
    tn, fp, fn, tp = confusion_matrix(y_true, prediction, labels=[0, 1]).ravel()
    return {
        "precision": float(precision_score(y_true, prediction, zero_division=0)),
        "recall": float(recall_score(y_true, prediction, zero_division=0)),
        "f1": float(f1_score(y_true, prediction, zero_division=0)),
        "alert_rate": float(prediction.mean()),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def ranking_metrics(y_true: pd.Series, score: pd.Series) -> dict[str, float]:
    mask = score.notna()
    return {
        "roc_auc": float(roc_auc_score(y_true[mask], score[mask])),
        "pr_auc": float(average_precision_score(y_true[mask], score[mask])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("analysis/catboost_timeseries/output_v2/catboost_timeseries_dataset.csv.gz"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis/catboost_timeseries/output_v2/simple_baselines.json"),
    )
    args = parser.parse_args()

    columns = ["split", TARGET, "q99_margin", GOES]
    frame = pd.read_csv(args.dataset, usecols=columns)
    train = frame.loc[frame["split"] == "train"]
    test = frame.loc[frame["split"] == "test"].copy()
    y_test = test[TARGET].astype(int)

    goes_q99 = float(train[GOES].quantile(0.99))
    dostel_alert = test["q99_margin"] > 0
    goes_alert = test[GOES] > goes_q99

    result = {
        "task": "instrument-local Q99 exceedance at any point in the next 6 hours",
        "test_rows": int(len(test)),
        "test_positive_rate": float(y_test.mean()),
        "thresholds": {
            "dostel": "train-calibrated instrument-local Q99 (q99_margin > 0)",
            "goes_gt10_proxy_train_q99": goes_q99,
            "goes_caveat": "derived differential-channel proxy, not official NOAA integral pfu",
        },
        "continuous_ranking": {
            "current_dostel_q99_margin": ranking_metrics(y_test, test["q99_margin"]),
            "current_goes_gt10_proxy": ranking_metrics(y_test, np.log1p(test[GOES].clip(lower=0))),
        },
        "rules": {
            "current_dostel_above_local_q99": binary_metrics(y_test, dostel_alert),
            "current_goes_proxy_above_train_q99": binary_metrics(y_test, goes_alert),
            "current_dostel_or_goes": binary_metrics(y_test, dostel_alert | goes_alert),
            "always_alert_recall_sanity_check": binary_metrics(
                y_test, pd.Series(True, index=test.index)
            ),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
