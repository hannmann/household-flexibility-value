from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from helpers import inputs_for

from household_flex import config, houses, measured
from household_flex.inputs import read_snapshot
from household_flex.scenarios import BY_KEY, run_scenario


def _year(year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="1h", tz="UTC",
                         inclusive="left")


def test_moving_a_year_keeps_weekday_and_hour() -> None:
    source_index = _year(2019)
    code = source_index.dayofweek * 100 + source_index.hour
    series = pd.Series(code.astype(float), index=source_index)
    target_index = _year(2025)
    moved = measured.move_to_year(series, target_index)
    assert len(moved) == len(target_index) and not moved.isna().any()
    assert (moved.to_numpy() == target_index.dayofweek * 100 + target_index.hour).all()


def test_load_forecast_uses_nothing_from_the_last_48_hours() -> None:
    index = _year(2025)[: 24 * 30]
    load = pd.Series(np.random.default_rng(1).uniform(0.1, 2.0, len(index)), index=index)
    base = measured.day_ahead_load_forecast(load, 0.5)
    t = 24 * 20
    changed = load.copy()
    changed.iloc[t] += 10.0
    after = measured.day_ahead_load_forecast(changed, 0.5)
    assert np.allclose(base.iloc[: t + 48], after.iloc[: t + 48])
    assert not np.isclose(base.iloc[t + 48], after.iloc[t + 48])
    assert (base.iloc[:48] == 0.5).all()


def test_complete_houses_skips_houses_with_gaps() -> None:
    frame = pd.DataFrame({"SFH3_household_w": [1.0, 2.0], "SFH3_heatpump_w": [1.0, 1.0],
                          "SFH12_household_w": [1.0, np.nan], "SFH12_heatpump_w": [1.0, 1.0],
                          "SFH4_household_w": [1.0, 1.0], "SFH4_heatpump_w": [1.0, 1.0]})
    assert measured.complete_houses(frame) == ["SFH3", "SFH4"]


def test_measured_household_keeps_its_annual_consumption() -> None:
    house = measured.complete_houses(measured.read_wpuq())[0]
    load = measured.household_load_kw(house, _year(2025))
    assert abs(load.sum() / measured.annual_kwh(house, "household") - 1.0) < 0.01


def test_optimiser_sees_a_forecast_not_the_measured_load() -> None:
    house = measured.complete_houses(measured.read_wpuq())[0]
    inputs, _ = inputs_for(overrides=(("household.measured_house", house),))
    assert not np.allclose(inputs["household_kw"], inputs["household_fc_kw"])
    known, _ = inputs_for(overrides=(("household.measured_house", house),
                                     ("household.load_forecast", "perfect")))
    assert np.allclose(known["household_kw"], known["household_fc_kw"])


def test_heat_calibration_reproduces_the_measured_heat_pump_electricity() -> None:
    _, cfg = inputs_for()
    snapshot = read_snapshot(Path(__file__).resolve().parent / ".cache_synthetic_2024.csv")
    target_kwh = 6000.0
    heat = houses.heat_settings(snapshot, cfg, target_kwh, snapshot["temp_c"])
    tuned = config.load(overrides=heat)
    inputs, _ = inputs_for("2024-01-01", "2024-12-31", overrides=tuple(heat.items()))
    result = run_scenario(BY_KEY["S0"], inputs, tuned)
    assert abs(result["heat_pump_kwh"] / target_kwh - 1.0) < 0.03
    assert result["comfort_deficit_kwh"] == 0.0


def test_backup_heater_flag() -> None:
    frame = pd.DataFrame({"space_heat_kwh": [15000.0, 40000.0, 50000.0, 8000.0],
                          "living_space_m2": [150.0, 150.0, np.nan, np.nan],
                          "measured_heat_pump_kwh": [4500.0, 11000.0, 14000.0, 2500.0]})
    assert houses.flag_backup_heater(frame).tolist() == [False, True, True, False]
