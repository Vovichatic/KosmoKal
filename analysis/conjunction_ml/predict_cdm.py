#!/usr/bin/env python3
"""Predict final conjunction risk from ESA-schema CDM sequences."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor

from train_esa_cdm import CATEGORICAL, HIGH_RISK_LOG10, build_event_table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-dir", type=Path, default=Path("analysis/conjunction_ml/output"))
    args = parser.parse_args()

    classifier = CatBoostClassifier()
    classifier.load_model(args.model_dir / "esa_cdm_high_risk_classifier.cbm")
    regressor = CatBoostRegressor()
    regressor.load_model(args.model_dir / "esa_cdm_final_risk_regressor.cbm")
    metrics = json.loads((args.model_dir / "metrics.json").read_text(encoding="utf-8"))
    threshold = float(metrics["classifier"]["validation_oof"]["threshold"])

    events = build_event_table(pd.read_csv(args.input), with_target=False)
    features = classifier.feature_names_
    for feature in features:
        if feature not in events:
            events[feature] = "missing" if feature in CATEGORICAL else np.nan
    for column in CATEGORICAL:
        events[column] = events[column].fillna("missing").astype(str)

    probability = classifier.predict_proba(events[features])[:, 1]
    risk = events["risk_max"].to_numpy() + regressor.predict(events[features])
    high = (probability >= threshold) | (events["last_risk"].to_numpy() >= HIGH_RISK_LOG10)
    risk = np.where(high, np.maximum(risk, HIGH_RISK_LOG10), np.minimum(risk, HIGH_RISK_LOG10 - 1e-3))
    result = pd.DataFrame(
        {
            "event_id": events["event_id"],
            "predicted_final_risk_log10": risk,
            "high_risk_probability": probability,
            "high_risk_prediction": high.astype(int),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"wrote {args.output}: {len(result)} events")


if __name__ == "__main__":
    main()
