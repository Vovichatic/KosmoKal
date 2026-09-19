import math
from datetime import datetime, timedelta, timezone

import pytest

from evarisk.orbit import (cutoff_rigidity_gv, demo_tle, propagate, time_grid,
                           transmission)
from evarisk.provenance import Record, Store, OBSERVATION, TEAM_COMPUTATION
from evarisk.risk.mmod import assess_mmod, pnp, PNP_REQUIREMENT
from evarisk.risk.fusion import fuse
from evarisk.windows import WindowScore, pareto_front, recommend, completeness
from evarisk.cli import synthetic_event
from evarisk.ml import live_radiation_forecaster, radiation_forecaster

UTC = timezone.utc
T0 = datetime(2024, 5, 11, 12, tzinfo=UTC)


def test_record_hash_is_content_addressed():
    a = Record("s", OBSERVATION, {"x": 1}, issued_at=T0)
    b = Record("s", OBSERVATION, {"x": 1}, issued_at=T0)
    c = Record("s", OBSERVATION, {"x": 2}, issued_at=T0)
    assert a.hash == b.hash and a.hash != c.hash


def test_store_delta_sync_sends_only_missing():
    s = Store()
    hashes = [s.put(Record("s", OBSERVATION, {"i": i}, issued_at=T0)) for i in range(10)]
    assert len(s.missing_from(hashes[:7])) == 3
    assert len(s.missing_from(hashes)) == 0


def test_replay_cutoff_drops_later_publications():
    s = Store()
    s.put(Record("s", OBSERVATION, {"x": 1}, issued_at=T0))
    s.put(Record("s", OBSERVATION, {"x": 2}, issued_at=T0 + timedelta(hours=2)))
    assert len(s.as_of(T0 + timedelta(hours=1))) == 1


def test_lineage_reaches_source_leaves():
    s = Store()
    src = Record("swpc", OBSERVATION, {"flux": 240}, issued_at=T0)
    s.put(src)
    calc = Record("team", TEAM_COMPUTATION, {"dose": 1.0}, parents=(src.hash,), issued_at=T0)
    s.put(calc)
    assert {r.source_id for r in s.lineage(calc.hash)} == {"team", "swpc"}


def test_cutoff_rigidity_high_at_equator_low_at_poles():
    eq = cutoff_rigidity_gv(0.0, -72.68, 420, kp=0)
    pole = cutoff_rigidity_gv(80.65, -72.68, 420, kp=0)
    assert eq > 10.0 and pole < 1.0


def test_storm_suppresses_cutoff():
    quiet = cutoff_rigidity_gv(45.0, 0.0, 420, kp=0)
    storm = cutoff_rigidity_gv(45.0, 0.0, 420, kp=8)
    assert storm < quiet


def test_transmission_monotone_in_energy():
    assert transmission(5.0, 1000) > transmission(5.0, 100) >= transmission(5.0, 10)


def test_sgp4_gives_low_earth_orbit():
    l1, l2 = demo_tle()
    pts = propagate(l1, l2, time_grid(T0, 1.5, 300))
    assert all(380 < p.alt_km < 460 for p in pts)
    assert max(abs(p.lat_deg) for p in pts) == pytest.approx(51.6, abs=1.0)


def test_pnp_shrinks_with_duration():
    assert pnp(4.0) > pnp(6.5) > pnp(8.0)
    # линейность по T при малых N: 8ч→6.5ч даёт ~19% выигрыша
    p8, p65 = 1 - pnp(8.0), 1 - pnp(6.5)
    assert 0.17 < (p8 - p65) / p8 < 0.20


def test_pnp_requirement_boundary():
    assert pnp(6.5, flux_per_m2_year=3.0) >= PNP_REQUIREMENT
    assert pnp(6.5, flux_per_m2_year=30.0) < PNP_REQUIREMENT


def test_conjunction_guard_window():
    tca = T0 + timedelta(hours=2)
    a = assess_mmod(T0, 6.5, [{"object": "DEB", "tca": tca, "miss_km": 1.0}])
    assert a.conjunction_overlap_min == pytest.approx(60.0)
    b = assess_mmod(T0, 1.0, [{"object": "DEB", "tca": T0 + timedelta(hours=12)}])
    assert b.conjunction_overlap_min == 0.0


def test_correlated_scales_are_not_double_counted():
    together = fuse({"S": 3, "G": 4, "R": 2}, 0.004, 0.4)
    assert together.combined_weather < together.naive_sum
    assert together.double_counting_avoided > 0.05


def test_mmod_stays_separate_from_weather():
    r = fuse({"S": 5, "G": 5, "R": 5}, 0.004, 1.0)
    assert r.components["mmod"] == 0.004
    assert r.components["weather"] != r.components["mmod"]


def _w(dose, pen, ov, comp, h=0):
    return WindowScore(T0 + timedelta(hours=h), 6.5, dose, pen, ov, comp,
                       0.1, 3.0, 0.0, "")


def test_pareto_front_keeps_incomparable_windows():
    lo_dose_hi_overlap = _w(100, 0.004, 60, 1.0, 0)
    hi_dose_no_overlap = _w(300, 0.004, 0, 1.0, 2)
    dominated = _w(400, 0.004, 90, 1.0, 4)
    front = pareto_front([lo_dose_hi_overlap, hi_dose_no_overlap, dominated])
    assert len(front) == 2 and dominated not in front


def test_recommend_reports_insufficient_grounds_on_low_completeness():
    v = recommend([_w(100, 0.004, 0, 0.25, 0), _w(120, 0.004, 0, 0.25, 2)])
    assert v["verdict"] == "оснований для выбора недостаточно"


def test_recommend_single_winner():
    v = recommend([_w(100, 0.004, 0, 1.0, 0), _w(300, 0.005, 60, 1.0, 2)])
    assert v["verdict"] == "рекомендуется окно"


def test_completeness_counts_stale_data_as_missing():
    statuses = {"a": True, "b": True}
    fresh = completeness(statuses, {"a": 60, "b": 60}, {"a": 1800, "b": 1800})
    stale = completeness(statuses, {"a": 60, "b": 99999}, {"a": 1800, "b": 1800})
    assert fresh == 1.0 and stale == 0.5


def test_failed_source_is_not_zero_risk():
    """Отказ источника снижает полноту, но не обнуляет риск."""
    statuses = {"a": True, "b": False}
    assert completeness(statuses, {"a": 60}, {"a": 1800}) == 0.5


def test_historical_ml_forecast_is_available_on_holdout():
    forecast = radiation_forecaster().predict(T0)
    assert forecast is not None
    assert 0.0 <= forecast.probability <= 1.0
    assert forecast.as_dict()["horizon_h"] == 6


def test_historical_ml_forecast_rejects_dates_outside_holdout():
    assert radiation_forecaster().predict(datetime(2026, 1, 1, tzinfo=UTC)) is None


def test_live_ml_forecast_uses_available_goes_kp_and_orbit_features():
    protons, kps = synthetic_event(T0 - timedelta(hours=24), hours=24, peak_pfu=30)
    result = live_radiation_forecaster().predict(T0, protons, kps, demo_tle())
    assert result is not None
    assert result["model"] == "catboost-goes-kp-q99-6h-live-v1"
    assert 0.0 <= result["probability"] <= 1.0
    assert result["confidence"] == "high"
