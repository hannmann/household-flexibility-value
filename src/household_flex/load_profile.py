"""Household electricity demand from the BDEW H25 standard load profile.

The H25 table (``data/h25.csv``) and the dynamisation polynomial are taken
from demandlib (oemof, MIT licence), which implements the BDEW 2025
standard load profiles. The profile is defined in German local time.

A standard profile is an average over many households, so it is smoother
than any single home. Replace it with smart-meter data when available.
"""

from __future__ import annotations

from datetime import date, timedelta
from importlib import resources

import numpy as np
import pandas as pd

MONTHS = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4, "Mai": 5, "Juni": 6, "Juli": 7,
    "August": 8, "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}


def _easter_sunday(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def berlin_holidays(year: int) -> set[date]:
    """Public holidays in Berlin: the nine national ones plus Women's Day (8 March)."""
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1), date(year, 3, 8), easter - timedelta(days=2),
        easter + timedelta(days=1), date(year, 5, 1), easter + timedelta(days=39),
        easter + timedelta(days=50), date(year, 10, 3), date(year, 12, 25),
        date(year, 12, 26),
    }


def _h25_table() -> pd.DataFrame:
    """Long table: month, day type (WT/SA/FT), quarter-hour slot -> kWh per 15 min."""
    path = resources.files("household_flex") / "data" / "h25.csv"
    with resources.as_file(path) as file:
        raw = pd.read_csv(file, header=[0, 1])
    raw = raw.drop(columns=raw.columns[0])
    rows = []
    for (month_name, day_type), values in raw.items():
        rows.append(
            pd.DataFrame(
                {
                    "month": MONTHS[month_name],
                    "day_type": day_type,
                    "slot": np.arange(96),
                    "kwh": values.to_numpy(dtype=float),
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def _dynamisation(day_of_year: np.ndarray) -> np.ndarray:
    d = day_of_year.astype(float)
    return -3.92e-10 * d**4 + 3.2e-7 * d**3 - 7.02e-5 * d**2 + 0.0021 * d + 1.24


def household_load_kw(index_utc: pd.DatetimeIndex, annual_kwh: float, timezone: str) -> pd.Series:
    """Hourly mean household demand in kW, scaled to ``annual_kwh``."""
    start = index_utc[0]
    end = index_utc[-1] + pd.Timedelta(hours=1)
    quarter = pd.date_range(start, end, freq="15min", inclusive="left")
    local = quarter.tz_convert(timezone)
    holidays = set().union(*(berlin_holidays(y) for y in set(local.year)))
    local_dates = local.date
    day_type = np.where(local.dayofweek == 5, "SA", np.where(local.dayofweek == 6, "FT", "WT"))
    is_holiday = np.array([d in holidays for d in local_dates])
    day_type = np.where(is_holiday, "FT", day_type)

    keys = pd.DataFrame(
        {"month": local.month, "day_type": day_type, "slot": local.hour * 4 + local.minute // 15}
    )
    merged = keys.merge(_h25_table(), on=["month", "day_type", "slot"], how="left")
    if merged["kwh"].isna().any():
        raise ValueError("H25 lookup failed for some quarter-hours")
    energy = merged["kwh"].to_numpy() * _dynamisation(np.asarray(local.dayofyear))
    kw_quarter = pd.Series(energy * 4.0, index=quarter)
    hourly_kw = kw_quarter.resample("1h").mean().reindex(index_utc)
    return (hourly_kw * annual_kwh / hourly_kw.sum()).rename("household_kw")
