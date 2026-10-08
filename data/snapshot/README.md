# Berlin 2025 snapshot

`berlin_2025_hourly.csv.gz` contains 8,760 consecutive UTC hours. Prices and actual weather
are unchanged from the original study. Weather forecasts were refreshed on 8 October 2026
using Open-Meteo's `previous_day2` fields; `forecast_lead_hours = 48` records that convention.

- Prices: [SMARD](https://www.smard.de), DE-LU day-ahead, hourly means of quarter-hour products
  where available. This is an hourly model, not a quarter-hour execution backtest.
- Actual weather: [Open-Meteo archive](https://open-meteo.com/en/docs/historical-weather-api),
  latitude 52.475, longitude 13.295, ERA5-based temperature and east/west tilted radiation.
- Forecast weather: [Open-Meteo Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api),
  fixed 48-hour lead temperature and east/west tilted radiation, 10-degree tilt.

Radiation is stored with Open-Meteo's preceding-hour labels and shifted back one hour on read.
Forecast availability includes that shift and an assumed six-hour dissemination buffer. No
observed publication timestamps are available in this extract. See [methodology](../../docs/methodology.md).
Missing values are rejected rather than interpolated from future data.

Open-Meteo weather data is provided under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Refresh using `make data`; refreshes may differ as source archives are updated. The committed
snapshot fixes the data used in the published results.
