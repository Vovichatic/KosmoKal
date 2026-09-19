#!/usr/bin/env python3
"""Download reproducible public inputs for the May-June 2024 EVA-risk replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import certifi


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
START = "2024-05-01"
END_EXCLUSIVE = "2024-07-01"
USER_AGENT = "KosmoKal-research/1.0 (public-data EDA)"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, target: Path, *, force: bool = False) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or force:
        temp = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(
                    request, timeout=600, context=SSL_CONTEXT
                ) as response:
                    with temp.open("wb") as stream:
                        while chunk := response.read(1024 * 1024):
                            stream.write(chunk)
                temp.replace(target)
                break
            except Exception as error:  # network retry boundary
                last_error = error
                if temp.exists():
                    temp.unlink()
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        if last_error is not None and not target.exists():
            raise last_error
    return {
        "path": str(target.relative_to(REPO)),
        "url": url,
        "bytes": target.stat().st_size,
        "sha256": sha256(target),
    }


def radlab_url() -> str:
    params = [
        ("spacecraft", "ISS"),
        ("instrument", "DosTel"),
        ("timestamp>", f"{START}T00:00:00"),
        ("timestamp<", f"{END_EXCLUSIVE}T00:00:00"),
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


def goes_files(satellite: int, year: int, month: int) -> list[str]:
    base = (
        "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/"
        f"goes/goes{satellite}/l2/data/sgps-l2-avg5m/{year}/{month:02d}/"
    )
    request = urllib.request.Request(base, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120, context=SSL_CONTEXT) as response:
        html = response.read().decode("utf-8", errors="replace")
    names = sorted(set(re.findall(r'href="([^"]+\.nc)"', html)))
    return [urllib.parse.urljoin(base, name) for name in names]


def directory_files(base: str, suffix: str) -> list[str]:
    request = urllib.request.Request(base, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120, context=SSL_CONTEXT) as response:
        html = response.read().decode("utf-8", errors="replace")
    names = sorted(set(re.findall(r'href="([^"]+)' + re.escape(suffix) + r'"', html)))
    return [urllib.parse.urljoin(base, name + suffix) for name in names]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="redownload existing files")
    parser.add_argument(
        "--skip-goes", action="store_true", help="skip the larger GOES NetCDF archive"
    )
    args = parser.parse_args()
    manifest: list[dict] = []

    manifest.append(
        fetch(
            radlab_url(),
            RAW / "radlab" / "dostel_20240501_20240701.csv",
            force=args.force,
        )
    )

    swpc_products = {
        "3day_forecast": "3day_forecast",
        "forecast_discussion": "discussion",
        "solar_geophysical_activity_summary": "solar_geophysical_activity_summaries",
    }
    swpc_root = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports"
    for local_name, remote_name in swpc_products.items():
        for month in (5, 6):
            base = f"{swpc_root}/{remote_name}/2024/{month:02d}/"
            for url in directory_files(base, ".txt"):
                target = RAW / "swpc" / local_name / f"2024-{month:02d}" / Path(url).name
                manifest.append(fetch(url, target, force=args.force))

    gfz_base = "https://kp.gfz.de/app/json/"
    for index in ("Kp", "Hp30", "Hp60", "SN", "Fobs", "Fadj"):
        query = urllib.parse.urlencode(
            {
                "start": f"{START}T00:00:00Z",
                "end": "2024-06-30T23:59:59Z",
                "index": index,
            }
        )
        manifest.append(
            fetch(
                f"{gfz_base}?{query}",
                RAW / "gfz" / f"{index.lower()}_20240501_20240630.json",
                force=args.force,
            )
        )

    for month in (5, 6):
        name = f"dst24{month:02d}.for.request"
        url = f"https://wdc.kugi.kyoto-u.ac.jp/dst_provisional/2024{month:02d}/{name}"
        manifest.append(fetch(url, RAW / "kyoto_dst" / name, force=args.force))

    for event in ("CME", "FLR", "SEP", "GST", "IPS", "HSS"):
        url = (
            f"https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/{event}"
            f"?startDate={START}&endDate=2024-06-30"
        )
        manifest.append(
            fetch(
                url,
                RAW / "donki" / f"{event.lower()}_20240501_20240630.json",
                force=args.force,
            )
        )

    manifest.append(
        fetch(
            "https://www.ngdc.noaa.gov/stp/space-weather/interplanetary-data/"
            "solar-proton-events/SEP%20page%20code.html",
            RAW / "noaa" / "solar_proton_events_1976_present.html",
            force=args.force,
        )
    )

    if not args.skip_goes:
        for satellite in (16, 18):
            for month in (5, 6):
                for url in goes_files(satellite, 2024, month):
                    target = RAW / "goes" / f"goes{satellite}" / "sgps_5m" / f"2024-{month:02d}" / Path(url).name
                    manifest.append(fetch(url, target, force=args.force))

    output = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": {"start": START, "end_exclusive": END_EXCLUSIVE},
        "files": sorted(manifest, key=lambda row: row["path"]),
    }
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "manifest.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = sum(row["bytes"] for row in manifest)
    print(f"Downloaded/verified {len(manifest)} files, {total / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    main()
