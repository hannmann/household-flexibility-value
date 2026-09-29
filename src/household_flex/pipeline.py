"""Run every scenario and sensitivity, and write the result tables and figure."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from . import config, finance
from .inputs import build_inputs, read_snapshot
from .plots import cost_bridge
from .scenarios import BY_KEY, SCENARIOS, run_scenario

REPORT_COLUMNS = (
    "scenario", "label", "annual_cost_eur", "import_cost_eur", "export_revenue_eur",
    "battery_wear_eur", "trading_margin_eur", "smart_meter_eur", "grid_import_kwh",
    "grid_export_kwh", "grid_charging_kwh", "heat_pump_kwh", "heat_pump_avg_price_ct",
    "self_sufficiency", "pv_self_consumption", "battery_cycles", "comfort_deficit_kwh",
    "backup_heat_kwh", "curtailed_kwh", "solver_fallbacks",
)

# name -> (config overrides, scenarios to run)
SENSITIVITIES: dict[str, tuple[dict[str, Any], tuple[str, ...]]] = {
    "battery_0kwh": ({"battery.capacity_kwh": 0.0}, ("S5",)),
    "battery_5kwh": ({"battery.capacity_kwh": 5.0, "battery.power_kw": 2.5}, ("S5",)),
    "battery_15kwh": ({"battery.capacity_kwh": 15.0, "battery.power_kw": 7.5}, ("S5",)),
    "no_grid_charging": ({"battery.grid_charging": False}, ("S5",)),
    "feed_in_after_reform": ({"tariffs.feed_in.regime": "market"}, ("S2", "S3", "S5")),
    "export_cap_60pct": ({"tariffs.feed_in.export_cap_share_of_peak": 0.6}, ("S5",)),
    "heat_pump_on_off": ({"heat_pump.flexible": False}, ("S5",)),
}


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
        if not scenario.pv or scenario.trading:
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

    reports.mkdir(parents=True, exist_ok=True)
    scenarios.round(3).to_csv(reports / "scenarios.csv", index=False)
    results.drop(columns=["label"]).round(3).to_csv(reports / "all_runs.csv", index=False)
    appraisal.round(2).to_csv(reports / "investment.csv", index=False)
    cost_bridge(scenarios, reports / "cost_bridge.png")
    return {"scenarios": scenarios, "all_runs": results, "investment": appraisal}
