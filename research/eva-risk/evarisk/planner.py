"""Evidence-based window comparison. No ML weights or inference code are changed."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from .illumination import in_shadow, state_intervals
from .orbit import propagate, time_grid
from .planning_data import bulletin_as_of, select_historical_orbit, orbit_is_usable
from .provenance import Record, Store, TEAM_COMPUTATION
from .windows import candidate_starts

UTC = timezone.utc
ALGORITHM = 'evarisk-evidence-2.0'
RULES = {
    'solar_probability_attention_pct': 20,
    'kp_attention': 5,
    'orbit_max_age_h': 72,
    'socrates_max_age_h': 24,
    'tca_guard_min': 30,
    'comparison_tolerance_min': 1,
}


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def clipped(a, b, start, end):
    lo, hi = max(a, start), min(b, end)
    return (lo, hi) if hi > lo else None


def union_minutes(intervals):
    total, high = 0.0, None
    for lo, hi in sorted(intervals):
        if high is None or lo > high:
            total += (hi - lo).total_seconds() / 60
        elif hi > high:
            total += (hi - high).total_seconds() / 60
        high = hi if high is None else max(high, hi)
    return total


def entry(factor, start, end, value, units, kind, evidence, explanation, **extra):
    return {'factor': factor, 'start': start.isoformat(), 'end': end.isoformat(),
            'value': value, 'units': units, 'kind': kind, 'evidence_hash': evidence,
            'explanation': explanation, **extra}


def orbit_payload(record, start, hours, mode, now):
    if record is None or not orbit_is_usable(record, start + timedelta(hours=hours)):
        return None
    row = record.payload
    tle = (row['TLE_LINE1'], row['TLE_LINE2'])
    grid = time_grid(start, hours, 60)
    end = start + timedelta(hours=hours)
    if grid[-1] != end:
        grid.append(end)
    points = propagate(*tle, grid)
    track = [{'time': p.t.isoformat(), 'lat': round(p.lat_deg, 5), 'lon': round(p.lon_deg, 5),
              'alt_km': round(p.alt_km, 2), 'in_saa': p.in_saa, 'in_shadow': in_shadow(p)} for p in points]
    if any(not 250 < p.alt_km < 600 for p in points):
        raise ValueError('Orbit outside configured ISS planning envelope')
    reference = min(max(now, start), end) if mode == 'current' else start
    current = min(track, key=lambda p: abs(dt(p['time']) - reference))
    return {'mode': mode, 'reference_time': reference.isoformat(), 'start': start.isoformat(),
            'end': end.isoformat(), 'step_s': 60, 'track': track, 'current': current,
            'source': {'id': record.source_id, 'label': 'Исторические TLE: реконструкция' if mode == 'historical' else 'CelesTrak · NORAD 25544',
                       'epoch': record.observed_at.isoformat(), 'is_fallback': False,
                       'status': 'reconstruction' if mode == 'historical' else 'current',
                       'age_h_at_end': round((end - record.observed_at).total_seconds() / 3600, 2),
                       'fetched_at': record.fetched_at.isoformat() if record.fetched_at else None,
                       'url': record.url, 'evidence_hash': record.hash},
            'precision_note': 'SGP4/TEME → вращение GMST; сферическая Земля, геоцентрическая широта. '
                              'Тень цилиндрическая, границы ±1 мин; манёвры и полутень не моделируются.'}


def choose(windows):
    complete = [w for w in windows if not w['critical_missing']]
    # Missing evidence anywhere in the search is not allowed to make that window look superior.
    for w in windows:
        w['on_pareto_front'] = False
    if not complete or windows[0]['critical_missing']:
        return {'status': 'insufficient_data', 'recommended_start': None,
                'reason': 'Недостаточно данных для сравнения выбранных механизмов; пропуски не считаются нулевым воздействием.'}
    def vector(w):
        return (w['solar_attention_min'], w['dark_minutes'], w['conjunction_overlap_min'])
    def dominates(a, b):
        x, y = vector(a), vector(b)
        return all(i <= j + 1 for i, j in zip(x, y)) and any(i < j - 1 for i, j in zip(x, y))
    front = [w for w in complete if not any(dominates(other, w) for other in complete)]
    for w in front:
        w['on_pareto_front'] = True
    if len(windows) < 2:
        return {'status': 'no_alternative', 'recommended_start': None, 'reason': 'Оценено одно окно. Увеличьте диапазон поиска для сравнения.'}
    original = windows[0]
    if original in front:
        equal = all(all(abs(a - b) <= 1 for a, b in zip(vector(original), vector(w))) for w in front)
        return {'status': 'no_improvement' if equal else 'tradeoff', 'recommended_start': None,
                'reason': 'Перенос не даёт доказанного улучшения по выбранным показателям.' if equal else
                          'Окна несравнимы: уменьшение одного воздействия увеличивает другое. Требуется выбор аналитика.'}
    if len(front) > 1 and any(any(abs(a-b)>1 for a,b in zip(vector(front[0]),vector(w))) for w in front[1:]):
        return {'status': 'tradeoff', 'recommended_start': None, 'reason': 'Есть несколько Парето-альтернатив с разными компромиссами.'}
    best = min(front, key=lambda w: w['start'])
    if best['requires_review']:
        return {'status': 'requires_review', 'recommended_start': None,
                'reason': 'Сравнение рассчитано, но предпочтительный вариант требует проверки предупреждений/ограничений.'}
    return {'status': 'recommended', 'recommended_start': best['start'],
            'reason': f"Альтернатива уменьшает экспозицию без ухудшения остальных показателей: S {original['solar_attention_min']:.0f}→{best['solar_attention_min']:.0f} мин; "
                      f"тень {original['dark_minutes']:.0f}→{best['dark_minutes']:.0f} мин; TCA {original['conjunction_overlap_min']:.0f}→{best['conjunction_overlap_min']:.0f} мин. Это предпочтение в заданном охвате, не допуск к ВКД."}


def calculate(req, batch=None, now=None, historical_records=None):
    now = now or datetime.now(UTC)
    start = req.start
    end = start + timedelta(hours=req.search_h + req.duration_h)
    cutoff = req.decision_cutoff or (start if req.mode == 'historical' else now)
    store = Store()
    issues = []
    statuses = {}
    scope = req.scope
    disabled = set(req.disabled_sources)
    if req.mode == 'historical':
        weather = bulletin_as_of(cutoff, historical_records) if 'swpc.forecast' not in disabled else None
        orbit_record = select_historical_orbit(start) if 'celestrak.gp.iss' not in disabled else None
        catalog = None
        statuses['swpc.forecast'] = {'health': 'archive' if weather else 'missing', 'detail': 'NOAA RSGA: фиксированный выпуск до общего cutoff'}
        issues.append('Историческая орбита — реконструкция; доступность её TLE на момент решения не подтверждена.')
    else:
        def get(sid):
            if sid in disabled or batch is None:
                return None
            return next(iter(batch.records.get(sid, ())), None)
        weather = get('swpc.forecast')
        orbit_record = get('celestrak.gp.iss')
        catalog = get('celestrak.socrates')
        for sid, status in (batch.statuses.items() if batch else []):
            statuses[sid] = {'health': 'disabled' if sid in disabled else status.health.value,
                             'last_success': status.last_success.isoformat() if status.last_success else None,
                             'detail': status.detail}
        if weather and (weather.issued_at is None or weather.issued_at > cutoff or now - weather.issued_at > timedelta(hours=24)):
            weather = None
        if catalog:
            ref = catalog.issued_at or catalog.fetched_at
            if ref is None or now - ref > timedelta(hours=RULES['socrates_max_age_h']):
                catalog = None
    if weather:
        store.put(weather)
        statuses['swpc.forecast'].update(issued_at=weather.issued_at.isoformat(), url=weather.url,
                                         evidence_hash=weather.hash, age_h=round((cutoff-weather.issued_at).total_seconds()/3600,2))
    if orbit_record:
        store.put(orbit_record)
    if catalog:
        store.put(catalog)
    try:
        orbit = orbit_payload(orbit_record, start, req.search_h + req.duration_h, req.mode, now)
    except (ValueError, RuntimeError) as exc:
        orbit = None
        issues.append(f'Орбита недоступна: {exc}')
    if orbit is None:
        issues.append('Нет подходящих орбитальных элементов; резервный TLE не подставляется.')
    statuses['orbit'] = {'health': 'usable' if orbit else 'missing', 'detail': issues[-1] if not orbit else orbit['source']['label']}
    statuses['conjunction'] = {'health': 'catalog' if catalog else 'missing', 'detail': 'Исторический каталог не подключён' if req.mode == 'historical' else 'Скрининг SOCRATES'}
    orbit_points = []
    if orbit:
        from .orbit import OrbitPoint
        orbit_points = [OrbitPoint(dt(p['time']),p['lat'],p['lon'],p['alt_km']) for p in orbit['track']]
    shadow_intervals = state_intervals(orbit_points, in_shadow)
    geometry = None
    if orbit:
        geometry = Record('team.illumination', TEAM_COMPUTATION,
                          {'intervals': [[a.isoformat(),b.isoformat()] for a,b in shadow_intervals],
                           'rule': 'cylindrical-shadow-v1', 'step_s': 60,
                           'constraint': {'max_dark_minutes': req.max_dark_minutes}},
                          units='min', parents=(orbit_record.hash,), issued_at=now,
                          note='Освещённость — ограничение визуальных работ, не самостоятельное доказательство опасности.')
        store.put(geometry)
    windows = []
    for t0 in candidate_starts(start, req.search_h, req.step_min):
        t1 = t0 + timedelta(hours=req.duration_h)
        timeline, cover, solar, gaps = [], [], [], []
        for seg in (weather.payload['segments'] if weather else []):
            cut = clipped(dt(seg['start']), dt(seg['end']), t0, t1)
            if not cut:
                continue
            a,b = cut
            if seg['factor'] == 'S':
                cover.append(cut)
                if seg['value'] >= RULES['solar_probability_attention_pct']:
                    solar.append(cut)
            # Keep G/R as context; do not sum correlated indices.
            timeline.append(entry(seg['factor'],a,b,seg['value'],seg['units'],seg['kind'],weather.hash,
                                  seg['meaning'], resolution=seg['resolution'],
                                  attention=seg['value'] >= (5 if seg['factor']=='G' else RULES['solar_probability_attention_pct'])))
        weather_coverage = min(1,union_minutes(cover)/(req.duration_h*60))
        if scope.weather and weather_coverage < 0.999:
            gaps.append('solar_forecast_coverage')
        if not orbit:
            gaps.append('orbit')
        dark = []
        for a,b in shadow_intervals:
            cut = clipped(a,b,t0,t1)
            if cut:
                dark.append(cut)
                timeline.append(entry('lighting',*cut,1,'тень','team_computation',geometry.hash,
                                      'Внешнее освещение отсутствует; ограничение выбранного плана работ.'))
        conjunction_intervals = []
        coorbital = False
        cat_coverage = 0.0
        if catalog:
            cut = clipped(dt(catalog.payload['valid_from']),dt(catalog.payload['valid_to']),t0,t1)
            cat_coverage = min(1,union_minutes([cut] if cut else [])/(req.duration_h*60))
            for event in catalog.payload['events']:
                tca = dt(event['tca'])
                cut = clipped(tca-timedelta(minutes=30),tca+timedelta(minutes=30),t0,t1)
                if cut:
                    conjunction_intervals.append(cut)
                    coorbital |= event['coorbital_review']
                    timeline.append(entry('conjunction',*cut,event['miss_km'],'km','external_forecast',catalog.hash,
                                          'Операционное окно проверки ±30 мин вокруг TCA; не доверительный интервал времени.',
                                          event=event, attention=True))
        if scope.conjunction and cat_coverage < 0.999:
            gaps.append('conjunction_catalog')
        if scope.mmod:
            gaps.append('mmod_model_unavailable')
        factor_completeness = {'weather': weather_coverage if scope.weather else None,
                               'lighting': float(bool(orbit)) if scope.lighting else None,
                               'conjunction': cat_coverage if scope.conjunction else None,
                               'mmod': 0.0 if scope.mmod else None,
                               'orbit': float(bool(orbit))}
        dark_minutes = union_minutes(dark) if scope.lighting else 0
        solar_minutes = union_minutes(solar) if scope.weather else 0
        conjunction_minutes = union_minutes(conjunction_intervals) if scope.conjunction else 0
        review = (solar_minutes>0 or (scope.lighting and dark_minutes>req.max_dark_minutes)
                  or conjunction_minutes>0 or coorbital and scope.conjunction)
        score = {'start': t0.isoformat(), 'end': t1.isoformat(), 'duration_h': req.duration_h,
                 'solar_attention_min': round(solar_minutes,2), 'dark_minutes': round(dark_minutes,2),
                 'conjunction_overlap_min': round(conjunction_minutes,2),
                 'factor_completeness': factor_completeness,
                 'completeness': min(v for v in factor_completeness.values() if v is not None),
                 'critical_missing': gaps, 'requires_review': bool(review),
                 'status': 'unknown' if gaps else 'attention' if review else 'no_flag_in_scope',
                 'timeline': timeline,
                 'explanation': 'S: минуты пересечения с сутками повышенной вероятности, не прогноз длительности бури. '
                                'Тень: ограничение визуальных работ. TCA: только каталожные объекты.'}
        parents = tuple(r.hash for r in (weather, geometry, catalog) if r)
        evidence = Record('team.window.v2',TEAM_COMPUTATION,dict(score),units='min / coverage',
                          parents=parents,issued_at=now,note='Показатели не объединяются в вероятность вреда человеку.')
        store.put(evidence)
        score['evidence_hash'] = evidence.hash
        windows.append(score)
    recommendation = choose(windows)
    choices = [w for w in windows[1:] if w['on_pareto_front']]
    alternative = next((w for w in choices if w['start']==recommendation['recommended_start']),
                       choices[0] if choices else (windows[1] if len(windows)>1 else None))
    if not scope.conjunction:
        issues.append('Сближения вне выбранного охвата; отсутствие оценки не означает отсутствие риска.')
    if not scope.mmod:
        issues.append('Некаталогизированные MMOD не оцениваются: нет верифицированного потока/модели пробития.')
    if req.mode == 'historical':
        issues.append('Прогноз NOAA отсечён по Issued. Орбитальная геометрия отдельно реконструирована. '
                      'Хеш фиксирует доступную архивную редакцию; независимого журнала исправлений издателя нет.')
    payload = {'schema_version':2,'algo_version':ALGORITHM,'generated_at':now.isoformat(),
               'code_revision':os.getenv('EVARISK_REVISION','see repository commit / docs/VALIDATION.md'),
               'request':req.model_dump(mode='json'),'decision_cutoff':cutoff.isoformat(),
               'replay_cutoff':cutoff.isoformat() if req.mode=='historical' else None,
               'data_mode':'issued-forecast-replay + orbit-reconstruction' if req.mode=='historical' else 'current',
               'rules':RULES,'windows':windows,'recommendation':recommendation,
               'comparison_starts':[windows[0]['start']]+([alternative['start']] if alternative else []),
               'source_status':statuses,'orbit':orbit,'limitations':issues,
               'provenance_root':store.root(),'evidence':[store.get(h).to_dict() for h in store.manifest()],
               'ml':{'frozen':True,'role':'research-only','used_for_recommendation':False,
                     'note':'Модели и параметры заморожены. Live feature parity не подтверждена; ML не снимает ограничения данных и не выдаёт допуск.'}}
    # Verification is deliberately outside the decision graph and may use later issues.
    if req.mode=='historical':
        records = historical_records
        if records is None:
            from .planning_data import historical_bulletins
            records = historical_bulletins()
        payload['verification'] = [
            {'issued_at':r.issued_at.isoformat(),'url':r.url,'raw_sha256':r.payload.get('raw_sha256'),
             'observed_proton_peak_pfu':r.payload.get('observed_proton_peak_pfu'),
             'note':'Поздняя сводка; не использована для рекомендации.'}
            for r in records if cutoff<r.issued_at<=end+timedelta(days=1)]
    payload['calculation_id']=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()[:24]
    return payload
