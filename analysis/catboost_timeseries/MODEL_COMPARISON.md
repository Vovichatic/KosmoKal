# CatBoost model comparison

Все варианты используют один и тот же target: превышение локального Q99 в
следующие 6 часов. Spatial baseline и Q99 калибруются только на периоде с
2023-01-01 до конца train. Май–июнь 2024 полностью отложены под test; пороги
классификации выбираются только на апрельской validation.

| Model | Features | ROC-AUC | PR-AUC | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| High-recall (`output_extended`) | 325 | 0.8206 | 0.8443 | 0.7273 | **0.7871** | **0.7560** |
| High-score v2 (`output_v2`) | 371 | **0.8413** | **0.8630** | **0.8419** | 0.6257 | 0.7179 |
| No-orbit | 265 | 0.8297 | 0.8566 | 0.8076 | 0.6600 | 0.7264 |

## What changed in v2

- distance and ratio to the fixed instrument-local Q99;
- recent exceedance rate and rolling maximum/Q90 of the Q99 margin;
- 15-minute, 1-hour, 6-hour and 1-day deltas;
- log-scaled DOSTEL flux and GOES proton channels;
- existing causal lags and rolling statistics up to 7 days;
- NOAA GOES XRS/SGPS, GFZ and publication-aware NASA DONKI telemetry.

The v2 feature set improves ranking and precision. The earlier model remains
the preferred operating profile when missing a hazardous interval is more
expensive than issuing an extra warning.

## Reproduction

```bash
.venv/bin/python analysis/space_weather_eda/download_extended_data.py \
  --start 2020-01-01 --end-exclusive 2024-07-01
.venv/bin/python analysis/space_weather_eda/build_extended_table.py
python3 analysis/catboost_timeseries/train_catboost.py \
  --output-dir analysis/catboost_timeseries/output_v2
```
