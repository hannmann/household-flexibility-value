"""Run all scenarios and sensitivities on the downloaded snapshot.

    python scripts/run_analysis.py                       # data/snapshot/berlin_2025_hourly.csv.gz
    python scripts/run_analysis.py --snapshot path.csv.gz --quick   # base scenarios only
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from household_flex.config import DEFAULT_CONFIG, PROJECT_ROOT
from household_flex.pipeline import run_all


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path,
                        default=PROJECT_ROOT / "data/snapshot/berlin_2025_hourly.csv.gz")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--reports", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--quick", action="store_true", help="skip sensitivity runs")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not args.snapshot.exists():
        raise SystemExit(f"Missing {args.snapshot}. Run scripts/download_data.py first.")
    results = run_all(args.snapshot, args.reports, args.config, args.workers,
                      include_sensitivities=not args.quick)
    with pd.option_context("display.width", 200, "display.max_columns", 12):
        print(results["scenarios"][["scenario", "label", "annual_cost_eur",
                                    "saving_vs_today_eur"]].round(0).to_string(index=False))


if __name__ == "__main__":
    main()
