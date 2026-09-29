"""The eight scenarios from the design, run on one year of inputs."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd

from . import tariffs
from .optimise import OptimisingController
from .simulate import Household, RuleController, run


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    pv: bool
    battery: bool
    dynamic: bool
    control: str            # "rules", "forecast", "perfect"
    trading: bool = False


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("S0", "Today", pv=False, battery=False, dynamic=False, control="rules"),
    Scenario("S1", "Dynamic tariff only", pv=False, battery=False, dynamic=True, control="rules"),
    Scenario("S2", "PV", pv=True, battery=False, dynamic=False, control="rules"),
    Scenario("S3", "PV + battery", pv=True, battery=True, dynamic=False, control="rules"),
    Scenario("S4", "All, simple rules", pv=True, battery=True, dynamic=True, control="rules"),
    Scenario("S5", "All, optimised on forecasts", pv=True, battery=True, dynamic=True,
             control="forecast"),
    Scenario("S6", "All, perfect foresight", pv=True, battery=True, dynamic=True,
             control="perfect"),
    Scenario("S7", "What if: exchange trading", pv=True, battery=True, dynamic=True,
             control="perfect", trading=True),
)
BY_KEY = {s.key: s for s in SCENARIOS}


def price_frame(inputs: pd.DataFrame, cfg: SimpleNamespace, dynamic: bool) -> pd.DataFrame:
    spot = inputs["spot_eur_mwh"]
    return pd.DataFrame(
        {
            "import": tariffs.import_price(spot, cfg, dynamic),
            "export": tariffs.export_price(spot, cfg),
            "spot": spot / 1000.0,
        }
    )


def run_scenario(scenario: Scenario, inputs: pd.DataFrame, cfg: SimpleNamespace) -> dict:
    hh = Household.from_config(cfg, inputs.attrs["loss_kw_per_k"], scenario.pv, scenario.battery)
    prices = price_frame(inputs, cfg, scenario.dynamic)
    if scenario.control == "rules":
        controller = RuleController(hh)
    else:
        controller = OptimisingController(
            hh, cfg, inputs, prices,
            perfect_foresight=scenario.control == "perfect",
            trading=scenario.trading,
            on_off=not cfg.heat_pump.flexible,
        )
    flows = run(inputs, hh, controller, prices["export"].to_numpy())
    # A smart meter is needed for a dynamic tariff and for PV above 7 kWp.
    smart_meter = scenario.dynamic or (scenario.pv and cfg.pv.peak_kw > 7.0)
    money = tariffs.settle(flows, prices, cfg, smart_meter)
    summary = summarise(flows, prices)
    summary["battery_cycles"] = (
        summary["battery_cycles"] / hh.capacity_kwh if hh.capacity_kwh > 0 else 0.0
    )
    return {
        "scenario": scenario.key,
        "label": scenario.label,
        **money,
        **summary,
        "solver_fallbacks": getattr(controller, "failures", 0),
        "flows": flows,
    }


def summarise(flows: pd.DataFrame, prices: pd.DataFrame) -> dict:
    demand = flows["household_kw"] + flows["hp_kw"]
    pv = flows["pv_kw"].sum()
    hp = flows["hp_kw"]
    return {
        "grid_import_kwh": float(flows["import_kw"].sum()),
        "grid_export_kwh": float(flows["export_kw"].sum()),
        "grid_charging_kwh": float(flows["grid_to_battery_kw"].sum()),
        "heat_pump_kwh": float(hp.sum()),
        "self_sufficiency": float(1.0 - flows["grid_to_house_kw"].sum() / demand.sum()),
        "pv_self_consumption": (
            float((flows["pv_self_kw"] + flows["pv_to_battery_kw"]).sum() / pv)
            if pv > 0 else float("nan")
        ),
        "heat_pump_avg_price_ct": float(100 * (hp * prices["import"]).sum() / hp.sum()),
        "battery_cycles": float(flows["battery_discharge_kw"].sum()),
        "comfort_deficit_kwh": float(flows["comfort_deficit_kwh"].sum()),
        "backup_heat_kwh": float(flows["backup_heat_kw"].sum()),
        "curtailed_kwh": float(flows["curtail_kw"].sum()),
    }
