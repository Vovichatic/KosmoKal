# Space-weather data EDA

Воспроизводимый сбор и первичный анализ данных для исторического режима
КосмоХакатона за 1 мая — 30 июня 2024 года.

```bash
python3 -m venv .venv
.venv/bin/pip install -r analysis/space_weather_eda/requirements.txt
.venv/bin/python analysis/space_weather_eda/download_data.py
MPLCONFIGDIR=.mplconfig .venv/bin/python analysis/space_weather_eda/run_eda.py
```

Основной результат: `output/EDA_REPORT.md`. Сырые и производные большие файлы
игнорируются Git; их происхождение и контрольные суммы находятся в
`data/raw/manifest.json`.

Важно: интегральные GOES-признаки в EDA являются вычисленными спектральными
прокси и не подменяют официальные пороги NOAA Space Weather Scale.

Расширенная ML-таблица 2020–2024 и экспериментальные внешние признаки:

```bash
.venv/bin/python analysis/space_weather_eda/download_extended_data.py \
  --start 2020-01-01 --end-exclusive 2024-07-01
.venv/bin/python analysis/space_weather_eda/download_external_features.py \
  --start 2023-01-01 --end-exclusive 2024-07-01
.venv/bin/python analysis/space_weather_eda/build_extended_table.py
```

Внешний блок включает NASA CDAWeb ACE и NOAA GOES-16 MPS-HI. Он сохранён как
воспроизводимая абляция, но не входит в лучшие финальные модели из-за ухудшения
метрик на мае–июне 2024. Ограничения replay описаны в
[`EXTENDED_DATA_SOURCES.md`](EXTENDED_DATA_SOURCES.md).
