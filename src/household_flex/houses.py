"""Re-run the main comparisons for measured households instead of one assumed one.

Each house from the WPuQ field study keeps the same roof, PV system, battery,
tariffs and 2025 Berlin prices and weather as the main analysis. Two things
change: household electricity is the house's measured hourly load, and heat
demand is set so that the modelled heat pump uses as much electricity as the
house's heat pump did (adjusted for the difference in heating degree-hours).
"""

from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from . import config, finance, measured
from .inputs import build_inputs, read_snapshot
from .scenarios import BY_KEY, run_scenario

BATTERY_5KWH = {"battery.capacity_kwh": 5.0, "battery.power_kw": 2.5}
NO_BATTERY = {"battery.capacity_kwh": 0.0}

# run name -> (scenario, overrides on top of the house's own settings)
MEASURED_RUNS: dict[str, tuple[str, dict[str, Any]]] = {
    "today": ("S0", {}),
    "pv": ("S2", {}),
    "pv_battery_rules": ("S3", BATTERY_5KWH),
    "best": ("S5", NO_BATTERY),
    "best_battery": ("S5", BATTERY_5KWH),
    "best_battery_known_load": ("S5", {**BATTERY_5KWH, "household.load_forecast": "perfect"}),
}
# The same house with the smooth standard profile scaled to its measured consumption.
PROFILE_RUNS: dict[str, tuple[str, dict[str, Any]]] = {
    "today_profile": ("S0", {}),
    "pv_profile": ("S2", {}),
    "pv_battery_rules_profile": ("S3", BATTERY_5KWH),
}
RESULT_FIELDS = ("annual_cost_eur", "pv_self_consumption", "self_sufficiency",
                 "heat_pump_kwh", "comfort_deficit_kwh", "solver_fallbacks")


def heat_settings(snapshot: pd.DataFrame, cfg, measured_heat_pump_kwh: float,
                  source_temp_c: pd.Series) -> dict[str, float]:
    """Space-heat demand and heat-pump size that reproduce a measured heat-pump bill.

    Hot water keeps the configured demand. The rest of the measured heat-pump
    electricity is scaled by the ratio of heating degree-hours (Berlin in the
    model year versus the measurement site and year) and converted to heat with
    the model's seasonal COP for space heating. The heat pump is sized so the
    thermostat can always hold the setpoint.
    """
    inputs = build_inputs(snapshot, cfg)
    limit = cfg.building.heating_limit_c
    hot_water_el = float((inputs["hot_water_kw"] / inputs["cop_hot_water"]).sum())
    scop_space = float(inputs["space_heat_kw"].sum()
                       / (inputs["space_heat_kw"] / inputs["cop_space"]).sum())
    climate = (measured.heating_degree_hours(snapshot["temp_c"], limit)
               / measured.heating_degree_hours(source_temp_c, limit))
    space_el = max(measured_heat_pump_kwh - hot_water_el, 0.0) * climate
    space_heat = space_el * scop_space
    loss_kw_per_k = space_heat / measured.heating_degree_hours(snapshot["temp_c"], limit)
    peak_kw = loss_kw_per_k * float((limit - snapshot["temp_c"]).max())
    peak_kw += float(inputs["hot_water_kw"].max())
    capacity = max(cfg.heat_pump.thermal_capacity_kw, math.ceil(1.15 * peak_kw))
    return {"household.space_heat_kwh_per_year": round(space_heat, 1),
            "heat_pump.thermal_capacity_kw": float(capacity)}


def _job(args: tuple[Path, Path, dict[str, Any], str]) -> dict:
    snapshot, config_path, overrides, key = args
    cfg = config.load(config_path, overrides)
    inputs = build_inputs(read_snapshot(snapshot), cfg)
    result = run_scenario(BY_KEY[key], inputs, cfg)
    out = {field: result[field] for field in RESULT_FIELDS}
    if cfg.household.measured_house:
        actual, forecast = inputs["household_kw"], inputs["household_fc_kw"]
        out["load_forecast_mae_share"] = float((actual - forecast).abs().mean() / actual.mean())
        out["load_peak_to_mean"] = float(actual.max() / actual.mean())
    return out


def plan_jobs(snapshot: pd.DataFrame, cfg, wpuq: pd.DataFrame,
              houses: list[str]) -> tuple[list[tuple[str, str, str, dict]], pd.DataFrame]:
    jobs, rows = [], []
    for house in houses:
        household_kwh = float(wpuq[f"{house}_household_w"].sum() / 1000.0)
        heat_pump_kwh = float(wpuq[f"{house}_heatpump_w"].sum() / 1000.0)
        heat = heat_settings(snapshot, cfg, heat_pump_kwh, wpuq["temp_c_open_meteo"])
        rows.append({"house": house, "household_kwh": household_kwh,
                     "measured_heat_pump_kwh": heat_pump_kwh,
                     "space_heat_kwh": heat["household.space_heat_kwh_per_year"],
                     "heat_pump_thermal_kw": heat["heat_pump.thermal_capacity_kw"]})
        own = {**heat, "household.measured_house": house}
        for run, (key, extra) in MEASURED_RUNS.items():
            jobs.append((house, run, key, {**own, **extra}))
        profile = {**heat, "household.electricity_kwh_per_year": household_kwh}
        for run, (key, extra) in PROFILE_RUNS.items():
            jobs.append((house, run, key, {**profile, **extra}))
    return jobs, pd.DataFrame(rows).set_index("house")


def summarise_house(row: pd.Series, cfg) -> dict[str, float]:
    """Savings, NPVs and battery value for one house from its run results."""
    cost = {run: row[f"{run}__annual_cost_eur"] for run in {**MEASURED_RUNS, **PROFILE_RUNS}}
    pv_saving = cost["today"] - cost["pv"]
    best_saving = cost["today"] - cost["best"]
    battery_extra = cost["best"] - cost["best_battery"]
    rules_battery_extra = cost["pv"] - cost["pv_battery_rules"]
    rules_battery_extra_profile = cost["pv_profile"] - cost["pv_battery_rules_profile"]
    return {
        "household_kwh": row["household_kwh"],
        "heat_pump_kwh": row["today__heat_pump_kwh"],
        "today_cost_eur": cost["today"],
        "pv_saving_eur": pv_saving,
        "pv_npv_eur": finance.appraise(pv_saving, cfg, True, 0.0)["npv_eur"],
        "best_saving_eur": best_saving,
        "best_npv_eur": finance.appraise(best_saving, cfg, True, 0.0)["npv_eur"],
        "battery_5kwh_extra_saving_eur": battery_extra,
        "battery_5kwh_breakeven_eur_per_kwh":
            finance.battery_breakeven_eur_per_kwh(battery_extra, cfg, 5.0),
        "known_load_extra_saving_eur":
            cost["best_battery"] - cost["best_battery_known_load"],
        "load_forecast_mae_share": row["best__load_forecast_mae_share"],
        "load_peak_to_mean": row["best__load_peak_to_mean"],
        "pv_self_consumption": row["pv__pv_self_consumption"],
        "pv_self_consumption_profile": row["pv_profile__pv_self_consumption"],
        "pv_saving_profile_eur": cost["today_profile"] - cost["pv_profile"],
        "rules_battery_extra_saving_eur": rules_battery_extra,
        "rules_battery_extra_saving_profile_eur": rules_battery_extra_profile,
    }


SUMMARY_ROWS = (  # column, label
    ("household_kwh", "Household electricity (kWh/year)"),
    ("heat_pump_kwh", "Heat-pump electricity (kWh/year)"),
    ("today_cost_eur", "Annual cost today (EUR)"),
    ("pv_saving_eur", "PV: annual saving (EUR)"),
    ("pv_npv_eur", "PV: NPV over 20 years (EUR)"),
    ("best_saving_eur", "PV + dynamic tariff + smart heat pump: annual saving (EUR)"),
    ("best_npv_eur", "PV + dynamic tariff + smart heat pump: NPV (EUR)"),
    ("battery_5kwh_extra_saving_eur", "5 kWh battery on top: extra saving (EUR/year)"),
    ("battery_5kwh_breakeven_eur_per_kwh", "5 kWh battery: break-even price (EUR/kWh)"),
    ("known_load_extra_saving_eur", "Knowing the household load in advance (EUR/year)"),
    ("load_forecast_mae_share", "Household load forecast error (MAE / mean load)"),
    ("load_peak_to_mean", "Peak hour / mean hour of household load"),
    ("pv_self_consumption", "PV self-consumption, measured load"),
    ("pv_self_consumption_profile", "PV self-consumption, standard profile"),
    ("rules_battery_extra_saving_eur", "Battery 5 kWh, simple rules: saving, measured load (EUR)"),
    ("rules_battery_extra_saving_profile_eur",
     "Battery 5 kWh, simple rules: saving, standard profile (EUR)"),
)


# Above this, the measured heat-pump electricity implies more heat than a house from
# around 2000 plausibly needs, which points to heavy use of the 6 kW backup heater.
PLAUSIBLE_SPACE_HEAT_KWH_PER_M2 = 200.0


def flag_backup_heater(per_house: pd.DataFrame) -> pd.Series:
    """Houses whose heat-pump meter probably includes much backup-heater use.

    One house has no recorded living area; it is flagged if its heat pump used
    more than 10,000 kWh, far above every house with a plausible heat demand.
    """
    per_m2 = per_house["space_heat_kwh"] / per_house["living_space_m2"]
    unknown_area = per_house["living_space_m2"].isna()
    return (per_m2 > PLAUSIBLE_SPACE_HEAT_KWH_PER_M2) | (
        unknown_area & (per_house["measured_heat_pump_kwh"] > 10_000))


def summary_table(per_house: pd.DataFrame) -> pd.DataFrame:
    """Median and spread over all houses, plus the median without flagged houses."""
    plausible = per_house[~per_house["likely_backup_heater"].astype(bool)]
    rows = []
    for column, label in SUMMARY_ROWS:
        values = per_house[column]
        rows.append({"measure": label, "median": values.median(),
                     "p10": values.quantile(0.1), "p90": values.quantile(0.9),
                     "min": values.min(), "max": values.max(),
                     "median_without_flagged": plausible[column].median()})
    shares = {
        "Houses where PV has a positive NPV": "pv_npv_eur",
        "Houses where the best setup has a positive NPV": "best_npv_eur",
    }
    for label, column in shares.items():
        rows.append({"measure": label, "median": (per_house[column] > 0).mean(),
                     "median_without_flagged": (plausible[column] > 0).mean()})
    label = "Houses where a 5 kWh battery breaks even at EUR 600/kWh"
    breakeven = "battery_5kwh_breakeven_eur_per_kwh"
    rows.append({"measure": label, "median": (per_house[breakeven] >= 600).mean(),
                 "median_without_flagged": (plausible[breakeven] >= 600).mean()})
    rows.append({"measure": "Number of houses", "median": len(per_house),
                 "median_without_flagged": len(plausible)})
    return pd.DataFrame(rows)


def run_houses(snapshot_path: Path, reports: Path, config_path: Path = config.DEFAULT_CONFIG,
               workers: int = 2, houses: list[str] | None = None) -> dict[str, pd.DataFrame]:
    cfg = config.load(config_path)
    snapshot = read_snapshot(snapshot_path)
    wpuq = measured.read_wpuq()
    houses = houses or measured.complete_houses(wpuq)
    jobs, house_info = plan_jobs(snapshot, cfg, wpuq, houses)

    with ProcessPoolExecutor(max_workers=workers) as pool:
        outputs = list(pool.map(_job, [(snapshot_path, config_path, overrides, key)
                                       for _, _, key, overrides in jobs]))

    all_runs = house_info.copy()
    for (house, run, _, _), result in zip(jobs, outputs, strict=True):
        for field, value in result.items():
            all_runs.loc[house, f"{run}__{field}"] = value
    reports.mkdir(parents=True, exist_ok=True)
    all_runs.round(4).to_csv(reports / "houses_all_runs.csv")
    return summarise(all_runs, cfg, reports)


def summarise(all_runs: pd.DataFrame, cfg, reports: Path) -> dict[str, pd.DataFrame]:
    """Per-house results and the summary table from the raw run results."""
    per_house = pd.DataFrame(
        {house: summarise_house(row, cfg) for house, row in all_runs.iterrows()}).T
    per_house.index.name = "house"
    info = all_runs[["household_kwh", "measured_heat_pump_kwh", "space_heat_kwh",
                     "heat_pump_thermal_kw"]]
    meta = pd.read_csv(measured.WPUQ_HOUSES, index_col="house")
    per_house = meta.join(info, how="right").join(per_house.drop(columns="household_kwh"))
    per_house["space_heat_kwh_per_m2"] = per_house["space_heat_kwh"] / per_house["living_space_m2"]
    per_house["likely_backup_heater"] = flag_backup_heater(per_house)
    summary = summary_table(per_house)

    per_house.round(3).to_csv(reports / "houses.csv")
    summary.round(3).to_csv(reports / "houses_summary.csv", index=False)
    return {"per_house": per_house, "all_runs": all_runs, "summary": summary}
