"""Appliances that can run at another time of day: dishwasher, washing machine, dryer.

A fixed share of each day's household electricity is treated as shiftable. Its
daily energy stays the same; only the timing changes.

- ``none``: the appliances run when they always do, as part of the household load.
- ``timer``: the household starts them around midday (``timer_hours``), a simple
  habit that needs no forecast or price signal.
- ``optimised``: the optimiser chooses the hours within the daily window
  (``earliest_hour`` to ``latest_hour``); the energy must be used by the end of it.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

MODES = ("none", "timer", "optimised")
COLUMNS = ("app_day_kwh", "app_day_fc_kwh", "app_window", "app_last", "app_day_start",
           "app_day_id")


def shiftable_share(load: pd.Series, appliances: SimpleNamespace) -> float:
    """Share of household electricity that the shiftable appliances account for."""
    annual_kwh = float(load.sum()) * 8760.0 / len(load)
    return min(appliances.shiftable_kwh_per_year / annual_kwh, 1.0)


def _daily_energy(shiftable: pd.Series, day: np.ndarray) -> np.ndarray:
    """Each hour carries the total shiftable energy of its local day."""
    return shiftable.groupby(day).transform("sum").to_numpy()


def apply(frame: pd.DataFrame, appliances: SimpleNamespace, timezone: str) -> None:
    """Move the shiftable part of ``household_kw`` (and its forecast) in place."""
    mode = appliances.shifting
    if mode not in MODES:
        raise ValueError(f"Unknown appliance shifting mode: {mode}")
    for column in COLUMNS:
        frame[column] = 0.0
    if mode == "none" or appliances.shiftable_kwh_per_year <= 0:
        return

    local = frame.index.tz_convert(timezone)
    day = np.asarray(local.date)
    hour = np.asarray(local.hour)
    share = shiftable_share(frame["household_kw"], appliances)
    for column in ("household_kw", "household_fc_kw"):
        shiftable = frame[column] * share
        frame[column] = frame[column] - shiftable
        daily = _daily_energy(shiftable, day)
        if mode == "timer":
            timer = np.isin(hour, appliances.timer_hours)
            per_day = pd.Series(timer, index=frame.index).groupby(day).transform("sum").to_numpy()
            # Days cut off at the edge of the data without timer hours keep their timing.
            moved = np.divide(daily, per_day, out=np.zeros(len(daily)), where=per_day > 0)
            frame[column] += np.where(timer, moved, np.where(per_day > 0, 0.0, shiftable))
        else:
            frame["app_day_kwh" if column == "household_kw" else "app_day_fc_kwh"] = daily

    if mode == "optimised":
        window = (hour >= appliances.earliest_hour) & (hour < appliances.latest_hour)
        frame["app_window"] = window.astype(float)
        frame["app_last"] = (hour == appliances.latest_hour - 1).astype(float)
        frame["app_day_start"] = np.r_[True, day[1:] != day[:-1]].astype(float)
        frame["app_day_id"] = pd.factorize(day)[0].astype(float)
