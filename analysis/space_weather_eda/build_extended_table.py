#!/usr/bin/env python3
"""Build a 5-minute modeling table for 2020 through June 2024."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "extended_raw"
OUTPUT = REPO / "data" / "processed" / "model_table_extended_5min.csv.gz"


def load_dostel() -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in sorted((RAW / "radlab").glob("dostel_*.csv"))]
    raw = pd.concat(frames, ignore_index=True)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    raw = raw.drop_duplicates(["timestamp", "instrument_id"]).sort_values(["instrument_id", "timestamp"])
    numeric = ["absorbed_dose_rate", "flux", "latitude", "longitude", "altitude", "b", "l"]
    raw[numeric] = raw[numeric].apply(pd.to_numeric, errors="coerce").astype(float)
    parts = []
    for instrument, group in raw.groupby("instrument_id"):
        indexed = group.set_index("timestamp")
        part = indexed[numeric].resample("5min").median()
        part["samples_in_bin"] = indexed["absorbed_dose_rate"].resample("5min").count()
        part["instrument_id"] = instrument
        parts.append(part.reset_index())
    data = pd.concat(parts, ignore_index=True).sort_values(["instrument_id", "timestamp"])
    data["lat_bin"] = np.floor(data["latitude"] / 5.0) * 5.0
    data["lon_bin"] = np.floor(data["longitude"] / 10.0) * 10.0
    data["log_dose"] = np.log1p(data["absorbed_dose_rate"])
    return data


def load_sgps() -> pd.DataFrame:
    parts = []
    for number, path in enumerate(sorted((RAW / "goes16" / "sgps_5m").glob("*/*.nc")), start=1):
        with xr.open_dataset(path) as ds:
            flux = ds["AvgDiffProtonFlux"].values.astype(float)
            flux[flux < 0] = np.nan
            lower = ds["DiffProtonLowerEnergy"].values.astype(float)
            upper = ds["DiffProtonUpperEnergy"].values.astype(float)
            # NCEI renamed the record dimension in the v3 files. Both names
            # represent the published 5-minute science-data timestamp.
            time_name = "time" if "time" in ds.variables else "L2_SciData_TimeStamp"
            frame = pd.DataFrame({"timestamp": pd.to_datetime(ds[time_name].values, utc=True)})
            for threshold_mev in (10, 50, 100):
                threshold_kev = threshold_mev * 1000.0
                overlap = np.maximum(0.0, upper - np.maximum(lower, threshold_kev))
                proxy_by_sensor = np.nansum(flux * overlap[None, :, :], axis=2)
                frame[f"proton_flux_proxy_gt{threshold_mev}_mev"] = np.nanmedian(
                    proxy_by_sensor, axis=1
                )
            parts.append(frame)
        if number % 100 == 0:
            print(f"parsed SGPS {number}", flush=True)
    return pd.concat(parts, ignore_index=True).sort_values("timestamp").drop_duplicates("timestamp")


def load_xrs() -> pd.DataFrame:
    parts = []
    for path in sorted((RAW / "goes16" / "xrs_1m").glob("*.nc")):
        with xr.open_dataset(path) as ds:
            frame = pd.DataFrame(
                {
                    "timestamp": pd.to_datetime(ds["time"].values, utc=True),
                    "xrs_a_flux": ds["xrsa_flux"].values.astype(float),
                    "xrs_b_flux": ds["xrsb_flux"].values.astype(float),
                }
            )
            parts.append(frame)
    xrs = pd.concat(parts, ignore_index=True).sort_values("timestamp")
    xrs.loc[xrs["xrs_a_flux"] < 0, "xrs_a_flux"] = np.nan
    xrs.loc[xrs["xrs_b_flux"] < 0, "xrs_b_flux"] = np.nan
    return (
        xrs.set_index("timestamp")
        .resample("5min")
        .agg(xrs_a_flux=("xrs_a_flux", "max"), xrs_b_flux=("xrs_b_flux", "max"))
        .reset_index()
    )


def load_gfz() -> dict[str, pd.DataFrame]:
    result = {}
    for index in ("Kp", "Hp30", "Hp60", "SN", "Fobs", "Fadj"):
        path = RAW / "gfz" / f"{index.lower()}.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        frame = pd.DataFrame(
            {"timestamp": pd.to_datetime(payload["datetime"], utc=True), index: payload[index]}
        )
        if "status" in payload:
            frame[f"{index}_status"] = payload["status"]
        result[index] = frame.sort_values("timestamp")
    return result


def load_donki() -> pd.DataFrame:
    rows = []
    time_keys = ("eventTime", "startTime", "beginTime")
    for path in sorted((RAW / "donki").glob("*/*.json")):
        event_type = path.parent.name.upper()
        for item in json.loads(path.read_text(encoding="utf-8")):
            event_time = next((item.get(key) for key in time_keys if item.get(key)), None)
            rows.append(
                {
                    "event_type": event_type,
                    "event_time": pd.to_datetime(event_time, utc=True, errors="coerce"),
                    "submission_time": pd.to_datetime(item.get("submissionTime"), utc=True, errors="coerce"),
                    "notification_count": len(item.get("sentNotifications") or []),
                }
            )
    frame = pd.DataFrame(rows)
    for column in ("event_time", "submission_time"):
        frame[column] = frame[column].astype("datetime64[ns, UTC]")
    return frame


def merge_sources(dostel: pd.DataFrame, sgps: pd.DataFrame, xrs: pd.DataFrame) -> pd.DataFrame:
    for frame in (dostel, sgps, xrs):
        frame["timestamp"] = frame["timestamp"].astype("datetime64[ns, UTC]")
    gfz = load_gfz()
    for frame in gfz.values():
        frame["timestamp"] = frame["timestamp"].astype("datetime64[ns, UTC]")
    donki = load_donki()
    parts = []
    for _, group in dostel.groupby("instrument_id"):
        merged = pd.merge_asof(
            group.sort_values("timestamp"), sgps, on="timestamp", direction="backward", tolerance=pd.Timedelta("10min")
        )
        merged = pd.merge_asof(
            merged.sort_values("timestamp"), xrs, on="timestamp", direction="backward", tolerance=pd.Timedelta("10min")
        )
        for index, source in gfz.items():
            tolerance = {
                "Kp": "4h", "Hp30": "45min", "Hp60": "90min",
                "SN": "36h", "Fobs": "36h", "Fadj": "36h",
            }[index]
            merged = pd.merge_asof(
                merged.sort_values("timestamp"), source, on="timestamp",
                direction="backward", tolerance=pd.Timedelta(tolerance),
            )
        if not donki.empty:
            for event_type in ("CME", "FLR", "SEP", "GST", "IPS", "HSS"):
                published = donki.loc[
                    (donki["event_type"] == event_type) & donki["submission_time"].notna(),
                    ["submission_time", "event_time", "notification_count"],
                ].sort_values("submission_time")
                if published.empty:
                    continue
                prefix = f"donki_{event_type.lower()}"
                published = published.rename(
                    columns={
                        "submission_time": f"{prefix}_submission_time",
                        "event_time": f"{prefix}_event_time",
                        "notification_count": f"{prefix}_notification_count",
                    }
                )
                merged = pd.merge_asof(
                    merged.sort_values("timestamp"), published,
                    left_on="timestamp", right_on=f"{prefix}_submission_time", direction="backward",
                )
                merged[f"{prefix}_age_minutes"] = (
                    merged["timestamp"] - merged[f"{prefix}_submission_time"]
                ).dt.total_seconds() / 60
        parts.append(merged)
    result = pd.concat(parts, ignore_index=True).sort_values(["timestamp", "instrument_id"])

    # Explicit missing columns keep the training schema stable. They remain NaN,
    # never zero, until a publication-aware archive is added.
    numeric_missing = [
        "Dst", "s1_probability_day0", "s1_probability_day1", "s1_probability_day2",
        "expected_max_kp_3d", "swpc_forecast_age_minutes",
    ]
    for column in numeric_missing:
        if column not in result:
            result[column] = np.nan
    for event in ("cme", "flr", "sep", "gst", "ips", "hss"):
        for suffix in ("notification_count", "age_minutes"):
            column = f"donki_{event}_{suffix}"
            if column not in result:
                result[column] = np.nan
    if "Kp_status" not in result:
        result["Kp_status"] = "missing"
    result["Dst_status"] = "missing"
    return result


def main() -> None:
    dostel = load_dostel()
    print(f"DOSTEL 5-minute rows: {len(dostel):,}", flush=True)
    sgps = load_sgps()
    print(f"SGPS rows: {len(sgps):,}", flush=True)
    xrs = load_xrs()
    print(f"XRS rows: {len(xrs):,}", flush=True)
    table = merge_sources(dostel, sgps, xrs)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT, index=False, compression="gzip")
    print(f"wrote {OUTPUT}: {len(table):,} rows, {len(table.columns)} columns", flush=True)


if __name__ == "__main__":
    main()
