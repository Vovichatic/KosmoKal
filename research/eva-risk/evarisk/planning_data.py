"""Versioned historical products and orbit selection; never synthesize missing data."""
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from .provenance import Record, EXTERNAL_FORECAST, OBSERVATION

ASSETS = Path(__file__).with_name('assets') / 'planning'
UTC = timezone.utc


@lru_cache(maxsize=1)
def historical_bulletins():
    path = ASSETS / 'noaa_rsga_2024.json'
    if not path.exists():
        return []
    return [Record('noaa.rsga.archive', EXTERNAL_FORECAST, row, units='% за сутки',
                   url=row['url'], issued_at=datetime.fromisoformat(row['issued_at']),
                   fetched_at=datetime.fromisoformat(row['fetched_at']),
                   note=row['version_note']) for row in json.loads(path.read_text())]


def bulletin_as_of(cutoff, records=None):
    candidates = [r for r in (historical_bulletins() if records is None else records)
                  if r.issued_at is not None and r.issued_at <= cutoff]
    return max(candidates, key=lambda r: r.issued_at, default=None)


def tle_epoch(line1):
    stamp = line1[18:32]
    y = int(stamp[:2]); year = y + (2000 if y < 57 else 1900)
    return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=float(stamp[2:]) - 1)


@lru_cache(maxsize=1)
def historical_elements():
    path = ASSETS / 'iss_tle_2024.json'
    return json.loads(path.read_text()) if path.exists() else []


def select_historical_orbit(start):
    rows = historical_elements()
    past = [r for r in rows if datetime.fromisoformat(r['epoch']) <= start]
    row = max(past, key=lambda r: r['epoch'], default=None)
    if row is None or start - datetime.fromisoformat(row['epoch']) > timedelta(days=3):
        return None
    return Record('iss.archive', OBSERVATION, row, units='TLE', url=row['url'],
                  observed_at=datetime.fromisoformat(row['epoch']), issued_at=None,
                  note='Историческая геометрия: реконструкция. Время публикации TLE не подтверждено; '
                       'не используется как доказательство доступности орбиты в прошлом.')


def orbit_is_usable(record, end):
    if record is None or record.observed_at is None:
        return False
    age = end - record.observed_at
    return timedelta(0) <= age <= timedelta(days=3)
