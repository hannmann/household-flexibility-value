from __future__ import annotations

import numpy as np
import pandas as pd
from helpers import inputs_for

from household_flex.optimise import OptimisingController, horizon_ends
from household_flex.scenarios import BY_KEY, price_frame, run_scenario
from household_flex.simulate import Household

TOL = 1e-6


def _balance_error(flows: pd.DataFrame) -> float:
    supply = flows["import_kw"] + flows["pv_kw"] + flows["battery_discharge_kw"] \
        + flows["trade_buy_kw"]
    use = flows["household_kw"] + flows["hp_kw"] + flows["battery_charge_kw"] \
        + flows["export_kw"] + flows["curtail_kw"] + flows["trade_sell_kw"]
    return float((supply - use).abs().max())


def test_energy_balances_every_hour_in_every_scenario() -> None:
    inputs, cfg = inputs_for()
    for key in ("S0", "S2", "S3", "S5", "S7"):
        flows = run_scenario(BY_KEY[key], inputs, cfg)["flows"]
        assert _balance_error(flows) < TOL, key
        assert (flows.drop(columns=["building_kwh"]) >= -TOL).all().all(), key


def test_battery_and_comfort_limits_hold() -> None:
    inputs, cfg = inputs_for()
    result = run_scenario(BY_KEY["S5"], inputs, cfg)
    flows = result["flows"]
    assert flows["soc_kwh"].max() <= cfg.battery.capacity_kwh + TOL
    assert flows["battery_charge_kw"].max() <= cfg.battery.power_kw + TOL
    assert result["comfort_deficit_kwh"] < 0.5
    assert result["solver_fallbacks"] == 0


def test_no_grid_charging_when_disabled() -> None:
    inputs, cfg = inputs_for(overrides=(("battery.grid_charging", False),))
    flows = run_scenario(BY_KEY["S5"], inputs, cfg)["flows"]
    assert flows["grid_to_battery_kw"].sum() < TOL


def test_optimiser_never_saves_by_running_the_house_colder() -> None:
    inputs, cfg = inputs_for()
    rules = run_scenario(BY_KEY["S4"], inputs, cfg)["flows"]
    optimised = run_scenario(BY_KEY["S6"], inputs, cfg)["flows"]
    assert optimised["building_kwh"].min() >= -TOL
    assert optimised["building_kwh"].mean() >= rules["building_kwh"].mean() - TOL


def test_optimiser_is_not_worse_than_rules_on_the_same_hardware() -> None:
    inputs, cfg = inputs_for()
    rules = run_scenario(BY_KEY["S4"], inputs, cfg)["annual_cost_eur"]
    optimised = run_scenario(BY_KEY["S6"], inputs, cfg)["annual_cost_eur"]
    assert optimised <= rules + 1.0


def test_forecast_controller_never_sees_actuals_or_unpublished_prices() -> None:
    inputs, cfg = inputs_for()
    hh = Household.from_config(cfg, inputs.attrs["loss_kw_per_k"], True, True)
    prices = price_frame(inputs, cfg, dynamic=True)
    t = 40  # an hour in which the controller heats (not an idle plan)
    end = horizon_ends(inputs.index, cfg.location.timezone, 13)[t]
    baseline = OptimisingController(hh, cfg, inputs, prices, perfect_foresight=False)
    expected = baseline.plan(t, hh.initial_state(), inputs)

    altered = inputs.copy()
    for column in ("pv_kw", "household_kw", "space_heat_kw", "hot_water_kw", "cop_space"):
        altered[column] = altered[column] * 1.7 + 0.3      # actual values change
    altered_prices = prices.copy()
    altered_prices.iloc[end:] = altered_prices.iloc[end:] * 3.0  # unpublished prices change
    controller = OptimisingController(hh, cfg, altered, altered_prices, perfect_foresight=False)
    assert controller.plan(t, hh.initial_state(), altered) == expected
    assert baseline.failures == 0 and controller.failures == 0
    assert expected.hp_space_kw + expected.battery_charge_kw + expected.battery_discharge_kw > 0


def test_price_horizon_follows_publication_and_daylight_saving() -> None:
    index = pd.date_range("2025-03-29", "2025-04-02", freq="1h", tz="UTC", inclusive="left")
    ends = horizon_ends(index, "Europe/Berlin", 13)
    local = index.tz_convert("Europe/Berlin")

    def end_local(ts: str) -> pd.Timestamp:
        i = int(np.flatnonzero(local == pd.Timestamp(ts, tz="Europe/Berlin"))[0])
        return index[ends[i]].tz_convert("Europe/Berlin")

    assert end_local("2025-03-29 12:00") == pd.Timestamp("2025-03-30 00:00", tz="Europe/Berlin")
    assert end_local("2025-03-29 13:00") == pd.Timestamp("2025-03-31 00:00", tz="Europe/Berlin")
    # 30 March has only 23 hours; the horizon still ends at local midnight.
    assert end_local("2025-03-30 14:00") == pd.Timestamp("2025-04-01 00:00", tz="Europe/Berlin")
