"""Operational forecast and catalog screening adapters with explicit coverage."""
import csv
import hashlib
import io
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from .base import HttpSource
from ..bulletins import parse_three_day
from ..provenance import Record, EXTERNAL_FORECAST


class ThreeDayForecast(HttpSource):
    source_id = 'swpc.forecast'
    title = 'NOAA SWPC 3-Day Forecast'
    url = 'https://services.swpc.noaa.gov/text/3-day-forecast.txt'
    homepage = url
    units = 'Kp / % за сутки'
    cadence_s = 1800
    publication_lag_s = 0
    kind = EXTERNAL_FORECAST

    def _http_get(self, url):
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.text

    def parse(self, payload, fetched_at):
        data = parse_three_day(payload)
        return [Record(self.source_id, EXTERNAL_FORECAST, data, units=self.units,
                       url=self.url, issued_at=datetime.fromisoformat(data['issued_at']),
                       fetched_at=fetched_at,
                       note='Суточная вероятность S не задаёт время начала события; Kp — интервалы 3 ч.')]


class Socrates(HttpSource):
    source_id = 'celestrak.socrates'
    title = 'CelesTrak SOCRATES · NORAD 25544'
    url = 'https://celestrak.org/SOCRATES/sort-minRange.csv'
    homepage = 'https://celestrak.org/SOCRATES/socrates-format.php'
    units = 'km / km/s / UTC'
    cadence_s = 8 * 3600
    publication_lag_s = 0
    kind = EXTERNAL_FORECAST

    def _http_get(self, url):
        response = requests.get(url, timeout=25)
        response.raise_for_status()
        return {'csv': response.text, 'last_modified': response.headers.get('Last-Modified')}

    def parse(self, payload, fetched_at):
        reader = csv.DictReader(io.StringIO(payload['csv']))
        required = {'NORAD_CAT_ID_1', 'NORAD_CAT_ID_2', 'TCA', 'TCA_RANGE', 'TCA_RELATIVE_SPEED'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('SOCRATES schema changed')
        rows = list(reader)
        if not rows:
            raise ValueError('SOCRATES catalog empty; cannot establish screening coverage')
        issued = None
        if payload.get('last_modified'):
            issued = parsedate_to_datetime(payload['last_modified']).astimezone(timezone.utc)
        events, seen = [], set()
        for row in rows:
            if '25544' not in (row['NORAD_CAT_ID_1'], row['NORAD_CAT_ID_2']):
                continue
            other = '2' if row['NORAD_CAT_ID_1'] == '25544' else '1'
            tca = datetime.fromisoformat(row['TCA']).replace(tzinfo=timezone.utc)
            key = (row[f'NORAD_CAT_ID_{other}'], tca)
            if key in seen:
                continue
            seen.add(key)
            speed = float(row['TCA_RELATIVE_SPEED'])
            events.append({'object_id': key[0], 'object_name': row.get(f'OBJECT_NAME_{other}', ''),
                           'tca': tca.isoformat(), 'miss_km': float(row['TCA_RANGE']),
                           'relative_speed_km_s': speed,
                           'coorbital_review': speed < 0.05,
                           'max_probability_bound': float(row['MAX_PROB']) if row.get('MAX_PROB') else None,
                           'raw_row': row})
        # Never infer an archive publication time from download time.
        reference = issued or fetched_at
        data = {'events': events, 'row_count': len(rows), 'raw_sha256': hashlib.sha256(payload['csv'].encode()).hexdigest(),
                'valid_from': reference.isoformat(),
                'valid_to': (reference + timedelta(days=6)).isoformat(),
                'publication_known': issued is not None}
        return [Record(self.source_id, EXTERNAL_FORECAST, data, units=self.units,
                       url=self.url, issued_at=issued, fetched_at=fetched_at,
                       note='Каталожный скрининг до 5 км. MAX_PROB — верхняя оценка, не вероятность поражения космонавта. '
                            'Почти совместное движение требует проверки принадлежности объектов.')]
