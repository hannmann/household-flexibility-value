"""Measured household and heat-pump electricity from the WPuQ field study.

Source: Schlemminger, Ohrdes, Schneider and Knoop (2022), "Dataset on electrical
single-family house and heat pump load profiles in Germany", Scientific Data 9, 56,
https://doi.org/10.5281/zenodo.5642902 (CC BY 4.0). Single-family houses near Hameln
(Lower Saxony) with ground-coupled heat pumps, metered separately for the household
and the heat pump. ``data/wpuq/`` holds hourly means for 2019; see its README.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import PROJECT_ROOT

WPUQ_FILE = PROJECT_ROOT / "data" / "wpuq" / "wpuq_2019_hourly.csv.gz"
WPUQ_HOUSES = PROJECT_ROOT / "data" / "wpuq" / "houses.csv"
FORECAST_LAG_DAYS = range(2, 9)  # the seven days before yesterday


@lru_cache(maxsize=2)
def read_wpuq(path: Path = WPUQ_FILE) -> pd.DataFrame:
    """Hourly means in W, indexed by the UTC start of each hour."""
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame


def complete_houses(frame: pd.DataFrame) -> list[str]:
    """Houses with a measurement for every hour of the year on both meters."""
    houses = [c.removesuffix("_household_w") for c in frame if c.endswith("_household_w")]
    complete = [h for h in houses
                if frame[f"{h}_household_w"].notna().all()
                and frame[f"{h}_heatpump_w"].notna().all()]
    return sorted(complete, key=lambda h: int(h.removeprefix("SFH")))


def move_to_year(series: pd.Series, target_index: pd.DatetimeIndex) -> pd.Series:
    """Re-date a year of hourly values to another year, keeping weekdays and season.

    Each target hour takes the value from a whole number of weeks earlier, so a
    Monday stays a Monday. Hours that fall outside the source year wrap around by
    52 weeks. From 2019 to 2025 the shift is 313 weeks, which also lines up the
    daylight-saving switches (both on the last Sundays of March and October).
    """
    source_start = series.index[0]
    source_end = series.index[-1]
    years = target_index[0].year - source_start.year
    weeks = round((pd.Timestamp(year=source_start.year + years, month=1, day=1)
                   - pd.Timestamp(year=source_start.year, month=1, day=1)).days / 7)
    shift = pd.Timedelta(weeks=weeks)
    year = pd.Timedelta(weeks=52)
    source = target_index - shift
    source = source.where(source <= source_end, source - year)
    source = source.where(source >= source_start, source + year)
    values = series.reindex(source).to_numpy()
    if np.isnan(values).any():
        raise ValueError("Source series does not cover the target year")
    return pd.Series(values, index=target_index, name=series.name)


def day_ahead_load_forecast(load: pd.Series, fallback_kw: float) -> pd.Series:
    """Mean of the same hour over the seven days before yesterday.

    Every value used is at least 48 hours old, so the forecast is available
    whenever the optimiser plans, up to 35 hours ahead. The first two days have
    no history and use ``fallback_kw`` (the mean load known from the last bill).
    """
    lags = pd.concat([load.shift(24 * d) for d in FORECAST_LAG_DAYS], axis=1)
    return lags.mean(axis=1).fillna(fallback_kw).rename("household_fc_kw")


def household_load_kw(house: str, target_index: pd.DatetimeIndex,
                      path: Path = WPUQ_FILE) -> pd.Series:
    """One house's measured household electricity (excluding the heat pump) in kW."""
    watts = read_wpuq(path)[f"{house}_household_w"]
    return (move_to_year(watts, target_index) / 1000.0).rename("household_kw")


def annual_kwh(house: str, feed: str, path: Path = WPUQ_FILE) -> float:
    """Measured annual consumption of a house's 'household' or 'heatpump' meter."""
    return float(read_wpuq(path)[f"{house}_{feed}_w"].sum() / 1000.0)


def heating_degree_hours(temp_c: pd.Series, heating_limit_c: float) -> float:
    return float((heating_limit_c - temp_c).clip(lower=0).sum())
