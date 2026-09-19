#!/usr/bin/env python3
"""Download extended training history while preserving May-June 2024 as test."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import certifi
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "extended_raw"
USER_AGENT = "KosmoKal-research/1.0 (public-data training)"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, target: Path, force: bool = False) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or force:
        temp = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=600, context=SSL_CONTEXT) as response:
                    with temp.open("wb") as stream:
                        while chunk := response.read(1024 * 1024):
                            stream.write(chunk)
                temp.replace(target)
                break
            except Exception:
                if temp.exists():
                    temp.unlink()
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
    return {
        "path": str(target.relative_to(REPO)),
        "url": url,
        "bytes": target.stat().st_size,
        "sha256": sha256(target),
    }


def month_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    return list(pd.date_range(start.normalize().replace(day=1), end, freq="MS", inclusive="left"))


def radlab_url(start: pd.Timestamp, end: pd.Timestamp) -> str:
    params = [
        ("spacecraft", "ISS"),
        ("instrument", "DosTel"),
        # urlencode adds the separating '='; a key ending in '>' therefore
        # produces the API expression timestamp>=value.
        ("timestamp>", start.strftime("%Y-%m-%dT%H:%M:%S")),
        ("timestamp<", end.strftime("%Y-%m-%dT%H:%M:%S")),
        ("absorbed_dose_rate", ""),
        ("flux", ""),
        ("latitude", ""),
        ("longitude", ""),
        ("altitude", ""),
        ("b", ""),
        ("l", ""),
        ("format", "csv"),
    ]
    return "https://visualization.osdr.nasa.gov/radlab/api/?" + urllib.parse.urlencode(params)


def directory_urls(base: str, suffix: str = ".nc") -> list[str]:
    request = urllib.request.Request(base, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120, context=SSL_CONTEXT) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return []
        raise
    names = sorted(set(re.findall(r'href="([^"]+' + re.escape(suffix) + r')"', html)))
    return [urllib.parse.urljoin(base, name) for name in names]


def build_jobs(start: pd.Timestamp, end: pd.Timestamp, force: bool) -> list[tuple[str, Path, bool]]:
    jobs: list[tuple[str, Path, bool]] = []
    months = month_starts(start, end)
    # RadLab rejects large responses; daily chunks stay below the public API's
    # practical response limit and are concatenated during preparation.
    for chunk_start in pd.date_range(start, end, freq="1D", inclusive="left"):
        chunk_end = min(end, chunk_start + pd.Timedelta(days=1))
        jobs.append(
            (
                radlab_url(chunk_start, chunk_end),
                RAW / "radlab" / f"dostel_{chunk_start:%Y%m%d}_{chunk_end:%Y%m%d}.csv",
                force,
            )
        )

    # One consistent satellite across the complete train/test interval.
    for month in months:
        base = (
            "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/"
            f"goes/goes16/l2/data/sgps-l2-avg5m/{month:%Y/%m}/"
        )
        for url in directory_urls(base):
            jobs.append((url, RAW / "goes16" / "sgps_5m" / f"{month:%Y-%m}" / Path(url).name, force))

    # Annual XRS files are compact and add direct flare telemetry.
    xrs_root = (
        "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/"
        "goes/goes16/l2/data/xrsf-l2-avg1m/"
    )
    for url in directory_urls(xrs_root):
        name = Path(url).name
        if any(f"_y{year}_" in name for year in range(start.year, end.year + 1)):
            jobs.append((url, RAW / "goes16" / "xrs_1m" / name, force))
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end-exclusive", default="2024-07-01")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--skip-bulk",
        action="store_true",
        help="Skip RadLab/GOES discovery and downloads (useful for refreshing indices/events).",
    )
    parser.add_argument(
        "--force-gfz",
        action="store_true",
        help="Refresh the stable-name GFZ files without redownloading the bulk archives.",
    )
    args = parser.parse_args()
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end_exclusive, tz="UTC")

    jobs = [] if args.skip_bulk else build_jobs(start, end, args.force)
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
            if number % 50 == 0 or number == len(jobs):
                print(f"downloaded/verified {number}/{len(jobs)}", flush=True)

    gfz_base = "https://kp.gfz.de/app/json/"
    for index in ("Kp", "Hp30", "Hp60", "SN", "Fobs", "Fadj"):
        query = urllib.parse.urlencode(
            {
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": (end - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "index": index,
            }
        )
        try:
            manifest.append(
                fetch(
                    f"{gfz_base}?{query}",
                    RAW / "gfz" / f"{index.lower()}.json",
                    args.force or args.force_gfz,
                )
            )
        except Exception as error:
            failures.append({"url": f"{gfz_base}?{query}", "path": f"data/extended_raw/gfz/{index.lower()}.json", "error": repr(error)})

    for event in ("CME", "FLR", "SEP", "GST", "IPS", "HSS"):
        for month in month_starts(start, end):
            chunk_start = max(start, month)
            chunk_end = min(end, month + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
            url = (
                f"https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/{event}"
                f"?startDate={chunk_start:%Y-%m-%d}&endDate={chunk_end:%Y-%m-%d}"
            )
            target = RAW / "donki" / event.lower() / f"{month:%Y-%m}.json"
            try:
                manifest.append(fetch(url, target, args.force))
            except Exception as error:
                failures.append({"url": url, "path": str(target.relative_to(REPO)), "error": repr(error)})

    output = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": {"start": args.start, "end_exclusive": args.end_exclusive},
        "files": sorted(manifest, key=lambda row: row["path"]),
        "failures": failures,
    }
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "manifest.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    total = sum(row["bytes"] for row in manifest)
    print(f"complete: {len(manifest)} files, {total / 1024 / 1024:.1f} MiB, failures={len(failures)}")


if __name__ == "__main__":
    main()
