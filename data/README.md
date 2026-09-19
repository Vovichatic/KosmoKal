# Локальные данные для анализа рисков ВКД

Сырые архивы скачиваются в `data/raw/` и намеренно не добавляются в Git:
они воспроизводятся командой

```bash
.venv/bin/python analysis/space_weather_eda/download_data.py
```

Расширенный архив 2020–2024 и модельная таблица воспроизводятся командами:

```bash
.venv/bin/python analysis/space_weather_eda/download_extended_data.py \
  --start 2020-01-01 --end-exclusive 2024-07-01
.venv/bin/python analysis/space_weather_eda/build_extended_table.py
python3 analysis/catboost_timeseries/train_catboost.py \
  --output-dir analysis/catboost_timeseries/output_v2
```

Экспериментальные ACE/MPS-HI признаки загружаются отдельно:

```bash
.venv/bin/python analysis/space_weather_eda/download_external_features.py \
  --start 2023-01-01 --end-exclusive 2024-07-01
.venv/bin/python analysis/space_weather_eda/build_extended_table.py
```

Сырые файлы `data/extended_raw/`, подготовленные таблицы `data/processed/` и
тяжёлые промежуточные feature-матрицы исключены из Git. В репозитории остаются
загрузчики, контрольные метрики, отчёты и сериализованные CatBoost-модели.

Для ML-прогноза сближений используется официальный ESA Collision Avoidance
Challenge dataset:

- `https://kelvins.esa.int/media/public/competitions/collision-avoidance-challenge/train_data.zip`;
- `https://kelvins.esa.int/media/public/competitions/collision-avoidance-challenge/test_data.csv`.

Файлы размещаются в `data/conjunction_raw/` и не добавляются в Git.

Ожидаемая локальная структура:

```text
data/conjunction_raw/
├── train_data.zip
├── train/
│   └── train_data.csv
└── test_data.csv
```

Проверочный период: **2024-05-01 00:00 UTC — 2024-07-01 00:00 UTC**.

Источники:

- NASA OSDR RadLab — DOSTEL 1/2 на МКС: absorbed dose rate, flux,
  latitude/longitude/altitude, B и L;
- NOAA/NCEI GOES-16 и GOES-18 SGPS L2, 5-минутные протонные данные;
- NOAA/NCEI GOES-16 MPS-HI L2, электроны 50 keV–4 MeV и протоны
  80 keV–12 MeV (экспериментальная абляция);
- NASA SPDF CDAWeb ACE SWEPAM/MFI/EPAM, солнечный ветер, IMF и частицы с
  консервативной задержкой 1 час (экспериментальная абляция);
- NASA CCMC DONKI — CME, flare, SEP, geomagnetic storm, interplanetary shock,
  high-speed stream и времена публикации;
- NOAA/NCEI SWPC — архивные 3-day Forecast, Forecast Discussion и ежедневные
  Solar and Geophysical Activity Summary;
- GFZ — Kp, Hp30, Hp60, sunspot number и F10.7;
- WDC Kyoto — provisional Dst за май и июнь 2024;
- NOAA — каталог Solar Proton Events.

Для линии сближений источник — ESA Collision Avoidance Challenge CDM. Для
будущей линии некаталогизированного MMOD рекомендуются NASA MEM/ORDEM; эти
модели не входят в текущий датасет и не заменяются значением `Pc` из CDM.

`data/raw/manifest.json` содержит URL, размер и SHA-256 каждого локального файла.
Условия использования и ограничения описаны в EDA-отчёте.

