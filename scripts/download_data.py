"""Download one year of Berlin weather and German day-ahead prices.

Run from the repository root:

    python scripts/download_data.py            # year 2025, Berlin 14197
    python scripts/download_data.py --year 2024

Needs only `pandas` and `requests`. Writes
`data/snapshot/berlin_<year>_hourly.csv.gz` with one row per UTC hour:

- price_eur_mwh        DE-LU day-ahead price (SMARD); hourly mean of the
                       15-minute products where those exist
- temp_c               2 m air temperature (Open-Meteo archive, ERA5-based)
- ghi_wm2              global horizontal irradiance
- gti_east_wm2,        irradiance on east / west facing panels at the
  gti_west_wm2         configured tilt (flat-roof east-west rows)
- *_fc columns         the same weather as forecast the day before
                       (Open-Meteo previous-runs API), if available

Open-Meteo irradiance values are means over the preceding hour. All
timestamps are UTC and mark the start of the hour.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

LATITUDE = 52.475  # Berlin 14197 (Schmargendorf / Wilmersdorf)
LONGITUDE = 13.295
PANEL_TILT_DEG = 10  # typical for east-west rows on a flat roof

SMARD_BASE = "https://www.smard.de/app/chart_data"
SMARD_PRICE_FILTER = 4169  # day-ahead price, EUR/MWh
SMARD_REGION = "DE-LU"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

ROOT = Path(__file__).resolve().parents[1]


def _get_json(url: str, params: dict | None = None, attempts: int = 4) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=60)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(1.0 * (2**attempt))
    raise RuntimeError(f"Download failed: {url} ({last_error})")


def _smard_series(resolution: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """One SMARD price series ('hour' or 'quarterhour') between start and end (UTC)."""
    stem = f"{SMARD_BASE}/{SMARD_PRICE_FILTER}/{SMARD_REGION}"
    try:
        index = _get_json(f"{stem}/index_{resolution}.json")
    except RuntimeError:
        return pd.Series(dtype=float)
    lower_ms = (start - pd.Timedelta(days=8)).value // 10**6
    upper_ms = end.value // 10**6
    chunks = [t for t in index.get("timestamps", []) if lower_ms <= t < upper_ms]
    values: dict[int, float] = {}
    for timestamp in chunks:
        url = f"{stem}/{SMARD_PRICE_FILTER}_{SMARD_REGION}_{resolution}_{timestamp}.json"
        for ms, value in _get_json(url).get("series", []):
            if value is not None:
                values[int(ms)] = float(value)
    series = pd.Series(values, dtype=float).sort_index()
    series.index = pd.to_datetime(series.index, unit="ms", utc=True)
    return series[(series.index >= start) & (series.index < end)]


def download_prices(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Hourly day-ahead prices; 15-minute products are averaged to the hour."""
    hourly = _smard_series("hour", start, end)
    quarter = _smard_series("quarterhour", start, end)
    if not quarter.empty:
        quarter_hourly = quarter.resample("1h").mean()
        hourly = quarter_hourly.combine_first(hourly)
    if hourly.empty:
        raise RuntimeError("No SMARD prices downloaded")
    return hourly.rename("price_eur_mwh")


def _open_meteo(url: str, variables: list[str], start: str, end: str, **extra) -> pd.DataFrame:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": start,
        "end_date": end,
        "hourly": ",".join(variables),
        "timezone": "UTC",
        **extra,
    }
    payload = _get_json(url, params)
    frame = pd.DataFrame(payload["hourly"])
    frame.index = pd.to_datetime(frame.pop("time"), utc=True)
    return frame


def download_weather(year: int) -> pd.DataFrame:
    start, end = f"{year}-01-01", f"{year}-12-31"
    base = _open_meteo(
        ARCHIVE_URL, ["temperature_2m", "shortwave_radiation"], start, end
    ).rename(columns={"temperature_2m": "temp_c", "shortwave_radiation": "ghi_wm2"})
    # Open-Meteo azimuth convention: 0 = south, -90 = east, 90 = west.
    east = _open_meteo(
        ARCHIVE_URL, ["global_tilted_irradiance"], start, end,
        tilt=PANEL_TILT_DEG, azimuth=-90,
    ).rename(columns={"global_tilted_irradiance": "gti_east_wm2"})
    west = _open_meteo(
        ARCHIVE_URL, ["global_tilted_irradiance"], start, end,
        tilt=PANEL_TILT_DEG, azimuth=90,
    ).rename(columns={"global_tilted_irradiance": "gti_west_wm2"})
    return base.join([east, west])


def download_forecasts(year: int) -> pd.DataFrame | None:
    """Weather as forecast one day earlier. Optional: returns None on failure."""
    start, end = f"{year}-01-01", f"{year}-12-31"
    try:
        base = _open_meteo(
            PREVIOUS_RUNS_URL, ["temperature_2m_previous_day1"], start, end
        ).rename(columns={"temperature_2m_previous_day1": "temp_fc_c"})
        east = _open_meteo(
            PREVIOUS_RUNS_URL, ["global_tilted_irradiance_previous_day1"], start, end,
            tilt=PANEL_TILT_DEG, azimuth=-90,
        ).rename(columns={"global_tilted_irradiance_previous_day1": "gti_east_fc_wm2"})
        west = _open_meteo(
            PREVIOUS_RUNS_URL, ["global_tilted_irradiance_previous_day1"], start, end,
            tilt=PANEL_TILT_DEG, azimuth=90,
        ).rename(columns={"global_tilted_irradiance_previous_day1": "gti_west_fc_wm2"})
    except (RuntimeError, KeyError) as exc:
        print(f"Day-ahead weather forecasts unavailable, continuing without: {exc}")
        return None
    return base.join([east, west])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()
    start = pd.Timestamp(f"{args.year}-01-01", tz="UTC")
    end = pd.Timestamp(f"{args.year + 1}-01-01", tz="UTC")

    print(f"Downloading day-ahead prices for {args.year} from SMARD ...")
    prices = download_prices(start, end)
    print(f"Downloading Berlin weather for {args.year} from Open-Meteo ...")
    weather = download_weather(args.year)
    forecasts = download_forecasts(args.year)

    index = pd.date_range(start, end, freq="1h", inclusive="left")
    frame = pd.DataFrame(index=index).join(prices).join(weather)
    if forecasts is not None:
        frame = frame.join(forecasts)
    frame.index.name = "timestamp_utc"

    missing = frame[["price_eur_mwh", "temp_c", "gti_east_wm2", "gti_west_wm2"]].isna().sum()
    print("Missing values per column:\n" + missing.to_string())
    if missing.sum() > 48:
        sys.exit("Too many gaps; check the downloads before using this file.")

    out = ROOT / "data" / "snapshot" / f"berlin_{args.year}_hourly.csv.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.round(3).to_csv(out)
    print(f"Wrote {len(frame)} rows to {out}")


if __name__ == "__main__":
    main()
