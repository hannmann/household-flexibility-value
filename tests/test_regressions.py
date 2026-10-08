"""Regression cases for information timing, physical feasibility and cash accounting."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from helpers import inputs_for

from household_flex import config, tariffs
from household_flex.inputs import build_inputs, read_snapshot
from household_flex.optimise import OptimisingController, horizon_ends
from household_flex.scenarios import BY_KEY, price_frame, run_scenario
from household_flex.simulate import Household, Setpoints, realise


def test_forecast_availability_covers_the_longest_price_horizon_and_dst() -> None:
    inputs, cfg = inputs_for("2024-01-01", "2024-12-31")
    ends = horizon_ends(inputs.index, cfg.location.timezone, 13)
    assert max(ends - np.arange(len(inputs))) > 24
    for t, end in enumerate(ends):
        assert (inputs["weather_fc_available_at_ns"].iloc[t:end]
                <= inputs.index[t].value).all()


def test_forecast_from_after_a_decision_is_rejected_not_silently_used() -> None:
    inputs, cfg = inputs_for()
    altered = inputs.copy()
    t = 40
    end = horizon_ends(inputs.index, cfg.location.timezone, 13)[t]
    altered.iloc[end - 1, altered.columns.get_loc("weather_fc_available_at_ns")] = (
        inputs.index[t].value + pd.Timedelta(hours=10).value)
    hh = Household.from_config(cfg, inputs.attrs["loss_kw_per_k"], True, True)
    with pytest.raises(ValueError, match="unavailable"):
        OptimisingController(hh, cfg, altered, price_frame(inputs, cfg, True),
                             perfect_foresight=False)


def test_legacy_forecast_snapshot_cannot_be_mistaken_for_causal_weather() -> None:
    path = Path(__file__).parent / ".cache_synthetic_2024.csv"
    snapshot = read_snapshot(path)
    with pytest.raises(ValueError, match="lead time"):
        build_inputs(snapshot.drop(columns="forecast_lead_hours"), config.load())
    snapshot["forecast_lead_hours"] = 24
    with pytest.raises(ValueError, match="entire published-price horizon"):
        build_inputs(snapshot, config.load())


def test_incomplete_snapshot_is_rejected_instead_of_future_backfill(tmp_path) -> None:
    inputs_for()
    path = Path(__file__).parent / ".cache_synthetic_2024.csv"
    frame = pd.read_csv(path, index_col=0)
    frame.iloc[30, frame.columns.get_loc("temp_fc_c")] = np.nan
    broken = tmp_path / "broken.csv"
    frame.to_csv(broken)
    with pytest.raises(ValueError, match="Incomplete"):
        read_snapshot(broken)


def test_single_inverter_and_storage_balance_even_at_extreme_prices() -> None:
    inputs, cfg = inputs_for()
    shocked = inputs.copy()
    shocked["spot_eur_mwh"] = np.resize([-500.0, 1000.0, 20.0], len(inputs))
    for key in ("S5", "S7"):
        result = run_scenario(BY_KEY[key], shocked, cfg)
        flows = result["flows"]
        throughput = flows["battery_charge_kw"] + flows["battery_discharge_kw"]
        assert throughput.max() <= cfg.battery.power_kw + 1e-6
        expected = (0.5 * cfg.battery.capacity_kwh
                    + (np.sqrt(cfg.battery.round_trip_efficiency) * flows["battery_charge_kw"]
                       - flows["battery_discharge_kw"]
                       / np.sqrt(cfg.battery.round_trip_efficiency)).cumsum())
        np.testing.assert_allclose(flows["soc_kwh"], expected, atol=1e-6)
        assert result["solver_fallbacks"] == 0


def test_export_limit_covers_battery_and_exchange_sales() -> None:
    inputs, _ = inputs_for()
    cfg = config.load(overrides={"battery.export": True, "battery.grid_charging": False,
                                "tariffs.feed_in.regime": "market",
                                "tariffs.feed_in.export_cap_share_of_peak": 0.0125})
    hh = Household.from_config(cfg, inputs.attrs["loss_kw_per_k"], True, True)
    state = hh.initial_state()
    state.trade_soc_kwh = 1.0
    actual = {"cop_space": 4.0, "cop_hot_water": 3.0, "hot_water_kw": 0.0,
              "space_heat_kw": 0.0, "household_kw": 0.0, "pv_kw": 2.0}
    flows = realise(Setpoints(battery_discharge_kw=4.0, trade_sell_kw=1.0),
                    state, hh, actual, 0.077)
    assert flows["export_kw"] + flows["trade_sell_kw"] <= 0.1 + 1e-6
    expected = 6.0 - flows["battery_discharge_kw"] / hh.eta
    assert abs(flows["soc_kwh"] - expected) < 1e-6


def test_hot_water_recourse_cannot_exceed_heat_pump_capacity() -> None:
    inputs, cfg = inputs_for()
    hh = Household.from_config(cfg, inputs.attrs["loss_kw_per_k"], False, False)
    state = hh.initial_state()
    state.tank_kwh = 0.0
    actual = {"cop_space": 3.0, "cop_hot_water": 3.0, "hot_water_kw": 21.0,
              "space_heat_kw": 0.0, "household_kw": 0.0, "pv_kw": 0.0}
    flows = realise(Setpoints(), state, hh, actual, 0.077)
    assert flows["hp_kw"] * 3.0 <= 7.0 + 1e-6
    assert flows["hot_water_deficit_kwh"] == pytest.approx(14.0)


def test_fixed_feed_in_never_pays_for_grid_charged_battery_exports() -> None:
    inputs, cfg = inputs_for()
    hh = Household.from_config(cfg, inputs.attrs["loss_kw_per_k"], True, True)
    assert np.isinf(hh.grid_charging_budget_kwh)  # not the MiSpeL export allowance
    actual = {"cop_space": 3.0, "cop_hot_water": 3.0, "hot_water_kw": 0.0,
              "space_heat_kw": 0.0, "household_kw": 0.0, "pv_kw": 0.0}
    flows = realise(Setpoints(battery_discharge_kw=3.0), hh.initial_state(), hh, actual, 0.077)
    assert flows["battery_export_kw"] == 0.0
    assert flows["battery_discharge_kw"] == 0.0


def test_vat_once_and_constant_component_cancels_when_shifting_one_kwh() -> None:
    cfg = config.load()
    spot = pd.Series([0.0, 100.0])
    prices = tariffs.import_price(spot, cfg, True)
    assert prices.iloc[0] == pytest.approx((0.015 + 0.15895325) * 1.19)
    assert prices.iloc[1] - prices.iloc[0] == pytest.approx(0.1 * 1.19)


def test_non_cash_wear_is_reported_but_not_charged_again_in_the_bill() -> None:
    inputs, cfg = inputs_for()
    result = run_scenario(BY_KEY["S3"], inputs, cfg)
    bill = (result["import_cost_eur"] - result["export_revenue_eur"]
            + result["smart_meter_eur"] + result["annual_base_eur"])
    assert result["annual_cost_eur"] == pytest.approx(bill)
    assert result["battery_wear_eur"] > 0
    assert result["dispatch_cost_including_wear_eur"] == pytest.approx(
        bill + result["battery_wear_eur"])
