from __future__ import annotations

import numpy as np
import pandas as pd
from helpers import inputs_for

from household_flex.inputs import read_snapshot
from household_flex.load_profile import berlin_holidays, household_load_kw


def test_household_profile_matches_annual_total_and_evening_peak() -> None:
    index = pd.date_range("2025-01-01", "2026-01-01", freq="1h", tz="UTC", inclusive="left")
    load = household_load_kw(index, 3500.0, "Europe/Berlin")
    assert len(load) == 8760 and not load.isna().any()
    assert abs(load.sum() - 3500.0) < 1e-6
    local = load.tz_convert("Europe/Berlin")
    by_hour = local.groupby(local.index.hour).mean()
    assert by_hour.idxmax() in (18, 19, 20)
    assert by_hour.idxmin() in (2, 3, 4)


def test_berlin_holidays_include_womens_day_and_easter_monday_2025() -> None:
    holidays = berlin_holidays(2025)
    assert pd.Timestamp("2025-03-08").date() in holidays
    assert pd.Timestamp("2025-04-21").date() in holidays
    assert len(holidays) == 10


def test_radiation_is_moved_to_start_of_hour_labels(tmp_path) -> None:
    index = pd.date_range("2025-06-01", periods=4, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {"price_eur_mwh": 1.0, "temp_c": 20.0, "ghi_wm2": [0, 100, 200, 300],
         "gti_east_wm2": [0, 100, 200, 300], "gti_west_wm2": [0, 10, 20, 30]},
        index=index,
    )
    path = tmp_path / "snap.csv"
    frame.to_csv(path)
    read = read_snapshot(path)
    # The mean over 00:00-01:00 is stamped 01:00 by Open-Meteo and must land on 00:00.
    assert read["gti_east_wm2"].iloc[0] == 100
    assert read["price_eur_mwh"].iloc[0] == 1.0


def test_inputs_hit_annual_heat_targets_on_the_full_year() -> None:
    inputs, cfg = inputs_for("2024-01-01", "2024-12-31")
    assert abs(inputs["space_heat_kw"].sum() - cfg.household.space_heat_kwh_per_year) < 1e-6
    assert abs(inputs["hot_water_kw"].sum() - cfg.household.hot_water_heat_kwh_per_year) < 1e-6
    assert (inputs["cop_space"] > inputs["cop_hot_water"]).all()
    assert np.isfinite(inputs.to_numpy(dtype=float)).all()
