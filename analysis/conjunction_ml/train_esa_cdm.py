#!/usr/bin/env python3
"""Train leakage-safe CatBoost models on ESA conjunction CDM sequences."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    fbeta_score,
    mean_squared_error,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split


SEED = 42
DECISION_CUTOFF_DAYS = 2.0
HIGH_RISK_LOG10 = -6.0
CATEGORICAL = ["mission_id", "c_object_type"]


def build_event_table(frame: pd.DataFrame, with_target: bool) -> pd.DataFrame:
    """Collapse each CDM sequence using only messages >=2 days before TCA."""
    frame = frame.sort_values(["event_id", "time_to_tca"], ascending=[True, False])
    if with_target:
        final_idx = frame.groupby("event_id", sort=False)["time_to_tca"].idxmin()
        targets = frame.loc[final_idx, ["event_id", "time_to_tca", "risk"]].rename(
            columns={"time_to_tca": "final_time_to_tca", "risk": "final_risk_log10"}
        )
        # The label row must never be reused as an input, even when the last
        # available training CDM happens to be older than the two-day cutoff.
        visible = frame.drop(index=final_idx)
    else:
        visible = frame
    visible = visible.loc[visible["time_to_tca"] >= DECISION_CUTOFF_DAYS].copy()
    eligible = set(visible["event_id"].unique())
    if with_target:
        targets = targets.loc[targets["event_id"].isin(eligible)]

    numeric = [
        column for column in visible.select_dtypes(include=[np.number]).columns
        if column != "event_id"
    ]
    groups = visible.groupby("event_id", sort=False)
    latest = groups.tail(1).set_index("event_id")
    earliest = groups.head(1).set_index("event_id")

    base = latest[numeric].add_prefix("last_")
    categorical = pd.DataFrame(
        {
            column: latest[column].fillna("missing").astype(str)
            for column in CATEGORICAL
        },
        index=latest.index,
    )

    # Generic sequence summaries work well for CDM fields because risk,
    # covariance, miss distance and orbit-determination quality all evolve as
    # new observations arrive.
    aggregate = groups[numeric].agg(["mean", "std", "min", "max"])
    aggregate.columns = [f"{column}_{stat}" for column, stat in aggregate.columns]
    delta = latest[numeric] - earliest[numeric]
    delta.columns = [f"{column}_delta" for column in delta.columns]
    extras = pd.DataFrame(
        {
            "cdm_count": groups.size(),
            "observed_span_days": groups["time_to_tca"].max() - groups["time_to_tca"].min(),
        }
    )
    result = pd.concat([base, categorical, aggregate, delta, extras], axis=1)

    result = result.copy()
    result.index.name = "event_id"
    result = result.reset_index()
    if with_target:
        result = result.merge(targets, on="event_id", how="inner", validate="one_to_one")
        result["target_high_risk"] = (result["final_risk_log10"] >= HIGH_RISK_LOG10).astype(int)
    return result


def choose_f2_threshold(
    y_true: pd.Series, probability: np.ndarray, mandatory_alert: np.ndarray | None = None
) -> float:
    candidates = np.linspace(0.01, 0.99, 197)
    scores = []
    for threshold in candidates:
        prediction = probability >= threshold
        if mandatory_alert is not None:
            prediction = prediction | mandatory_alert
        scores.append(fbeta_score(y_true, prediction, beta=2, zero_division=0))
    return float(candidates[int(np.argmax(scores))])


def classification_metrics(
    y_true: pd.Series,
    probability: np.ndarray,
    threshold: float,
    mandatory_alert: np.ndarray | None = None,
) -> dict:
    prediction = probability >= threshold
    if mandatory_alert is not None:
        prediction = prediction | mandatory_alert
    return {
        "positive_rate": float(y_true.mean()),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "pr_auc": float(average_precision_score(y_true, probability)),
        "precision": float(precision_score(y_true, prediction, zero_division=0)),
        "recall": float(recall_score(y_true, prediction, zero_division=0)),
        "f2": float(fbeta_score(y_true, prediction, beta=2, zero_division=0)),
        "brier": float(brier_score_loss(y_true, probability)),
        "threshold": threshold,
    }


def fit_classifier(train: pd.DataFrame, valid: pd.DataFrame, features: list[str]) -> CatBoostClassifier:
    positives = int(train["target_high_risk"].sum())
    negatives = len(train) - positives
    model = CatBoostClassifier(
        iterations=1500,
        depth=7,
        learning_rate=0.035,
        loss_function="Logloss",
        eval_metric="PRAUC:type=Classic",
        class_weights=[1.0, negatives / max(positives, 1)],
        random_seed=SEED,
        l2_leaf_reg=8,
        random_strength=0.5,
        od_type="Iter",
        od_wait=120,
        allow_writing_files=False,
        verbose=200,
    )
    model.fit(
        train[features], train["target_high_risk"], cat_features=CATEGORICAL,
        eval_set=(valid[features], valid["target_high_risk"]), use_best_model=True,
    )
    return model


def fit_regressor(train: pd.DataFrame, valid: pd.DataFrame, features: list[str]) -> CatBoostRegressor:
    # ESA's regression error is evaluated only on high-risk events. Fit a
    # residual correction around the strongest causal baseline (maximum risk
    # reported in CDMs available before the two-day cutoff) and retain nearby
    # borderline events to regularize the small positive class.
    train = train.loc[train["final_risk_log10"] >= -8.0].copy()
    valid = valid.loc[valid["final_risk_log10"] >= -8.0].copy()
    train["residual_target"] = train["final_risk_log10"] - train["risk_max"]
    valid["residual_target"] = valid["final_risk_log10"] - valid["risk_max"]
    model = CatBoostRegressor(
        iterations=1800,
        depth=7,
        learning_rate=0.035,
        loss_function="RMSE",
        eval_metric="RMSE",
        random_seed=SEED,
        l2_leaf_reg=10,
        random_strength=0.5,
        od_type="Iter",
        od_wait=120,
        allow_writing_files=False,
        verbose=200,
    )
    model.fit(
        train[features], train["residual_target"], cat_features=CATEGORICAL,
        eval_set=(valid[features], valid["residual_target"]), use_best_model=True,
    )
    return model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, default=Path("data/conjunction_raw/train/train_data.csv"))
    parser.add_argument("--challenge-test", type=Path, default=Path("data/conjunction_raw/test_data.csv"))
    parser.add_argument("--output", type=Path, default=Path("analysis/conjunction_ml/output"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(args.train)
    events = build_event_table(raw, with_target=True)
    challenge_events = build_event_table(pd.read_csv(args.challenge_test), with_target=False)
    events.to_csv(args.output / "event_table_train.csv.gz", index=False, compression="gzip")
    challenge_events.to_csv(args.output / "event_table_challenge_test.csv.gz", index=False, compression="gzip")

    # ESA challenge test events receive a final CDM within one day of TCA,
    # while inputs stop at two days. Keep validation and holdout test on that
    # same distribution; older-ending sequences are auxiliary training only.
    test_like = events.loc[events["final_time_to_tca"] < 1.0].copy()
    auxiliary = events.loc[events["final_time_to_tca"] >= 1.0].copy()
    model_pool, test = train_test_split(
        test_like, test_size=0.20, random_state=SEED,
        stratify=test_like["target_high_risk"],
    )
    excluded = {"event_id", "final_time_to_tca", "final_risk_log10", "target_high_risk"}
    features = [column for column in events.columns if column not in excluded]
    for part in (model_pool, auxiliary, test, challenge_events, events):
        for column in CATEGORICAL:
            part[column] = part[column].fillna("missing").astype(str)

    # A single validation split contains too few rare positives. Select the
    # threshold and number of trees from out-of-fold predictions on all
    # test-like development events, while keeping a final holdout untouched.
    splitter = StratifiedKFold(n_splits=4, shuffle=True, random_state=SEED)
    oof_probability = np.zeros(len(model_pool), dtype=float)
    fold_iterations: list[int] = []
    for fold, (train_idx, valid_idx) in enumerate(
        splitter.split(model_pool, model_pool["target_high_risk"]), start=1
    ):
        fold_train = pd.concat([model_pool.iloc[train_idx], auxiliary], ignore_index=True)
        fold_valid = model_pool.iloc[valid_idx]
        fold_model = fit_classifier(fold_train, fold_valid, features)
        oof_probability[valid_idx] = fold_model.predict_proba(fold_valid[features])[:, 1]
        fold_iterations.append(max(1, fold_model.get_best_iteration() + 1))
        print(f"completed classifier fold {fold}", flush=True)
    oof_known_alert = model_pool["last_risk"].to_numpy() >= HIGH_RISK_LOG10
    threshold = choose_f2_threshold(
        model_pool["target_high_risk"], oof_probability, oof_known_alert
    )
    classifier_iterations = max(5, int(round(float(np.median(fold_iterations)))))

    train = pd.concat([model_pool, auxiliary], ignore_index=True)
    positives = int(train["target_high_risk"].sum())
    classifier = CatBoostClassifier(
        iterations=classifier_iterations, depth=7, learning_rate=0.035,
        loss_function="Logloss", random_seed=SEED,
        class_weights=[1.0, (len(train) - positives) / max(positives, 1)],
        l2_leaf_reg=8, random_strength=0.5, allow_writing_files=False, verbose=False,
    )
    classifier.fit(train[features], train["target_high_risk"], cat_features=CATEGORICAL)
    test_probability = classifier.predict_proba(test[features])[:, 1]

    regression_train, regression_valid = train_test_split(
        model_pool, test_size=0.20, random_state=SEED,
        stratify=model_pool["target_high_risk"],
    )
    regressor_selector = fit_regressor(
        pd.concat([regression_train, auxiliary], ignore_index=True), regression_valid, features
    )
    regressor_iterations = max(1, regressor_selector.get_best_iteration() + 1)
    regression_focus = train.loc[train["final_risk_log10"] >= -8.0].copy()
    regression_focus["residual_target"] = (
        regression_focus["final_risk_log10"] - regression_focus["risk_max"]
    )
    regressor = CatBoostRegressor(
        iterations=regressor_iterations, depth=7, learning_rate=0.035,
        loss_function="RMSE", random_seed=SEED, l2_leaf_reg=10,
        random_strength=0.5, allow_writing_files=False, verbose=False,
    )
    regressor.fit(
        regression_focus[features], regression_focus["residual_target"], cat_features=CATEGORICAL
    )
    test_risk_raw = test["risk_max"].to_numpy() + regressor.predict(test[features])
    test_known_alert = test["last_risk"].to_numpy() >= HIGH_RISK_LOG10
    test_prediction = (test_probability >= threshold) | test_known_alert
    # Keep regression and classification heads consistent at the operational
    # boundary. This does not use test labels; the boundary comes from ESA.
    test_risk = np.where(
        test_prediction,
        np.maximum(test_risk_raw, HIGH_RISK_LOG10),
        np.minimum(test_risk_raw, HIGH_RISK_LOG10 - 1e-3),
    )
    high_mask = test["target_high_risk"].to_numpy() == 1

    # Legitimate two-day baselines: the latest self-reported risk and the
    # covariance-scaled maximum-risk estimate already present in the CDM.
    baseline_risk = test["last_risk"].to_numpy()
    baseline_probability = (baseline_risk >= HIGH_RISK_LOG10).astype(float)
    baseline_max = test["last_max_risk_estimate"].to_numpy()
    baseline_max_probability = (baseline_max >= HIGH_RISK_LOG10).astype(float)

    metrics = {
        "dataset": {
            "raw_rows": int(len(raw)),
            "eligible_events": int(len(events)),
            "features": len(features),
            "decision_cutoff_days": DECISION_CUTOFF_DAYS,
            "high_risk_log10_threshold": HIGH_RISK_LOG10,
            "split_rows": {"train": len(train), "oof_validation": len(model_pool), "test": len(test)},
            "test_like_events": int(len(test_like)),
        },
        "classifier": {
            "selected_iterations": classifier_iterations,
            "fold_iterations": fold_iterations,
            "validation_oof": classification_metrics(
                model_pool["target_high_risk"], oof_probability, threshold, oof_known_alert
            ),
            "test": classification_metrics(
                test["target_high_risk"], test_probability, threshold, test_known_alert
            ),
        },
        "regressor": {
            "selected_iterations": regressor_iterations,
            "test_rmse_all_log10": float(mean_squared_error(test["final_risk_log10"], test_risk) ** 0.5),
            "test_rmse_high_risk_log10": float(mean_squared_error(test.loc[high_mask, "final_risk_log10"], test_risk[high_mask]) ** 0.5),
            "risk_max_baseline_rmse_high_risk_log10": float(mean_squared_error(test.loc[high_mask, "final_risk_log10"], test.loc[high_mask, "risk_max"]) ** 0.5),
        },
        "baselines": {
            "latest_known_risk": classification_metrics(test["target_high_risk"], baseline_probability, 0.5),
            "latest_max_risk_estimate": classification_metrics(test["target_high_risk"], baseline_max_probability, 0.5),
        },
    }

    # Once the holdout metrics are frozen, refit deployable artifacts on every
    # labeled event using only the already selected iteration counts.
    all_positives = int(events["target_high_risk"].sum())
    final_classifier = CatBoostClassifier(
        iterations=classifier_iterations, depth=7,
        learning_rate=0.035, loss_function="Logloss", random_seed=SEED,
        class_weights=[1.0, (len(events) - all_positives) / max(all_positives, 1)],
        l2_leaf_reg=8, random_strength=0.5, allow_writing_files=False, verbose=False,
    )
    final_classifier.fit(
        events[features], events["target_high_risk"], cat_features=CATEGORICAL
    )
    focus = events.loc[events["final_risk_log10"] >= -8.0].copy()
    focus["residual_target"] = focus["final_risk_log10"] - focus["risk_max"]
    final_regressor = CatBoostRegressor(
        iterations=regressor_iterations, depth=7,
        learning_rate=0.035, loss_function="RMSE", random_seed=SEED,
        l2_leaf_reg=10, random_strength=0.5, allow_writing_files=False, verbose=False,
    )
    final_regressor.fit(
        focus[features], focus["residual_target"], cat_features=CATEGORICAL
    )
    final_classifier.save_model(args.output / "esa_cdm_high_risk_classifier.cbm")
    final_regressor.save_model(args.output / "esa_cdm_final_risk_regressor.cbm")
    pd.DataFrame(
        {"feature": features, "importance": final_classifier.get_feature_importance()}
    ).sort_values("importance", ascending=False).to_csv(
        args.output / "classifier_feature_importance.csv", index=False
    )
    challenge_prediction = pd.DataFrame({
        "event_id": challenge_events["event_id"],
        "predicted_risk": challenge_events["risk_max"].to_numpy() + final_regressor.predict(challenge_events[features]),
        "high_risk_probability": final_classifier.predict_proba(challenge_events[features])[:, 1],
    })
    challenge_is_high = (
        (challenge_prediction["high_risk_probability"] >= threshold)
        | (challenge_events["last_risk"].to_numpy() >= HIGH_RISK_LOG10)
    )
    challenge_prediction["predicted_risk"] = np.where(
        challenge_is_high,
        np.maximum(challenge_prediction["predicted_risk"], HIGH_RISK_LOG10),
        np.minimum(challenge_prediction["predicted_risk"], HIGH_RISK_LOG10 - 1e-3),
    )
    challenge_prediction.to_csv(args.output / "challenge_predictions.csv", index=False)
    challenge_prediction[["event_id", "predicted_risk"]].to_csv(
        args.output / "challenge_submission.csv", index=False
    )
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

