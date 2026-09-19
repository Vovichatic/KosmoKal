#!/usr/bin/env python3
"""Acquire immutable raw NOAA issues for arbitrary May–June 2024 queries."""
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'research/eva-risk/evarisk/assets/planning'
sys.path.insert(0, str(ROOT / 'research/eva-risk'))
from evarisk.bulletins import parse_rsga


def download(day):
    url = f'https://iswa.ccmc.gsfc.nasa.gov/iswa_data_tree/composite/coupled/noaa-swpc/RSGA/{day:%Y/%m/%Y%m%d}RSGA.txt'
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    raw = response.text
    parsed = parse_rsga(raw)
    return {**parsed, 'url': url, 'raw_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'version_note': 'Dated NOAA issue preserved in NASA ISWA; content hash fixes the downloaded edition.'}


if __name__ == '__main__':
    start = datetime(2024, 4, 28)
    days = [start + timedelta(days=i) for i in range(67)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(download, days))
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / 'noaa_rsga_2024.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
    print(f'Saved {len(records)} validated NOAA issues')
