#!/usr/bin/env python3
"""Build compact modeling tables and an EDA report for May-June 2024."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

matplotlib.use("Agg")
import matplotlib.pyplot as plt


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROCESSED = REPO / "data" / "processed"
OUTPUT = Path(__file__).resolve().parent / "output"
START = pd.Timestamp("2024-05-01T00:00:00Z")
END = pd.Timestamp("2024-07-01T00:00:00Z")


def ensure_dirs() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)


def load_dostel() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    path = RAW / "radlab" / "dostel_20240501_20240701.csv"
    raw = pd.read_csv(path)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    raw = raw.sort_values(["instrument_id", "timestamp"])
    numeric = [
        "absorbed_dose_rate",
        "flux",
        "latitude",
        "longitude",
        "altitude",
        "b",
        "l",
    ]
    frames = []
    cadence = {}
    for instrument, group in raw.groupby("instrument_id"):
        delta = group["timestamp"].diff().dt.total_seconds().dropna()
        cadence[instrument] = {
            "median_seconds": float(delta.median()),
            "p95_seconds": float(delta.quantile(0.95)),
            "max_seconds": float(delta.max()),
        }
        aggregate = group.set_index("timestamp")[numeric].resample("5min").median()
        aggregate["samples_in_bin"] = (
            group.set_index("timestamp")["absorbed_dose_rate"].resample("5min").count()
        )
        aggregate["instrument_id"] = instrument
        frames.append(aggregate.reset_index())
    data = pd.concat(frames, ignore_index=True).sort_values(["instrument_id", "timestamp"])

    data["lat_bin"] = np.floor(data["latitude"] / 5.0) * 5.0
    data["lon_bin"] = np.floor(data["longitude"] / 10.0) * 10.0
    data["log_dose"] = np.log1p(data["absorbed_dose_rate"])
    baseline = data.groupby(["instrument_id", "lat_bin", "lon_bin"])["log_dose"].transform("median")
    fallback = data.groupby("instrument_id")["log_dose"].transform("median")
    data["spatial_baseline_log_dose"] = baseline.fillna(fallback)
    data["dose_residual"] = data["log_dose"] - data["spatial_baseline_log_dose"]

    thresholds = {}
    for instrument, idx in data.groupby("instrument_id").groups.items():
        series = data.loc[idx, "dose_residual"]
        thresholds[instrument] = {
            "q95_residual": float(series.quantile(0.95)),
            "q99_residual": float(series.quantile(0.99)),
        }
        ordered = data.loc[idx].sort_values("timestamp")
        for hours, bins in ((1, 12), (3, 36), (6, 72)):
            future = ordered["dose_residual"].shift(-1)
            future_max = future.iloc[::-1].rolling(bins, min_periods=1).max().iloc[::-1]
            data.loc[ordered.index, f"target_future_max_residual_{hours}h"] = future_max.values
            data.loc[ordered.index, f"target_high_q99_{hours}h"] = (
                future_max > thresholds[instrument]["q99_residual"]
            ).astype("Int64").values

    summary = {
        "rows_raw": int(len(raw)),
        "rows_5min": int(len(data)),
        "start": raw["timestamp"].min().isoformat(),
        "end": raw["timestamp"].max().isoformat(),
        "instruments": sorted(raw["instrument_id"].unique().tolist()),
        "cadence": cadence,
        "thresholds": thresholds,
        "missing_5min_dose_fraction": float(data["absorbed_dose_rate"].isna().mean()),
        "duplicate_rows": int(raw.duplicated(["timestamp", "instrument_id"]).sum()),
        "dose_quantiles": {
            str(q): float(raw["absorbed_dose_rate"].quantile(q))
            for q in (0.5, 0.9, 0.95, 0.99, 0.999)
        },
    }
    return raw, data, summary


def load_goes_satellite(satellite: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = sorted((RAW / "goes" / f"goes{satellite}" / "sgps_5m").glob("*/*.nc"))
    frames = []
    energy_rows = []
    for file in files:
        with xr.open_dataset(file) as ds:
            flux = ds["AvgDiffProtonFlux"].values.astype(float)
            flux[flux < 0] = np.nan
            lower = ds["DiffProtonLowerEnergy"].values.astype(float)
            upper = ds["DiffProtonUpperEnergy"].values.astype(float)
            effective = ds["DiffProtonEffectiveEnergy"].values.astype(float)
            valid = ds["DiffValidL1bSamplesInAvg"].values.astype(float)
            timestamps = pd.to_datetime(ds["time"].values, utc=True)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                flux_channels = np.nanmedian(flux, axis=1)
                valid_channels = np.nanmedian(valid, axis=1)
            frame = pd.DataFrame({"timestamp": timestamps})
            frame["satellite"] = f"GOES-{satellite}"
            for channel in range(flux_channels.shape[1]):
                frame[f"p{channel + 1:02d}_diff_flux"] = flux_channels[:, channel]
                frame[f"p{channel + 1:02d}_valid_samples"] = valid_channels[:, channel]
            for threshold_mev in (10, 50, 100):
                threshold_kev = threshold_mev * 1000.0
                overlap = np.maximum(0.0, upper - np.maximum(lower, threshold_kev))
                proxy_by_sensor = np.nansum(flux * overlap[None, :, :], axis=2)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    frame[f"proton_flux_proxy_gt{threshold_mev}_mev"] = np.nanmedian(
                        proxy_by_sensor, axis=1
                    )
            frames.append(frame)
            if not energy_rows:
                for channel in range(lower.shape[1]):
                    energy_rows.append(
                        {
                            "satellite": f"GOES-{satellite}",
                            "channel": f"P{channel + 1}",
                            "lower_mev_sensor_median": float(np.nanmedian(lower[:, channel]) / 1000),
                            "upper_mev_sensor_median": float(np.nanmedian(upper[:, channel]) / 1000),
                            "effective_mev_sensor_median": float(np.nanmedian(effective[:, channel]) / 1000),
                        }
                    )
    return pd.concat(frames, ignore_index=True), pd.DataFrame(energy_rows)


def load_gfz(index: str) -> pd.DataFrame:
    path = RAW / "gfz" / f"{index.lower()}_20240501_20240630.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    frame = pd.DataFrame({"timestamp": pd.to_datetime(payload["datetime"], utc=True), index: payload[index]})
    if "status" in payload:
        frame[f"{index}_status"] = payload["status"]
    return frame


def load_dst() -> pd.DataFrame:
    rows = []
    for month in (5, 6):
        path = RAW / "kyoto_dst" / f"dst24{month:02d}.for.request"
        for line in path.read_text(encoding="ascii", errors="ignore").splitlines():
            if not line.startswith("DST"):
                continue
            day = int(line[8:10])
            values = [int(line[pos : pos + 4]) for pos in range(20, 116, 4)]
            for hour, value in enumerate(values):
                rows.append(
                    {
                        "timestamp": pd.Timestamp(year=2024, month=month, day=day, hour=hour, tz="UTC"),
                        "Dst": value,
                        "Dst_status": "provisional",
                    }
                )
    return pd.DataFrame(rows)


def load_donki() -> tuple[pd.DataFrame, pd.DataFrame]:
    events = []
    notifications = []
    time_keys = ("eventTime", "startTime", "beginTime")
    for path in sorted((RAW / "donki").glob("*.json")):
        event_type = path.stem.split("_")[0].upper()
        for item in json.loads(path.read_text(encoding="utf-8")):
            event_time = next((item.get(key) for key in time_keys if item.get(key)), None)
            submission = item.get("submissionTime")
            event_id = next((value for key, value in item.items() if key.lower().endswith("id")), None)
            event_dt = pd.to_datetime(event_time, utc=True, errors="coerce")
            submission_dt = pd.to_datetime(submission, utc=True, errors="coerce")
            delay_min = (
                (submission_dt - event_dt).total_seconds() / 60
                if pd.notna(event_dt) and pd.notna(submission_dt)
                else np.nan
            )
            events.append(
                {
                    "event_type": event_type,
                    "event_id": event_id,
                    "event_time": event_dt,
                    "submission_time": submission_dt,
                    "publication_delay_minutes": delay_min,
                    "version_id": item.get("versionId"),
                    "linked_event_count": len(item.get("linkedEvents") or []),
                    "notification_count": len(item.get("sentNotifications") or []),
                }
            )
            for note in item.get("sentNotifications") or []:
                notifications.append(
                    {
                        "event_type": event_type,
                        "event_id": event_id,
                        "message_id": note.get("messageID"),
                        "message_issue_time": pd.to_datetime(
                            note.get("messageIssueTime"), utc=True, errors="coerce"
                        ),
                        "message_url": note.get("messageURL"),
                    }
                )
    return pd.DataFrame(events), pd.DataFrame(notifications)


def load_swpc_forecasts() -> pd.DataFrame:
    rows = []
    for path in sorted((RAW / "swpc" / "3day_forecast").glob("*/*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        issued_match = re.search(r":Issued:\s*(\d{4}\s+[A-Za-z]+\s+\d{1,2}\s+\d{4})\s+UTC", text)
        probability_match = re.search(
            r"S1 or greater\s+(\d+)%\s+(\d+)%\s+(\d+)%", text, flags=re.IGNORECASE
        )
        kp_match = re.search(r"greatest expected 3 hr Kp.*?\bis\s+([0-9.]+)", text, flags=re.IGNORECASE | re.DOTALL)
        if not issued_match or not probability_match:
            continue
        issued_at = pd.to_datetime(issued_match.group(1), format="%Y %b %d %H%M", utc=True)
        rows.append(
            {
                "issued_at": issued_at,
                "s1_probability_day0": int(probability_match.group(1)) / 100,
                "s1_probability_day1": int(probability_match.group(2)) / 100,
                "s1_probability_day2": int(probability_match.group(3)) / 100,
                "expected_max_kp_3d": float(kp_match.group(1)) if kp_match else np.nan,
                "source_file": str(path.relative_to(REPO)),
            }
        )
    return pd.DataFrame(rows).sort_values("issued_at").drop_duplicates("issued_at", keep="last")


def merge_model_table(
    dostel: pd.DataFrame,
    goes: pd.DataFrame,
    gfz: dict[str, pd.DataFrame],
    dst: pd.DataFrame,
    events: pd.DataFrame,
    forecasts: pd.DataFrame,
) -> pd.DataFrame:
    dostel = dostel.copy()
    goes = goes.copy()
    dst = dst.copy()
    dostel["timestamp"] = dostel["timestamp"].astype("datetime64[ns, UTC]")
    goes["timestamp"] = goes["timestamp"].astype("datetime64[ns, UTC]")
    dst["timestamp"] = dst["timestamp"].astype("datetime64[ns, UTC]")
    gfz = {name: frame.copy() for name, frame in gfz.items()}
    for frame in gfz.values():
        frame["timestamp"] = frame["timestamp"].astype("datetime64[ns, UTC]")
    events = events.copy()
    events["submission_time"] = events["submission_time"].astype("datetime64[ns, UTC]")
    events["event_time"] = events["event_time"].astype("datetime64[ns, UTC]")
    forecasts = forecasts.copy()
    forecasts["issued_at"] = forecasts["issued_at"].astype("datetime64[ns, UTC]")
    proxy_cols = [column for column in goes if column.startswith("proton_flux_proxy_")]
    goes_features = goes.groupby("timestamp", as_index=False)[proxy_cols].max()
    result_parts = []
    for _, group in dostel.groupby("instrument_id"):
        merged = group.sort_values("timestamp")
        merged = pd.merge_asof(
            merged,
            goes_features.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
            tolerance=pd.Timedelta("10min"),
        )
        for index, frame in gfz.items():
            tolerance = {
                "Kp": pd.Timedelta("4h"),
                "Hp30": pd.Timedelta("45min"),
                "Hp60": pd.Timedelta("90min"),
                "SN": pd.Timedelta("36h"),
                "Fobs": pd.Timedelta("36h"),
                "Fadj": pd.Timedelta("36h"),
            }[index]
            merged = pd.merge_asof(
                merged.sort_values("timestamp"),
                frame.sort_values("timestamp"),
                on="timestamp",
                direction="backward",
                tolerance=tolerance,
            )
        merged = pd.merge_asof(
            merged.sort_values("timestamp"),
            dst.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
            tolerance=pd.Timedelta("90min"),
        )
        forecast_columns = [
            "issued_at",
            "s1_probability_day0",
            "s1_probability_day1",
            "s1_probability_day2",
            "expected_max_kp_3d",
        ]
        merged = pd.merge_asof(
            merged.sort_values("timestamp"),
            forecasts[forecast_columns].sort_values("issued_at"),
            left_on="timestamp",
            right_on="issued_at",
            direction="backward",
            tolerance=pd.Timedelta("72h"),
        )
        merged["swpc_forecast_age_minutes"] = (
            merged["timestamp"] - merged["issued_at"]
        ).dt.total_seconds() / 60
        for event_type in ("CME", "FLR", "SEP", "GST", "IPS", "HSS"):
            published = events.loc[
                (events["event_type"] == event_type) & events["submission_time"].notna(),
                ["submission_time", "event_time", "notification_count", "version_id"],
            ].sort_values("submission_time")
            if published.empty:
                continue
            published = published.rename(
                columns={
                    "submission_time": f"donki_{event_type.lower()}_submission_time",
                    "event_time": f"donki_{event_type.lower()}_event_time",
                    "notification_count": f"donki_{event_type.lower()}_notification_count",
                    "version_id": f"donki_{event_type.lower()}_version_id",
                }
            )
            merged = pd.merge_asof(
                merged.sort_values("timestamp"),
                published,
                left_on="timestamp",
                right_on=f"donki_{event_type.lower()}_submission_time",
                direction="backward",
            )
            merged[f"donki_{event_type.lower()}_age_minutes"] = (
                merged["timestamp"] - merged[f"donki_{event_type.lower()}_submission_time"]
            ).dt.total_seconds() / 60
        result_parts.append(merged)
    return pd.concat(result_parts, ignore_index=True).sort_values(["timestamp", "instrument_id"])


def make_figures(raw_dostel: pd.DataFrame, model: pd.DataFrame) -> None:
    daily = raw_dostel.set_index("timestamp").resample("1D").agg(
        dose_median=("absorbed_dose_rate", "median"),
        dose_p99=("absorbed_dose_rate", lambda x: x.quantile(0.99)),
        dose_max=("absorbed_dose_rate", "max"),
    )
    external = model.groupby("timestamp", as_index=True).first()
    fig, axes = plt.subplots(4, 1, figsize=(14, 11), sharex=True)
    axes[0].plot(daily.index, daily["dose_median"], label="DOSTEL median")
    axes[0].plot(daily.index, daily["dose_p99"], label="DOSTEL p99")
    axes[0].set_ylabel("µGy/h")
    axes[0].set_yscale("log")
    axes[0].legend()
    axes[1].plot(external.index, external["proton_flux_proxy_gt10_mev"])
    axes[1].set_ylabel("GOES >10 MeV\nproxy")
    axes[1].set_yscale("symlog", linthresh=1e-4)
    axes[2].plot(external.index, external["Hp30"], label="Hp30")
    axes[2].plot(external.index, external["Kp"], alpha=0.8, label="Kp")
    axes[2].set_ylabel("geomagnetic index")
    axes[2].legend()
    axes[3].plot(external.index, external["Dst"], color="tab:red")
    axes[3].axhline(-100, color="black", linestyle="--", linewidth=0.8)
    axes[3].set_ylabel("Dst, nT")
    axes[3].set_xlabel("UTC")
    fig.suptitle("May-June 2024: ISS radiation proxy and external environment")
    fig.tight_layout()
    fig.savefig(OUTPUT / "timeline_overview.png", dpi=160)
    plt.close(fig)

    sample = raw_dostel.iloc[::5]
    fig, ax = plt.subplots(figsize=(12, 5.5))
    points = ax.scatter(
        sample["longitude"],
        sample["latitude"],
        c=np.log1p(sample["absorbed_dose_rate"]),
        s=3,
        cmap="magma",
        alpha=0.65,
    )
    fig.colorbar(points, ax=ax, label="log(1 + absorbed dose rate)")
    ax.set(xlabel="longitude, deg", ylabel="latitude, deg", title="DOSTEL spatial radiation pattern")
    fig.tight_layout()
    fig.savefig(OUTPUT / "dostel_spatial_map.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for instrument, group in raw_dostel.groupby("instrument_id"):
        values = np.log1p(group["absorbed_dose_rate"].dropna())
        ax.hist(values, bins=100, density=True, histtype="step", linewidth=1.4, label=instrument)
    ax.set(xlabel="log(1 + absorbed dose rate, µGy/h)", ylabel="density", title="Detector-conditioned target distribution")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT / "dostel_distribution.png", dpi=160)
    plt.close(fig)

    corr_columns = [
        "dose_residual",
        "target_future_max_residual_1h",
        "target_future_max_residual_3h",
        "target_future_max_residual_6h",
        "latitude",
        "altitude",
        "b",
        "l",
        "proton_flux_proxy_gt10_mev",
        "proton_flux_proxy_gt50_mev",
        "proton_flux_proxy_gt100_mev",
        "Hp30",
        "Kp",
        "Dst",
        "SN",
        "Fobs",
    ]
    corr = model[corr_columns].corr(method="spearman")
    fig, ax = plt.subplots(figsize=(12, 10))
    image = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=75, ha="right", fontsize=8)
    ax.set_yticks(range(len(corr)), corr.columns, fontsize=8)
    fig.colorbar(image, ax=ax, label="Spearman correlation")
    ax.set_title("Feature/target correlations (descriptive, not causal)")
    fig.tight_layout()
    fig.savefig(OUTPUT / "correlation_matrix.png", dpi=160)
    plt.close(fig)


def build_report(
    dostel_summary: dict,
    goes: pd.DataFrame,
    gfz: dict[str, pd.DataFrame],
    dst: pd.DataFrame,
    events: pd.DataFrame,
    forecasts: pd.DataFrame,
    model: pd.DataFrame,
) -> None:
    event_counts = events.groupby("event_type").size().to_dict()
    event_delays = events.groupby("event_type")["publication_delay_minutes"].median().dropna().to_dict()
    goes_missing = {
        column: float(goes[column].isna().mean())
        for column in goes
        if column.startswith("proton_flux_proxy_")
    }
    q = dostel_summary["dose_quantiles"]
    high_by_instrument = (
        model.groupby("instrument_id")["target_high_q99_6h"].mean().round(4).to_dict()
    )
    report = f"""# EDA данных для прогноза радиационных окон ВКД

Период анализа: **2024-05-01 00:00 UTC — 2024-07-01 00:00 UTC**.

## Что загружено

- NASA OSDR RadLab DOSTEL: **{dostel_summary['rows_raw']:,}** исходных измерений,
  приборы {', '.join(dostel_summary['instruments'])};
- NOAA GOES SGPS: **{len(goes):,}** пяти­минутных satellite-records для GOES-16/18;
- GFZ: Kp, Hp30, Hp60, SSN, observed/adjusted F10.7;
- Kyoto WDC: **{len(dst):,}** часовых provisional Dst;
- NASA DONKI: {sum(event_counts.values()):,} событий шести типов и отдельные времена публикации;
- NOAA SPE catalog: полный справочный HTML-архив с 1976 года.

## Главные результаты

1. **DOSTEL пригоден как основной исторический target/proxy.** Покрытие идёт от
   `{dostel_summary['start']}` до `{dostel_summary['end']}`. Доля пустых 5-минутных
   target-бинов: **{dostel_summary['missing_5min_dose_fraction']:.2%}**;
   дубли по `(timestamp, instrument_id)`: **{dostel_summary['duplicate_rows']}**.

2. Распределение дозы крайне асимметрично: медиана **{q['0.5']:.3f} µGy/h**,
   p95 **{q['0.95']:.3f}**, p99 **{q['0.99']:.3f}**, p99.9 **{q['0.999']:.3f}**.
   Поэтому регрессировать нужно `log1p(dose_rate)` или spatial residual, а не сырую дозу.

3. Сильнейшая структура target связана с положением МКС и SAA. Нужен
   `instrument_id`-conditioned spatial baseline; простое смешивание DosTel1/2 создаёт
   ошибку из-за различной локальной геометрии и отклика.

4. GOES содержит дифференциальные каналы 1–500 MeV. В подготовленной таблице
   `proton_flux_proxy_gt10/50/100_mev` — **интегральные прокси, вычисленные из
   дифференциальных каналов**, а не официальные NOAA integral pfu thresholds.
   Доли пропусков: {json.dumps(goes_missing, ensure_ascii=False)}.

5. Майская Gannon storm отчётливо видна по Dst/Hp30, но её нельзя автоматически
   размечать как радиационно опасное окно: geomagnetic disturbance и proton radiation
   — разные механизмы.

6. DONKI обязательно присоединять по `submissionTime <= cutoff`, не только по
   `eventTime`. Число событий: {json.dumps(event_counts, ensure_ascii=False)}.
   Медианные задержки публикации, мин: {json.dumps(event_delays, ensure_ascii=False)}.

7. Архив NOAA SWPC содержит **{len(forecasts)} из ожидаемых 122** выпусков
   3-day Forecast (**{len(forecasts) / 122:.1%}**). Между 14 мая и 16 июня в публичном
   NCEI-каталоге есть крупный разрыв, поэтому feature ограничен сроком действия 72 часа
   и после этого становится missing, а не бесконечно forward-filled.
   Максимальная выданная вероятность `S1 or greater` в периоде —
   **{forecasts[['s1_probability_day0', 's1_probability_day1', 's1_probability_day2']].max().max():.0%}**.
   Это лучший готовый publication-aware feature для честного прогноза из прошлого.

8. Доля положительных 6-часовых окон по исследовательскому локальному Q99:
   {json.dumps(high_by_instrument, ensure_ascii=False)}. Это label для эксперимента,
   а не медицинский или эксплуатационный NASA threshold.

## Рекомендация по модели

- **Target:** будущий максимум spatial residual за 1/3/6 ч и интеграл dose proxy по окну;
- **lagged features:** прошлые DOSTEL dose/flux только при доказанной доступности к cutoff;
- **external features:** GOES proton channels/proxies, DONKI/SWPC publication-aware events;
- **orbit features:** latitude/longitude, altitude, B, L и их extrema по будущему окну;
- **magnetosphere:** Hp30/Hp60 и Dst как модификаторы geomagnetic cutoff;
- **slow context:** SSN/F10.7, но не как краткосрочный alarm;
- **split:** temporal/event-based; окна проверки не участвуют ни в обучении, ни в threshold tuning.

## Ограничения

- DOSTEL измеряет внутри Columbus и не равен дозе человека во время EVA.
- RadLab в этом EDA используется как архивный ground truth; его real-time latency не доказана.
- Исторические TLE/OMM с временем публикации не скачаны: Space-Track требует учётную
  запись, а CelesTrak historical request требует форму, e-mail и CAPTCHA. Для строгого
  replay этот пробел нужно закрыть отдельно.
- Kyoto provisional Dst доступен только для некоммерческого использования.
- Данные DONKI могли редактироваться после события; для replay используются сохранённые
  `submissionTime`, `versionId` и notification issue times, но архивность каждой версии
  надо проверять отдельно.

## Артефакты

- `data/processed/model_table_5min.csv.gz` — объединённая таблица features/targets;
- `data/processed/goes_sgps_5min.csv.gz` — компактные GOES channels/proxies;
- `data/processed/donki_events.csv` и `donki_notifications.csv`;
- `data/processed/swpc_3day_forecasts.csv` — выпуски с S1+ probabilities и `issued_at`;
- `data/processed/source_inventory.csv` — покрытие, cadence, роль и ограничения источников;
- `analysis/space_weather_eda/output/*.png` — графики;
- `data/raw/manifest.json` — URL, размер и SHA-256 всех сырых файлов.
"""
    (OUTPUT / "EDA_REPORT.md").write_text(report, encoding="utf-8")


def write_source_inventory(
    raw_dostel: pd.DataFrame,
    goes: pd.DataFrame,
    gfz: dict[str, pd.DataFrame],
    dst: pd.DataFrame,
    events: pd.DataFrame,
    forecasts: pd.DataFrame,
) -> None:
    rows = []

    def add(source: str, frame: pd.DataFrame, time_col: str, role: str, notes: str) -> None:
        times = frame[time_col].dropna().sort_values().drop_duplicates()
        cadence = times.diff().dt.total_seconds().median() if len(times) > 1 else np.nan
        rows.append(
            {
                "source": source,
                "rows": len(frame),
                "start_utc": times.min().isoformat() if len(times) else None,
                "end_utc": times.max().isoformat() if len(times) else None,
                "median_cadence_seconds": cadence,
                "recommended_role": role,
                "notes": notes,
            }
        )

    add("NASA RadLab DOSTEL", raw_dostel, "timestamp", "target / historical ground truth", "Inside Columbus; not human EVA dose")
    for satellite, frame in goes.groupby("satellite"):
        add(f"NOAA {satellite} SGPS", frame, "timestamp", "external proton features", "Differential 1-500 MeV; derived integral proxies are not official NOAA pfu")
    for index, frame in gfz.items():
        role = "slow solar-cycle context" if index in {"SN", "Fobs", "Fadj"} else "geomagnetic feature"
        add(f"GFZ {index}", frame, "timestamp", role, "Join backward from cutoff")
    add("Kyoto provisional Dst", dst, "timestamp", "geomagnetic feature", "Non-commercial use; provisional values")
    for event_type, frame in events.groupby("event_type"):
        add(f"NASA DONKI {event_type}", frame, "submission_time", "publication-aware event feature", "Use submission_time, not future final knowledge")
    add("NOAA SWPC 3-day Forecast", forecasts, "issued_at", "primary replay forecast feature", "Issued product; includes S1+ probabilities for three days")
    pd.DataFrame(rows).to_csv(PROCESSED / "source_inventory.csv", index=False)


def main() -> None:
    ensure_dirs()
    raw_dostel, dostel, dostel_summary = load_dostel()
    goes_parts = []
    energy_parts = []
    for satellite in (16, 18):
        data, energy = load_goes_satellite(satellite)
        goes_parts.append(data)
        energy_parts.append(energy)
    goes = pd.concat(goes_parts, ignore_index=True).sort_values(["timestamp", "satellite"])
    energy = pd.concat(energy_parts, ignore_index=True)
    gfz = {index: load_gfz(index) for index in ("Kp", "Hp30", "Hp60", "SN", "Fobs", "Fadj")}
    dst = load_dst()
    events, notifications = load_donki()
    forecasts = load_swpc_forecasts()
    model = merge_model_table(dostel, goes, gfz, dst, events, forecasts)

    goes.to_csv(PROCESSED / "goes_sgps_5min.csv.gz", index=False, compression="gzip")
    energy.to_csv(PROCESSED / "goes_sgps_energy_channels.csv", index=False)
    dst.to_csv(PROCESSED / "dst_hourly.csv", index=False)
    events.to_csv(PROCESSED / "donki_events.csv", index=False)
    notifications.to_csv(PROCESSED / "donki_notifications.csv", index=False)
    forecasts.to_csv(PROCESSED / "swpc_3day_forecasts.csv", index=False)
    model.to_csv(PROCESSED / "model_table_5min.csv.gz", index=False, compression="gzip")
    write_source_inventory(raw_dostel, goes, gfz, dst, events, forecasts)
    (OUTPUT / "eda_summary.json").write_text(
        json.dumps(dostel_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    make_figures(raw_dostel, model)
    build_report(dostel_summary, goes, gfz, dst, events, forecasts, model)
    print(f"DOSTEL raw rows: {len(raw_dostel):,}")
    print(f"GOES rows: {len(goes):,}")
    print(f"Model rows: {len(model):,}")
    print(f"Report: {OUTPUT / 'EDA_REPORT.md'}")


if __name__ == "__main__":
    main()
