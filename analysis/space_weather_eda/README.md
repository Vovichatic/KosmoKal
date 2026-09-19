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
