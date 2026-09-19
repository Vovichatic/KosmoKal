#!/usr/bin/env python3
"""Build a leakage-aware time-series dataset and train CatBoost.

The model predicts whether the instrument-specific spatial dose residual will
exceed the local research Q99 at any point in the next six hours. Features at
timestamp t only use observations available at or before t. Temporal splits
are separated by a six-hour purge gap so target windows do not overlap.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


TARGET = "target_high_q99_6h"
HORIZON_HOURS = 6
HORIZON_STEPS = 72
SEED = 42
TARGET_CALIBRATION_START = pd.Timestamp("2023-01-01", tz="UTC")

SPLITS = {
    "train": (pd.Timestamp("2020-01-08", tz="UTC"), pd.Timestamp("2024-04-17 18:00", tz="UTC")),
    "valid": (pd.Timestamp("2024-04-18", tz="UTC"), pd.Timestamp("2024-04-30 18:00", tz="UTC")),
    "test": (pd.Timestamp("2024-05-01", tz="UTC"), pd.Timestamp("2024-06-30 18:00", tz="UTC")),
}

LAG_STEPS = {
    "5m": 1,
    "15m": 3,
    "30m": 6,
    "1h": 12,
    "90m": 18,
    "95m": 19,
    "100m": 20,
    "3h": 36,
    "190m": 38,
    "285m": 57,
    "6h": 72,
    "380m": 76,
    "12h": 144,
    "1d": 288,
    "3d": 864,
    "7d": 2016,
}

ROLLING_STEPS = {
    "1h": 12,
    "6h": 72,
    "1d": 288,
    "3d": 864,
    "7d": 2016,
}

EXTERNAL_POSITIVE = [
    "mpsh_electron_low",
    "mpsh_electron_mid",
    "mpsh_electron_high",
    "mpsh_electron_gt2mev",
    "mpsh_proton_proxy_gt1mev",
    "mpsh_proton_proxy_gt5mev",
    "ace_epam_p7",
    "ace_epam_p8",
    "ace_epam_de1",
    "ace_epam_de4",
]

EXTERNAL_STATE = [
    "ace_proton_density",
    "ace_solar_wind_speed",
    "ace_helium_ratio",
    "ace_proton_temperature",
    "ace_imf_magnitude",
    "ace_imf_bx_gse",
    "ace_imf_by_gse",
    "ace_imf_bz_gse",
]

EXTERNAL_HISTORY = [f"log1p_{column}" for column in EXTERNAL_POSITIVE] + [
    "ace_proton_density",
    "ace_solar_wind_speed",
    "ace_imf_magnitude",
    "ace_imf_bz_gse",
]

LAG_SOURCES = [
    "dose_residual",
    "log_dose",
    "flux",
    "proton_flux_proxy_gt10_mev",
    "proton_flux_proxy_gt50_mev",
    "proton_flux_proxy_gt100_mev",
    "log10_xrs_a_flux",
    "log10_xrs_b_flux",
]

ROLLING_SOURCES = [
    "dose_residual",
    "flux",
    "proton_flux_proxy_gt10_mev",
    "proton_flux_proxy_gt50_mev",
    "proton_flux_proxy_gt100_mev",
    "log10_xrs_a_flux",
    "log10_xrs_b_flux",
]

CURRENT_NUMERIC = [
    "absorbed_dose_rate",
    "flux",
    "latitude",
    "longitude",
    "altitude",
    "b",
    "l",
    "samples_in_bin",
    "log_dose",
    "spatial_baseline_log_dose",
    "dose_residual",
    "proton_flux_proxy_gt10_mev",
    "proton_flux_proxy_gt50_mev",
    "proton_flux_proxy_gt100_mev",
    "xrs_a_flux",
    "xrs_b_flux",
    "log10_xrs_a_flux",
    "log10_xrs_b_flux",
    "log1p_flux",
    "log1p_proton_flux_proxy_gt10_mev",
    "log1p_proton_flux_proxy_gt50_mev",
    "log1p_proton_flux_proxy_gt100_mev",
    "q99_margin",
    "q99_ratio",
    "Kp",
    "Hp30",
    "Hp60",
    "SN",
    "Fobs",
    "Fadj",
    "Dst",
    "s1_probability_day0",
    "s1_probability_day1",
    "s1_probability_day2",
    "expected_max_kp_3d",
    "swpc_forecast_age_minutes",
    "donki_cme_notification_count",
    "donki_cme_age_minutes",
    "donki_flr_notification_count",
    "donki_flr_age_minutes",
    "donki_sep_notification_count",
    "donki_sep_age_minutes",
    "donki_gst_notification_count",
    "donki_gst_age_minutes",
    "donki_ips_notification_count",
    "donki_ips_age_minutes",
    "donki_hss_notification_count",
    "donki_hss_age_minutes",
] + EXTERNAL_POSITIVE + [f"log1p_{column}" for column in EXTERNAL_POSITIVE] + EXTERNAL_STATE

CATEGORICAL = ["instrument_id", "Kp_status", "Dst_status"]


def add_time_features(frame: pd.DataFrame) -> None:
    ts = frame["timestamp"]
    minute_of_day = ts.dt.hour * 60 + ts.dt.minute
    frame["minute_of_day_sin"] = np.sin(2 * np.pi * minute_of_day / 1440)
    frame["minute_of_day_cos"] = np.cos(2 * np.pi * minute_of_day / 1440)
    day_of_year = ts.dt.dayofyear + minute_of_day / 1440
    frame["day_of_year_sin"] = np.sin(2 * np.pi * day_of_year / 366)
    frame["day_of_year_cos"] = np.cos(2 * np.pi * day_of_year / 366)
    frame["longitude_sin"] = np.sin(np.deg2rad(frame["longitude"]))
    frame["longitude_cos"] = np.cos(np.deg2rad(frame["longitude"]))
    frame["log10_xrs_a_flux"] = np.log10(frame["xrs_a_flux"].clip(lower=1e-12))
    frame["log10_xrs_b_flux"] = np.log10(frame["xrs_b_flux"].clip(lower=1e-12))
    frame["log1p_flux"] = np.log1p(frame["flux"].clip(lower=0))
    for threshold_mev in (10, 50, 100):
        source = f"proton_flux_proxy_gt{threshold_mev}_mev"
        frame[f"log1p_{source}"] = np.log1p(frame[source].clip(lower=0))
    for source in EXTERNAL_POSITIVE:
        if source in frame:
            frame[f"log1p_{source}"] = np.log1p(frame[source].clip(lower=0))


def add_risk_state_features(frame: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    """Add causal state, persistence, and trend features around the fixed Q99."""
    local_threshold = frame["instrument_id"].map(thresholds).astype(float)
    frame["q99_margin"] = frame["dose_residual"] - local_threshold
    frame["q99_ratio"] = frame["dose_residual"] / local_threshold.replace(0, np.nan)

    groups = frame.groupby("instrument_id", sort=False)
    dynamic: dict[str, pd.Series] = {}
    exceedance = (frame["q99_margin"] > 0).astype(float).where(frame["dose_residual"].notna())
    shifted_exceedance = exceedance.groupby(frame["instrument_id"], sort=False).shift(1)
    shifted_margin = groups["q99_margin"].shift(1)
    for label, steps in {"1h": 12, "6h": 72, "1d": 288, "3d": 864}.items():
        exceedance_groups = shifted_exceedance.groupby(frame["instrument_id"], sort=False)
        margin_groups = shifted_margin.groupby(frame["instrument_id"], sort=False)
        min_periods = max(3, steps // 4)
        dynamic[f"q99_exceedance_roll_{label}_rate"] = (
            exceedance_groups.rolling(steps, min_periods=min_periods).mean().reset_index(level=0, drop=True)
        )
        dynamic[f"q99_margin_roll_{label}_max"] = (
            margin_groups.rolling(steps, min_periods=min_periods).max().reset_index(level=0, drop=True)
        )
        dynamic[f"q99_margin_roll_{label}_q90"] = (
            margin_groups.rolling(steps, min_periods=min_periods).quantile(0.90).reset_index(level=0, drop=True)
        )

    trend_sources = [
        "dose_residual", "log1p_flux",
        "log1p_proton_flux_proxy_gt10_mev",
        "log1p_proton_flux_proxy_gt50_mev",
        "log1p_proton_flux_proxy_gt100_mev",
        "log10_xrs_a_flux", "log10_xrs_b_flux",
    ]
    for source in trend_sources:
        grouped = groups[source]
        for label, steps in {"15m": 3, "1h": 12, "6h": 72, "1d": 288}.items():
            dynamic[f"{source}_delta_{label}"] = frame[source] - grouped.shift(steps)
    return pd.concat([frame, pd.DataFrame(dynamic, index=frame.index)], axis=1)


def add_orbit_repeat_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Compare current state with the same approximate phase on prior ISS orbits."""
    groups = frame.groupby("instrument_id", sort=False)
    dynamic: dict[str, pd.Series] = {}
    for source in ["dose_residual", "flux", "log_dose"]:
        grouped = groups[source]
        for label, steps in {"95m": 19, "190m": 38, "285m": 57, "380m": 76}.items():
            dynamic[f"{source}_orbit_diff_{label}"] = frame[source] - grouped.shift(steps)
    return pd.concat([frame, pd.DataFrame(dynamic, index=frame.index)], axis=1)


def rebuild_train_only_target(frame: pd.DataFrame) -> dict[str, float]:
    """Replace globally fitted EDA baseline/label with train-only versions."""
    fit_end = SPLITS["train"][1]
    # Keep the event definition fixed while extending model history. Otherwise
    # adding older years changes Q99 itself and makes model comparisons invalid.
    fit = frame.loc[
        (frame["timestamp"] >= TARGET_CALIBRATION_START)
        & (frame["timestamp"] < fit_end)
    ]
    cell_baseline = (
        fit.groupby(["instrument_id", "lat_bin", "lon_bin"], dropna=False)["log_dose"]
        .median()
        .rename("train_spatial_baseline_log_dose")
    )
    instrument_baseline = fit.groupby("instrument_id")["log_dose"].median()
    frame.drop(columns=["spatial_baseline_log_dose", "dose_residual", TARGET], errors="ignore", inplace=True)
    frame["spatial_baseline_log_dose"] = frame.join(
        cell_baseline, on=["instrument_id", "lat_bin", "lon_bin"]
    )["train_spatial_baseline_log_dose"]
    frame["spatial_baseline_log_dose"] = frame["spatial_baseline_log_dose"].fillna(
        frame["instrument_id"].map(instrument_baseline)
    )
    frame["dose_residual"] = frame["log_dose"] - frame["spatial_baseline_log_dose"]

    thresholds = (
        frame.loc[
            (frame["timestamp"] >= TARGET_CALIBRATION_START)
            & (frame["timestamp"] < fit_end)
        ]
        .groupby("instrument_id")["dose_residual"]
        .quantile(0.99)
        .to_dict()
    )
    frame[TARGET] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    for instrument, idx in frame.groupby("instrument_id", sort=False).groups.items():
        ordered = frame.loc[idx].sort_values("timestamp")
        future = ordered["dose_residual"].shift(-1)
        future_max = future.iloc[::-1].rolling(HORIZON_STEPS, min_periods=HORIZON_STEPS).max().iloc[::-1]
        label = (future_max > thresholds[instrument]).astype("Int64")
        label.loc[future_max.isna()] = pd.NA
        frame.loc[ordered.index, TARGET] = label.values
    return {str(key): float(value) for key, value in thresholds.items()}


def add_history_features(frame: pd.DataFrame) -> pd.DataFrame:
    groups = frame.groupby("instrument_id", sort=False)
    feature_data: dict[str, pd.Series] = {}
    for source in LAG_SOURCES:
        if source not in frame:
            continue
        grouped = groups[source]
        for label, steps in LAG_STEPS.items():
            feature_data[f"{source}_lag_{label}"] = grouped.shift(steps)

    # Shift by one bin before every rolling calculation. No statistic contains
    # the observation at the row being predicted.
    for source in ROLLING_SOURCES:
        if source not in frame:
            continue
        shifted = groups[source].shift(1)
        shifted_groups = shifted.groupby(frame["instrument_id"], sort=False)
        for label, steps in ROLLING_STEPS.items():
            rolling = shifted_groups.rolling(steps, min_periods=max(3, steps // 4))
            feature_data[f"{source}_roll_{label}_mean"] = rolling.mean().reset_index(level=0, drop=True)
            feature_data[f"{source}_roll_{label}_std"] = rolling.std().reset_index(level=0, drop=True)
            feature_data[f"{source}_roll_{label}_min"] = rolling.min().reset_index(level=0, drop=True)
            feature_data[f"{source}_roll_{label}_max"] = rolling.max().reset_index(level=0, drop=True)

    # Extra space-weather streams get a smaller, physically relevant history
    # grid to control memory and reduce multiple-testing noise.
    for source in EXTERNAL_HISTORY:
        if source not in frame:
            continue
        grouped = groups[source]
        for label, steps in {"15m": 3, "1h": 12, "3h": 36, "6h": 72, "12h": 144, "1d": 288}.items():
            feature_data[f"{source}_lag_{label}"] = grouped.shift(steps)
        shifted = grouped.shift(1)
        shifted_groups = shifted.groupby(frame["instrument_id"], sort=False)
        for label, steps in {"1h": 12, "6h": 72, "1d": 288}.items():
            rolling = shifted_groups.rolling(steps, min_periods=max(3, steps // 4))
            feature_data[f"{source}_roll_{label}_mean"] = rolling.mean().reset_index(level=0, drop=True)
            feature_data[f"{source}_roll_{label}_std"] = rolling.std().reset_index(level=0, drop=True)
            feature_data[f"{source}_roll_{label}_max"] = rolling.max().reset_index(level=0, drop=True)
    return pd.concat([frame, pd.DataFrame(feature_data, index=frame.index)], axis=1)


def assign_split(timestamp: pd.Series) -> pd.Series:
    result = pd.Series("excluded", index=timestamp.index, dtype="string")
    for name, (start, end) in SPLITS.items():
        result.loc[(timestamp >= start) & (timestamp < end)] = name
    return result


def choose_threshold(y_true: pd.Series, probability: np.ndarray) -> float:
    candidates = np.linspace(0.05, 0.95, 181)
    scores = [f1_score(y_true, probability >= threshold, zero_division=0) for threshold in candidates]
    return float(candidates[int(np.argmax(scores))])


def classification_metrics(y_true: pd.Series, probability: np.ndarray, threshold: float) -> dict:
    prediction = (probability >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, prediction, labels=[0, 1]).ravel()
    return {
        "rows": int(len(y_true)),
        "positive_rate": float(np.mean(y_true)),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "pr_auc": float(average_precision_score(y_true, probability)),
        "f1": float(f1_score(y_true, prediction, zero_division=0)),
        "precision": float(precision_score(y_true, prediction, zero_division=0)),
        "recall": float(recall_score(y_true, prediction, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, prediction)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, prediction)),
        "brier": float(brier_score_loss(y_true, probability)),
        "threshold": float(threshold),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/processed/model_table_extended_5min.csv.gz"))
    parser.add_argument("--output-dir", type=Path, default=Path("analysis/catboost_timeseries/output_extended"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(args.input, compression="gzip", parse_dates=["timestamp"], low_memory=False)
    frame = frame.sort_values(["instrument_id", "timestamp"]).reset_index(drop=True)

    q99_thresholds = rebuild_train_only_target(frame)
    add_time_features(frame)
    frame = add_risk_state_features(frame, q99_thresholds)
    frame = add_history_features(frame)
    frame = add_orbit_repeat_features(frame)
    frame["split"] = assign_split(frame["timestamp"])

    time_features = [
        "minute_of_day_sin",
        "minute_of_day_cos",
        "day_of_year_sin",
        "day_of_year_cos",
        "longitude_sin",
        "longitude_cos",
    ]
    generated = [
        column
        for column in frame.columns
        if (
            "_lag_" in column
            or "_roll_" in column
            or "_orbit_diff_" in column
            or "_delta_" in column
        )
    ]
    features = [
        column
        for column in CURRENT_NUMERIC + CATEGORICAL + time_features + generated
        if column in frame and (column in CATEGORICAL or frame[column].notna().any())
    ]

    dataset = frame.loc[frame["split"] != "excluded", ["timestamp", "split", TARGET] + features].copy()
    dataset = dataset.loc[dataset[TARGET].notna()].reset_index(drop=True)
    for column in CATEGORICAL:
        dataset[column] = dataset[column].fillna("missing").astype(str)

    dataset_path = args.output_dir / "catboost_timeseries_dataset.csv.gz"
    dataset.to_csv(dataset_path, index=False, compression="gzip")

    train = dataset[dataset["split"] == "train"]
    valid = dataset[dataset["split"] == "valid"]
    test = dataset[dataset["split"] == "test"]

    selection_model = CatBoostClassifier(
        iterations=700,
        depth=7,
        learning_rate=0.04,
        loss_function="Logloss",
        eval_metric="AUC",
        random_seed=SEED,
        l2_leaf_reg=8,
        random_strength=1.0,
        od_type="Iter",
        od_wait=80,
        allow_writing_files=False,
        verbose=100,
    )
    selection_model.fit(
        train[features],
        train[TARGET].astype(int),
        cat_features=CATEGORICAL,
        eval_set=(valid[features], valid[TARGET].astype(int)),
        use_best_model=True,
    )

    valid_probability = selection_model.predict_proba(valid[features])[:, 1]
    threshold = choose_threshold(valid[TARGET].astype(int), valid_probability)
    best_iterations = max(1, selection_model.get_best_iteration() + 1)
    final_train = pd.concat([train, valid], ignore_index=True)
    model = CatBoostClassifier(
        iterations=best_iterations,
        depth=7,
        learning_rate=0.04,
        loss_function="Logloss",
        random_seed=SEED,
        l2_leaf_reg=8,
        random_strength=1.0,
        allow_writing_files=False,
        verbose=False,
    )
    model.fit(
        final_train[features],
        final_train[TARGET].astype(int),
        cat_features=CATEGORICAL,
    )
    test_probability = model.predict_proba(test[features])[:, 1]

    # Feature ablation uses the same refit protocol but removes orbital-repeat
    # lags/differences while retaining ordinary history and solar telemetry.
    orbit_labels = ("90m", "95m", "100m", "190m", "285m", "380m")
    without_orbit_features = [
        column for column in features
        if "_orbit_diff_" not in column and not any(column.endswith(f"_lag_{label}") for label in orbit_labels)
    ]
    ablation_selector = CatBoostClassifier(
        iterations=700, depth=7, learning_rate=0.04, loss_function="Logloss", eval_metric="AUC",
        random_seed=SEED, l2_leaf_reg=8, random_strength=1.0, od_type="Iter", od_wait=80,
        allow_writing_files=False, verbose=False,
    )
    ablation_selector.fit(
        train[without_orbit_features], train[TARGET].astype(int), cat_features=CATEGORICAL,
        eval_set=(valid[without_orbit_features], valid[TARGET].astype(int)), use_best_model=True,
    )
    ablation_iterations = max(1, ablation_selector.get_best_iteration() + 1)
    ablation_model = CatBoostClassifier(
        iterations=ablation_iterations, depth=7, learning_rate=0.04, loss_function="Logloss",
        random_seed=SEED, l2_leaf_reg=8, random_strength=1.0,
        allow_writing_files=False, verbose=False,
    )
    ablation_model.fit(
        final_train[without_orbit_features], final_train[TARGET].astype(int), cat_features=CATEGORICAL
    )
    ablation_test_probability = ablation_model.predict_proba(test[without_orbit_features])[:, 1]

    metrics = {
        "task": "classification of instrument-local Q99 exceedance in the next 6 hours",
        "target": TARGET,
        "history_days": 7,
        "horizon_hours": HORIZON_HOURS,
        "seed": SEED,
        "train_only_q99_residual_thresholds": q99_thresholds,
        "target_calibration_start": TARGET_CALIBRATION_START.isoformat(),
        "feature_count": len(features),
        "categorical_features": CATEGORICAL,
        "selection_best_iteration": int(selection_model.get_best_iteration()),
        "final_refit_iterations": best_iterations,
        "split_boundaries": {
            name: {"start": start.isoformat(), "end_exclusive": end.isoformat()}
            for name, (start, end) in SPLITS.items()
        },
        "validation": classification_metrics(valid[TARGET].astype(int), valid_probability, threshold),
        "test": classification_metrics(test[TARGET].astype(int), test_probability, threshold),
        "test_by_instrument": {},
        "constant_probability_baseline": {
            "probability": float(train[TARGET].mean()),
            "test_roc_auc": 0.5,
            "test_pr_auc": float(test[TARGET].mean()),
            "test_brier": float(brier_score_loss(test[TARGET], np.full(len(test), train[TARGET].mean()))),
        },
        "without_orbital_features_ablation": {
            "feature_count": len(without_orbit_features),
            "selection_best_iteration": int(ablation_selector.get_best_iteration()),
            "test_roc_auc": float(roc_auc_score(test[TARGET], ablation_test_probability)),
            "test_pr_auc": float(average_precision_score(test[TARGET], ablation_test_probability)),
            "test_brier": float(brier_score_loss(test[TARGET], ablation_test_probability)),
        },
    }
    for instrument, part in test.groupby("instrument_id"):
        idx = part.index
        local_probability = model.predict_proba(part[features])[:, 1]
        metrics["test_by_instrument"][instrument] = classification_metrics(
            part[TARGET].astype(int), local_probability, threshold
        )

    model.save_model(args.output_dir / "catboost_q99_6h.cbm")

    importance = pd.DataFrame(
        {"feature": features, "importance": model.get_feature_importance()}
    ).sort_values("importance", ascending=False)
    importance.to_csv(args.output_dir / "feature_importance.csv", index=False)

    predictions = test[["timestamp", "instrument_id", TARGET]].copy()
    predictions["probability"] = test_probability
    predictions["prediction"] = (test_probability >= threshold).astype(int)
    predictions.to_csv(args.output_dir / "test_predictions.csv", index=False)

    with (args.output_dir / "metrics.json").open("w", encoding="utf-8") as stream:
        json.dump(metrics, stream, ensure_ascii=False, indent=2)

    report = f"""# CatBoost: прогноз превышения Q99 на горизонте 6 часов

## Постановка

- Target: `{TARGET}` — будет ли превышен локальный исследовательский Q99 spatial residual в следующие 6 часов.
- История: лаги от 5 минут до 7 суток и rolling-статистики за 1 час, 6 часов, 1, 3 и 7 суток.
- Split: train / validation / test по времени; между частями оставлен purge-зазор 6 часов.
- Порог классификации выбран по максимуму F1 только на validation и затем зафиксирован для test.

## Результат на test

- ROC-AUC: **{metrics['test']['roc_auc']:.4f}**
- PR-AUC: **{metrics['test']['pr_auc']:.4f}** (доля положительного класса {metrics['test']['positive_rate']:.4f})
- F1: **{metrics['test']['f1']:.4f}**
- Precision: **{metrics['test']['precision']:.4f}**
- Recall: **{metrics['test']['recall']:.4f}**
- Balanced accuracy: **{metrics['test']['balanced_accuracy']:.4f}**
- Brier score: **{metrics['test']['brier']:.4f}**
- Порог: **{threshold:.3f}**, выбран только на апрельской validation

## Польза временных признаков

- CatBoost без орбитальных лагов: ROC-AUC **{metrics['without_orbital_features_ablation']['test_roc_auc']:.4f}**, PR-AUC **{metrics['without_orbital_features_ablation']['test_pr_auc']:.4f}**.
- CatBoost с орбитальными лагами и историей до 7 суток: ROC-AUC **{metrics['test']['roc_auc']:.4f}**.
- Константный baseline: ROC-AUC **0.5000**, PR-AUC **{metrics['constant_probability_baseline']['test_pr_auc']:.4f}**.

## Ограничения

- Обучение использует историю с января 2020 года; май-июнь 2024 полностью оставлены под test.
- Spatial baseline и Q99 зафиксированы по калибровочному периоду с января 2023 до конца train, чтобы расширение истории не меняло определение target.
- Q99 — исследовательская локальная метка, не эксплуатационный порог NASA.
- DOSTEL — архивный proxy внутри Columbus; его оперативная доступность не доказана.
- Перекрывающиеся шестичасовые окна дают автокорреляцию даже при честном временном split.
- Spatial baseline и Q99 оценены только на train и заморожены для validation/test.
"""
    (args.output_dir / "REPORT.md").write_text(report, encoding="utf-8")

    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
