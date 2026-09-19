"""Dated NOAA products. Forecast validity is independent of publication time."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
MONTHS = {m: i for i, m in enumerate(
    ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}


def issued_time(text: str) -> datetime:
    match = re.search(r':Issued:\s*(\d{4})\s+(\w{3})\s+(\d{1,2})\s+(\d{2})(\d{2})\s+UTC', text)
    if not match:
        raise ValueError('NOAA bulletin has no explicit Issued time')
    y, mon, day, h, minute = match.groups()
    return datetime(int(y), MONTHS[mon], int(day), int(h), int(minute), tzinfo=UTC)


def day_near(day: int, month: str, issued: datetime) -> datetime:
    dates = [datetime(y, MONTHS[month], day, tzinfo=UTC)
             for y in (issued.year - 1, issued.year, issued.year + 1)]
    return min(dates, key=lambda d: abs(d - issued))


def parse_rsga(text: str) -> dict:
    """Daily proton-event probabilities, not hourly onset predictions or doses."""
    issued = issued_time(text)
    header = re.search(r'III\.\s+Event probabilities\s+(\d+)\s+(\w{3})\s*-\s*(\d+)\s+(\w{3})', text)
    probs = re.search(r'^Proton\s+(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', text, re.M)
    if not header or not probs:
        raise ValueError('RSGA proton forecast format not recognized')
    first = day_near(int(header[1]), header[2], issued)
    last = day_near(int(header[3]), header[4], issued)
    if last - first != timedelta(days=2):
        raise ValueError('RSGA forecast dates do not span three days')
    segments = []
    for i, value in enumerate(probs.groups()):
        p = int(value)
        if not 0 <= p <= 100:
            raise ValueError('Invalid probability')
        start = first + timedelta(days=i)
        segments.append({'factor': 'S', 'start': start.isoformat(),
                         'end': (start + timedelta(days=1)).isoformat(),
                         'value': p, 'units': '% за сутки',
                         'kind': 'external_forecast', 'resolution': 'day',
                         'meaning': 'Вероятность протонного события по NOAA за сутки; время начала неизвестно'})
    peak = re.search(r'Protons greater than 10 MeV.*?peak level of\s+([\d.]+)\s+pfu',
                     text, re.S | re.I)
    ap = re.search(r'Estimated Afr/Ap\s+\d+\s+\w+\s+\d+\s*/\s*(\d+)', text)
    return {'issued_at': issued.isoformat(), 'segments': segments,
            'observed_proton_peak_pfu': float(peak[1]) if peak else None,
            'estimated_ap': int(ap[1]) if ap else None,
            'text': text, 'product': 'NOAA RSGA'}


def parse_three_day(text: str) -> dict:
    issued = issued_time(text)
    segments = []
    # Each section explicitly labels its three daily columns.
    for factor, section, pattern in [
        ('S', 'B.', r'^S1 or greater\s+(\d+)%\s+(\d+)%\s+(\d+)%'),
        ('R', 'C.', r'^R1-R2\s+(\d+)%\s+(\d+)%\s+(\d+)%'),
    ]:
        body = text.split(section, 1)[-1]
        dates = re.search(r'^\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+)\s+((?:\w{3})\s+\d+)\s+((?:\w{3})\s+\d+)\s*$', body, re.M)
        values = re.search(pattern, body, re.M)
        if dates and values:
            for label, value in zip(dates.groups(), values.groups()):
                month, day = label.split()
                start = day_near(int(day), month, issued)
                segments.append({'factor': factor, 'start': start.isoformat(),
                                 'end': (start + timedelta(days=1)).isoformat(),
                                 'value': float(value), 'units': '% за сутки',
                                 'kind': 'external_forecast', 'resolution': 'day',
                                 'meaning': 'S1+ за сутки' if factor == 'S' else 'R1–R2 за сутки; контекст HF, не риск связи МКС'})
    a = text.split('B.', 1)[0]
    dates = re.search(r'^\s*((?:\w{3})\s+\d+)\s+((?:\w{3})\s+\d+)\s+((?:\w{3})\s+\d+)\s*$', a, re.M)
    if dates:
        for match in re.finditer(r'^(\d{2})-\d{2}UT\s+([\d.]+)(?:\s*\(G\d\))?\s+([\d.]+)(?:\s*\(G\d\))?\s+([\d.]+)', a, re.M):
            for label, value in zip(dates.groups(), match.groups()[1:]):
                month, day = label.split()
                start = day_near(int(day), month, issued) + timedelta(hours=int(match[1]))
                # A bulletin can contain already elapsed bins. Do not call those predictions.
                if start < issued:
                    continue
                segments.append({'factor': 'G', 'start': start.isoformat(),
                                 'end': (start + timedelta(hours=3)).isoformat(),
                                 'value': float(value), 'units': 'Kp',
                                 'kind': 'external_forecast', 'resolution': '3h',
                                 'meaning': 'Прогноз Kp; геомагнитный контекст, не доза'})
    if not any(s['factor'] == 'S' for s in segments):
        raise ValueError('NOAA 3-day S forecast missing')
    return {'issued_at': issued.isoformat(), 'segments': segments, 'text': text,
            'product': 'NOAA 3-Day Forecast'}
