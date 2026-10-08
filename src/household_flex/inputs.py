"""Turn the downloaded weather and price snapshot into hourly model inputs.

Conventions: the index is UTC and marks the start of each hour; power
values are hourly means in kW, so they equal kWh per hour.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import appliances, measured
from .load_profile import household_load_kw

RADIATION_COLUMNS = (
    "ghi_wm2", "gti_east_wm2", "gti_west_wm2", "gti_east_fc_wm2", "gti_west_fc_wm2",
)
HOT_WATER_SHAPE = np.array(  # share of a day's hot-water use per local hour
    [0.5, 0.3, 0.3, 0.3, 0.5, 1.5, 4.0, 7.5, 7.5, 6.0, 4.5, 4.0,
     4.0, 3.5, 3.0, 3.0, 3.5, 4.5, 6.0, 7.0, 7.0, 6.5, 4.5, 2.1]
)


def read_snapshot(path: Path) -> pd.DataFrame:
    """Read the download script's CSV and align radiation to start-of-hour labels.

    Open-Meteo radiation is the mean over the hour *preceding* each
    timestamp, so the value stamped 11:00 belongs to the hour 10:00-11:00.
    """
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    if not frame.index.is_unique or not (frame.index.to_series().diff().dropna()
                                         == pd.Timedelta(hours=1)).all():
        raise ValueError("Snapshot must have unique, consecutive UTC hours")
    if frame.isna().any().any():
        raise ValueError("Incomplete snapshot: download missing values; do not backfill forecasts")
    for column in RADIATION_COLUMNS:
        if column in frame:
            last = frame[column].iloc[-1]
            frame[column] = frame[column].shift(-1)
            # The bundled Berlin year ends at night. Require a zero boundary;
            # arbitrary daytime files must extend to a zero night-time boundary.
            if last != 0.0:
                raise ValueError("Radiation alignment needs a trailing zero night-time sample")
            frame.loc[frame.index[-1], column] = 0.0
    return frame


def pv_kw(
    gti_east: pd.Series, gti_west: pd.Series, temp_c: pd.Series, pv: SimpleNamespace
) -> pd.Series:
    """AC output of an east-west system split evenly between both sides."""
    output = pd.Series(0.0, index=gti_east.index)
    for gti in (gti_east.clip(lower=0), gti_west.clip(lower=0)):
        cell_temp = temp_c + gti * (pv.noct_c - 20.0) / 800.0
        temp_factor = 1.0 + pv.temperature_coefficient_per_k * (cell_temp - 25.0)
        output += 0.5 * pv.peak_kw * gti / 1000.0 * temp_factor
    return (output * (1.0 - pv.system_losses)).clip(lower=0).rename("pv_kw")


def heating_loss_coefficient(temp_c: pd.Series, annual_kwh: float, heating_limit_c: float) -> float:
    """kW per K so that degree-hours below the heating limit add up to the annual demand."""
    degree_hours = (heating_limit_c - temp_c).clip(lower=0).sum()
    return annual_kwh / degree_hours


def space_heat_kw(temp_c: pd.Series, loss_kw_per_k: float, heating_limit_c: float) -> pd.Series:
    return (loss_kw_per_k * (heating_limit_c - temp_c).clip(lower=0)).rename("space_heat_kw")


def hot_water_kw(index_utc: pd.DatetimeIndex, annual_kwh: float, timezone: str) -> pd.Series:
    local_hour = index_utc.tz_convert(timezone).hour
    shape = HOT_WATER_SHAPE[np.asarray(local_hour)]
    return pd.Series(shape * annual_kwh / shape.sum(), index=index_utc, name="hot_water_kw")


def cop(sink_flow_c: np.ndarray | pd.Series, hp: SimpleNamespace) -> np.ndarray:
    """Carnot-based COP with 5 K heat-exchanger temperature differences."""
    sink_k = np.asarray(sink_flow_c, dtype=float) + 5.0 + 273.15
    source_k = hp.source_temp_c - 5.0 + 273.15
    return hp.carnot_efficiency * sink_k / (sink_k - source_k)


def space_flow_temp_c(temp_c: pd.Series, hp: SimpleNamespace, heating_limit_c: float) -> pd.Series:
    """Linear heating curve from the mild to the cold design point (-12 C)."""
    share = ((heating_limit_c - temp_c) / (heating_limit_c + 12.0)).clip(0.0, 1.0)
    return hp.flow_temp_mild_c + share * (hp.flow_temp_cold_c - hp.flow_temp_mild_c)


def build_inputs(snapshot: pd.DataFrame, cfg: SimpleNamespace) -> pd.DataFrame:
    """All hourly series the simulations need: actual values and day-ahead forecasts."""
    index = snapshot.index
    temp = snapshot["temp_c"]
    heating_limit = cfg.building.heating_limit_c
    loss = heating_loss_coefficient(temp, cfg.household.space_heat_kwh_per_year, heating_limit)

    frame = pd.DataFrame(index=index)
    frame["spot_eur_mwh"] = snapshot["price_eur_mwh"]
    frame["temp_c"] = temp
    measured_house = cfg.household.measured_house
    if measured_house:
        frame["household_kw"] = measured.household_load_kw(measured_house, index)
    else:
        frame["household_kw"] = household_load_kw(
            index, cfg.household.electricity_kwh_per_year, cfg.location.timezone
        )
    frame["pv_kw"] = pv_kw(snapshot["gti_east_wm2"], snapshot["gti_west_wm2"], temp, cfg.pv)
    frame["space_heat_kw"] = space_heat_kw(temp, loss, heating_limit)
    frame["hot_water_kw"] = hot_water_kw(
        index, cfg.household.hot_water_heat_kwh_per_year, cfg.location.timezone
    )
    frame["cop_space"] = cop(space_flow_temp_c(temp, cfg.heat_pump, heating_limit), cfg.heat_pump)
    frame["cop_hot_water"] = cop(
        np.full(len(index), cfg.heat_pump.hot_water_flow_temp_c), cfg.heat_pump
    )

    # Fixed 48 h lead forecasts, not a common day-ahead model run. Availability
    # uses a conservative 6 h publication buffer. Radiation labels move back
    # one hour, so their nominal availability is an hour later than temperature.
    has_forecast = {"temp_fc_c", "gti_east_fc_wm2", "gti_west_fc_wm2"} <= set(snapshot.columns)
    if has_forecast:
        if "forecast_lead_hours" not in snapshot:
            raise ValueError("Weather forecasts need declared lead time; legacy snapshots unsafe")
        lead = snapshot["forecast_lead_hours"]
        if not (lead >= 48).all():
            raise ValueError("Weather lead time must cover the entire published-price horizon")
        temp_fc = snapshot["temp_fc_c"]
        frame["pv_fc_kw"] = pv_kw(
            snapshot["gti_east_fc_wm2"], snapshot["gti_west_fc_wm2"], temp_fc, cfg.pv
        )
        available = index + pd.to_timedelta(7.0 - lead, unit="h")
    else:
        # Values are available after the observed hour has ended. No future
        # backfill at startup: use declared climatology/zero PV baselines.
        temp_fc = temp.shift(48).fillna(10.0)
        frame["pv_fc_kw"] = frame["pv_kw"].shift(48).fillna(0.0)
        available = index - pd.Timedelta(hours=47)
    frame["weather_fc_available_at_ns"] = [stamp.value for stamp in available]
    frame["space_heat_fc_kw"] = space_heat_kw(temp_fc, loss, heating_limit)
    frame["cop_space_fc"] = cop(
        space_flow_temp_c(temp_fc, cfg.heat_pump, heating_limit), cfg.heat_pump
    )
    # The standard load profile is itself an expectation, so it doubles as
    # the household load forecast. A measured house needs a real forecast.
    if measured_house and cfg.household.load_forecast == "recent_days":
        frame["household_fc_kw"] = measured.day_ahead_load_forecast(
            frame["household_kw"], cfg.household.electricity_kwh_per_year / 8760.0
        )
    elif measured_house and cfg.household.load_forecast != "perfect":
        raise ValueError(f"Unknown load forecast: {cfg.household.load_forecast}")
    else:
        frame["household_fc_kw"] = frame["household_kw"]
    frame["hot_water_fc_kw"] = frame["hot_water_kw"]
    appliances.apply(frame, cfg.household.appliances, cfg.location.timezone)
    frame.attrs["forecast_source"] = (
        "fixed 48h lead + 6h buffer" if has_forecast else "48h persistence")
    frame.attrs["loss_kw_per_k"] = loss
    return frame
