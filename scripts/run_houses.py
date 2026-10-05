"""Re-run the main comparisons for the measured WPuQ households.

    python scripts/run_houses.py                      # all houses with a complete year
    python scripts/run_houses.py --houses SFH3 SFH12  # a subset
    python scripts/run_houses.py --from-runs          # rebuild tables and figure only
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from household_flex import config
from household_flex.config import DEFAULT_CONFIG, PROJECT_ROOT
from household_flex.houses import run_houses, summarise
from household_flex.plots import houses_figure


def main_analysis_reference(reports: Path) -> dict:
    """The assumed household's results, to mark in the figure."""
    investment = pd.read_csv(reports / "investment.csv").set_index(["case", "scenario"])
    battery = pd.read_csv(reports / "battery_value.csv")
    five = battery[(battery["setup"] == "fixed feed-in") & (battery["battery_kwh"] == 5)]
    return {
        "pv_npv": float(investment.loc[("base", "S2"), "npv_eur"]),
        "best_npv": float(investment.loc[("battery_0kwh", "S5"), "npv_eur"]),
        "battery_breakeven": float(five["breakeven_eur_per_kwh"].iloc[0]),
        "battery_price": float(five["assumed_eur_per_kwh"].iloc[0]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path,
                        default=PROJECT_ROOT / "data/snapshot/berlin_2025_hourly.csv.gz")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--reports", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--houses", nargs="*")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--from-runs", action="store_true",
                        help="skip the simulations and reuse reports/houses_all_runs.csv")
    args = parser.parse_args()
    if args.from_runs:
        all_runs = pd.read_csv(args.reports / "houses_all_runs.csv", index_col="house")
        results = summarise(all_runs, config.load(args.config), args.reports)
    else:
        results = run_houses(args.snapshot, args.reports, args.config, args.workers, args.houses)
    houses_figure(results["per_house"], args.reports / "houses.png",
                  main_analysis_reference(args.reports))
    with pd.option_context("display.width", 200, "display.max_columns", 12):
        print(results["summary"].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
