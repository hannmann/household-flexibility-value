"""Run every scenario and sensitivity, and write the result tables and figure."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from . import config, finance
from .inputs import build_inputs, read_snapshot
from .plots import cost_bridge
from .scenarios import BY_KEY, SCENARIOS, price_frame, run_scenario

REPORT_COLUMNS = (
    "scenario", "label", "annual_cost_eur", "import_cost_eur", "export_revenue_eur",
    "battery_wear_eur", "dispatch_cost_including_wear_eur", "trading_margin_eur",
    "smart_meter_eur", "annual_base_eur", "grid_import_kwh",
    "grid_export_kwh", "grid_charging_kwh", "heat_pump_kwh", "heat_pump_avg_price_ct",
    "self_sufficiency", "pv_self_consumption", "battery_cycles", "comfort_deficit_kwh",
    "backup_heat_kwh", "hot_water_deficit_kwh", "comfort_shortfall_hours",
    "max_battery_throughput_kw", "curtailed_kwh", "solver_fallbacks",
)

# name -> (config overrides, scenarios to run)
SENSITIVITIES: dict[str, tuple[dict[str, Any], tuple[str, ...]]] = {
    "battery_0kwh": ({"battery.capacity_kwh": 0.0}, ("S5",)),
    "battery_5kwh": ({"battery.capacity_kwh": 5.0, "battery.power_kw": 2.5}, ("S5",)),
    "battery_15kwh": ({"battery.capacity_kwh": 15.0, "battery.power_kw": 7.5}, ("S5",)),
    "no_grid_charging": ({"battery.grid_charging": False}, ("S5",)),
    "hypothetical_market_feed_in": (
        {"tariffs.feed_in.regime": "market", "battery.export": True,
         "battery.grid_charging": False}, ("S2", "S3", "S5")),
    "export_cap_60pct": ({"tariffs.feed_in.export_cap_share_of_peak": 0.6}, ("S5",)),
    # 2025 was unusually sunny; 10% less PV output approximates an average year.
    "pv_yield_minus_10pct": ({"pv.system_losses": 1.0 - 0.86 * 0.9}, ("S2", "S3", "S5")),
    "battery_0kwh_pv_minus_10pct": (
        {"battery.capacity_kwh": 0.0, "pv.system_losses": 1.0 - 0.86 * 0.9}, ("S5",)),
    "battery_0kwh_market_feed_in": (
        {"battery.capacity_kwh": 0.0, "tariffs.feed_in.regime": "market",
         "battery.export": True, "battery.grid_charging": False}, ("S5",)),
    "battery_5kwh_market_feed_in": (
        {"battery.capacity_kwh": 5.0, "battery.power_kw": 2.5,
         "tariffs.feed_in.regime": "market", "battery.export": True,
         "battery.grid_charging": False}, ("S5",)),
    "heat_pump_on_off": ({"heat_pump.flexible": False}, ("S5",)),
    # Dishwasher, washing machine and dryer: started around midday, or timed by the optimiser.
    "appliances_timer": ({"household.appliances.shifting": "timer"}, ("S2", "S3", "S5")),
    "appliances_optimised": ({"household.appliances.shifting": "optimised"}, ("S5",)),
    "battery_0kwh_appliances_timer": (
        {"battery.capacity_kwh": 0.0, "household.appliances.shifting": "timer"}, ("S5",)),
    "battery_0kwh_appliances_optimised": (
        {"battery.capacity_kwh": 0.0, "household.appliances.shifting": "optimised"}, ("S5",)),
    # A modern heat pump on the same borehole: about 20% more efficient.
    "heat_pump_modern": ({"heat_pump.carnot_efficiency": 0.6}, ("S0", "S4", "S5")),
    "heat_pump_modern_big_tank": (
        {"heat_pump.carnot_efficiency": 0.6, "hot_water_tank.capacity_kwh_th": 12.0}, ("S5",)),
}
# Cases that change the existing heat pump, which the hardware appraisal does not price.
NOT_APPRAISED = ("heat_pump_modern", "heat_pump_modern_big_tank")


def _job(args: tuple[Path, Path, dict[str, Any], str]) -> dict:
    snapshot, config_path, overrides, key = args
    cfg = config.load(config_path, overrides)
    inputs = build_inputs(read_snapshot(snapshot), cfg)
    result = run_scenario(BY_KEY[key], inputs, cfg)
    result.pop("flows")
    result["forecast_source"] = inputs.attrs["forecast_source"]
    return result


def _battery_kwh(cfg, overrides: dict[str, Any], scenario_key: str) -> float:
    if not BY_KEY[scenario_key].battery:
        return 0.0
    return float(overrides.get("battery.capacity_kwh", cfg.battery.capacity_kwh))


def run_all(snapshot: Path, reports: Path, config_path: Path = config.DEFAULT_CONFIG,
            workers: int = 2, include_sensitivities: bool = True) -> dict[str, pd.DataFrame]:
    cfg = config.load(config_path)
    jobs: list[tuple[str, dict[str, Any], str]] = [("base", {}, s.key) for s in SCENARIOS]
    if include_sensitivities:
        for name, (overrides, keys) in SENSITIVITIES.items():
            jobs += [(name, overrides, key) for key in keys]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        outputs = list(pool.map(_job, [(snapshot, config_path, o, k) for _, o, k in jobs]))

    rows = []
    for (case, overrides, key), result in zip(jobs, outputs, strict=True):
        rows.append({"case": case, **result, "battery_kwh": _battery_kwh(cfg, overrides, key)})
    results = pd.DataFrame(rows)
    base = results[results["case"] == "base"].set_index("scenario")
    today = float(base.loc["S0", "annual_cost_eur"])

    scenarios = base.reset_index()[list(REPORT_COLUMNS)].copy()
    scenarios["saving_vs_today_eur"] = today - scenarios["annual_cost_eur"]

    appraisal_rows = []
    for _, row in results.iterrows():
        scenario = BY_KEY[row["scenario"]]
        if not scenario.pv or scenario.trading or row["case"] in NOT_APPRAISED:
            continue
        appraisal_rows.append(
            {
                "case": row["case"],
                "scenario": row["scenario"],
                "label": row["label"],
                "battery_kwh": row["battery_kwh"],
                "annual_cost_eur": row["annual_cost_eur"],
                **finance.appraise(today - row["annual_cost_eur"], cfg, True, row["battery_kwh"]),
            }
        )
    appraisal = pd.DataFrame(appraisal_rows)
    battery_value = _battery_value(results, cfg)

    reports.mkdir(parents=True, exist_ok=True)
    battery_value.round(1).to_csv(reports / "battery_value.csv", index=False)
    price_structure(snapshot, cfg).to_csv(reports / "price_structure.csv", index=False)
    scenarios.round(3).to_csv(reports / "scenarios.csv", index=False)
    results.drop(columns=["label"]).round(3).to_csv(reports / "all_runs.csv", index=False)
    appraisal.round(2).to_csv(reports / "investment.csv", index=False)
    cost_bridge(scenarios, reports / "cost_bridge.png")
    return {"scenarios": scenarios, "all_runs": results, "investment": appraisal,
            "battery_value": battery_value}


# Optimised (S5) runs that differ only in battery size, grouped by the rest of the setup.
BATTERY_FAMILIES: dict[str, dict[int, str]] = {
    "fixed feed-in": {0: "battery_0kwh", 5: "battery_5kwh", 10: "base", 15: "battery_15kwh"},
    "hypothetical market feed-in": {
        0: "battery_0kwh_market_feed_in", 5: "battery_5kwh_market_feed_in",
        10: "hypothetical_market_feed_in"},
    "10% less sun": {0: "battery_0kwh_pv_minus_10pct", 10: "pv_yield_minus_10pct"},
}


def _battery_value(results: pd.DataFrame, cfg) -> pd.DataFrame:
    """What a battery adds on top of PV with optimised control, and what it may cost."""
    s5 = results[results["scenario"] == "S5"].set_index("case")["annual_cost_eur"]
    rows = []
    for family, cases in BATTERY_FAMILIES.items():
        if not set(cases.values()) <= set(s5.index):
            continue
        without = float(s5[cases[0]])
        for kwh, case in cases.items():
            if kwh == 0:
                continue
            extra = without - float(s5[case])
            rows.append({
                "setup": family,
                "battery_kwh": kwh,
                "extra_saving_eur_per_year": extra,
                "breakeven_eur_per_kwh": finance.battery_breakeven_eur_per_kwh(extra, cfg, kwh),
                "assumed_eur_per_kwh": cfg.investment.battery_eur_per_kwh,
            })
    return pd.DataFrame(rows)


def price_structure(snapshot: Path, cfg) -> pd.DataFrame:
    """Price spreads and solar overlap; fixed components do not cancel spreads."""
    inputs = build_inputs(read_snapshot(snapshot), cfg)
    retail_ct = price_frame(inputs, cfg, dynamic=True)["import"] * 100.0
    local = inputs.index.tz_convert(cfg.location.timezone)
    daily = pd.DataFrame({"ct": retail_ct.to_numpy(), "date": local.date, "month": local.month})
    daily = daily.groupby("date").agg(spread=("ct", lambda s: s.max() - s.min()),
                                      month=("month", "first"))
    winter = daily["month"].isin((11, 12, 1, 2))
    summer = daily["month"].isin((5, 6, 7, 8))
    negative = inputs["spot_eur_mwh"] < 0.0
    heat_pump_kw = (inputs["space_heat_kw"] / inputs["cop_space"]
                    + inputs["hot_water_kw"] / inputs["cop_hot_water"])
    surplus = inputs["pv_kw"] - inputs["household_kw"] - heat_pump_kw
    facts = {
        "mean_dynamic_price_ct_per_kwh": retail_ct.mean(),
        "non_energy_gross_ct_per_kwh": (
            cfg.tariffs.dynamic.non_energy_net_ct_per_kwh * (1 + cfg.tariffs.dynamic.vat)),
        "daily_price_spread_winter_ct": daily.loc[winter, "spread"].mean(),
        "daily_price_spread_summer_ct": daily.loc[summer, "spread"].mean(),
        "negative_price_hours": int(negative.sum()),
        "mean_dynamic_price_in_negative_hours_ct": retail_ct[negative].mean(),
        "share_of_negative_hours_with_own_pv_surplus": float((surplus[negative] > 0).mean()),
    }
    return pd.DataFrame({"fact": list(facts),
                         "value": [round(float(v), 3) for v in facts.values()]})
