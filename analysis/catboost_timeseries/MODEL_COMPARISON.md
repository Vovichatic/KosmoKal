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
| Balanced recall (`output_recall_search_fine`) | 371 | **0.8442** | **0.8643** | 0.7277 | 0.8246 | 0.7732 |
| Aggressive recall (`output_recall_search_existing`) | 371 | 0.8424 | 0.8614 | 0.7028 | **0.8564** | 0.7720 |

Для recall-профилей порог выбирается только на апрельской validation как
максимальный recall при `precision >= 0.60`. Aggressive-профиль увеличивает
recall на 6.94 процентного пункта относительно прежнего high-recall при
снижении test precision на 2.45 пункта. F2 растёт с 0.7743 до 0.8206.

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

## Подбор CatBoost под recall

Проверены `Logloss` и `CrossEntropy`, depth 6–8, `l2_leaf_reg`,
`random_strength`, `rsm` и веса положительного класса 1.05–1.20. В CatBoost
Recall, F1 и PRAUC нельзя использовать как оптимизируемый loss, поэтому модель
обучается по Logloss/CrossEntropy, а рабочая точка выбирается по validation.

Лучший aggressive-профиль использует depth 7, learning rate 0.04,
`l2_leaf_reg=8`, `random_strength=0.5` и `class_weights=[1.0, 1.10]`.
Balanced-профиль использует вес положительного класса 1.15 и более высокий
порог. Автоматические `Balanced` weights здесь не подходят: положительный класс
в длинном train сам является большинством, а распределение меняется во времени.
Ограничение CatBoost на оптимизируемые classification losses документировано в
`https://catboost.ai/docs/en/concepts/loss-functions-classification`.

## Абляция NASA ACE и NOAA MPS-HI

В экспериментальную v3-таблицу добавлены предварительные 5-минутные ACE
SWEPAM/MFI/EPAM с часовым availability lag и GOES-16 MPS-HI (электроны
50 keV–4 MeV, интегральный канал >2 MeV, протоны 80 keV–12 MeV). Результаты
при одинаковой recall-настройке:

| Дополнительные признаки | ROC-AUC | PR-AUC | Precision | Recall | F2 |
|---|---:|---:|---:|---:|---:|
| Нет, balanced tuned | **0.8442** | **0.8643** | 0.7277 | **0.8246** | **0.8032** |
| MPS-HI | 0.8360 | 0.8587 | 0.7342 | 0.7930 | 0.7805 |
| ACE | 0.8330 | 0.8499 | 0.7409 | 0.7756 | 0.7684 |
| ACE + MPS-HI | 0.8354 | 0.8548 | **0.7672** | 0.7465 | 0.7506 |

Новые каналы не вошли в финальную модель: они немного улучшают старый baseline,
но проигрывают корректно настроенному CatBoost без них. Вероятная причина —
domain shift между тихой апрельской validation и майской геомагнитной бурей,
а также архивная переработка продуктов. Загрузчики и метрики сохранены для
воспроизводимости, но результат не заявляется как operational replay.

## Сравнение с простыми текущими правилами

Проверка выполнена на том же полностью отложенном периоде май–июнь 2024.
Порог DOSTEL — локальный Q99, рассчитанный только по train. Порог GOES — Q99
прокси `>10 MeV` на train; это производный прокси из дифференциальных каналов,
а не официальный интегральный порог NOAA в pfu.

| Метод | Precision | Recall | F1 | Доля тревог |
|---|---:|---:|---:|---:|
| Текущий DOSTEL выше локального Q99 | 0.803 | 0.035 | 0.067 | 0.022 |
| Текущий GOES-прокси выше train Q99 | 0.536 | 0.055 | 0.101 | 0.053 |
| Текущий DOSTEL или GOES | 0.606 | 0.086 | 0.151 | 0.073 |
| CatBoost high-recall | **0.727** | **0.787** | **0.756** | 0.557 |

По непрерывным текущим значениям DOSTEL ROC-AUC равен 0.506, PR-AUC — 0.550;
для GOES ROC-AUC равен 0.518, PR-AUC — 0.527. При prevalence 0.515 это почти
не даёт ранжирования на горизонте 6 часов. Текущий DOSTEL хорошо подтверждает
уже начавшееся превышение, но плохо предупреждает о событии заранее. Высокий
recall сам по себе не является достаточным: правило «всегда тревога» получает
recall 1.0 и precision 0.515.

## Reproduction

```bash
.venv/bin/python analysis/space_weather_eda/download_extended_data.py \
  --start 2020-01-01 --end-exclusive 2024-07-01
.venv/bin/python analysis/space_weather_eda/build_extended_table.py
python3 analysis/catboost_timeseries/train_catboost.py \
  --output-dir analysis/catboost_timeseries/output_v2
python3 analysis/catboost_timeseries/compare_simple_baselines.py
python3 analysis/catboost_timeseries/search_catboost_recall.py \
  --dataset analysis/catboost_timeseries/output_v2/catboost_timeseries_dataset.csv.gz \
  --output-dir analysis/catboost_timeseries/output_recall_search_existing
```
