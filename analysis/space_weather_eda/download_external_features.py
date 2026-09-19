#!/usr/bin/env python3
"""Download causal upstream and geosynchronous radiation features.

Sources:
- NASA CDAWeb HAPI ACE preliminary/key-parameter streams;
- NOAA NCEI GOES-16 MPS-HI five-minute Level-2 files.

The builder exposes ACE observations only after a one-hour safety lag. Raw
archives are reproducible and remain excluded from Git.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from download_extended_data import RAW, REPO, directory_urls, fetch, month_starts


HAPI = "https://cdaweb.gsfc.nasa.gov/hapi/data"


def hapi_url(dataset: str, parameters: list[str], start: pd.Timestamp, end: pd.Timestamp) -> str:
    query = urllib.parse.urlencode(
        {
            "id": dataset,
            "parameters": ",".join(["Time", *parameters]),
            "time.min": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time.max": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "format": "csv",
        }
    )
    return f"{HAPI}?{query}"


def build_jobs(start: pd.Timestamp, end: pd.Timestamp, force: bool) -> list[tuple[str, Path, bool]]:
    jobs: list[tuple[str, Path, bool]] = []
    ace = {
        "swe": ("AC_K0_SWE", ["Np", "Vp", "He_ratio", "Tpr"]),
        "mfi": ("AC_K0_MFI", ["Magnitude", "BGSEc"]),
        "epam": ("AC_H1_EPM", ["P7", "P8", "DE1", "DE2", "DE3", "DE4"]),
    }
    for month in month_starts(start, end):
        chunk_start = max(start, month)
        chunk_end = min(end, month + pd.offsets.MonthBegin(1))
        for name, (dataset, parameters) in ace.items():
            jobs.append(
                (
                    hapi_url(dataset, parameters, chunk_start, chunk_end),
                    RAW / "ace" / name / f"{month:%Y-%m}.csv",
                    force,
                )
            )

        base = (
            "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/"
            f"goes/goes16/l2/data/mpsh-l2-avg5m/{month:%Y/%m}/"
        )
        for url in directory_urls(base):
            jobs.append((url, RAW / "goes16" / "mpsh_5m" / f"{month:%Y-%m}" / Path(url).name, force))
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end-exclusive", default="2024-07-01")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end_exclusive, tz="UTC")

    jobs = build_jobs(start, end, args.force)
    manifest: list[dict] = []
    failures: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, *job): job for job in jobs}
        for number, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            url, target, _ = futures[future]
            try:
                manifest.append(future.result())
            except Exception as error:
                failures.append({"url": url, "path": str(target.relative_to(REPO)), "error": repr(error)})
                print(f"failed: {target.name}: {error}", flush=True)
            if number % 100 == 0 or number == len(jobs):
                print(f"downloaded/verified {number}/{len(jobs)}", flush=True)

    output = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": {"start": args.start, "end_exclusive": args.end_exclusive},
        "files": sorted(manifest, key=lambda row: row["path"]),
        "failures": failures,
    }
    target = RAW / "external_features_manifest.json"
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    total = sum(row["bytes"] for row in manifest)
    print(f"complete: {len(manifest)} files, {total / 1024 / 1024:.1f} MiB, failures={len(failures)}")


if __name__ == "__main__":
    main()
