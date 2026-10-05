"""Extract hourly household and heat-pump electricity from the WPuQ HDF5 file.

    python scripts/extract_wpuq.py path/to/2019_data_60min.hdf5

Download ``2019_data_60min.hdf5`` (111 MB) from https://doi.org/10.5281/zenodo.5642902.
Reading it needs PyTables (``pip install tables``). The script writes
``data/wpuq/wpuq_2019_hourly.csv.gz`` and ``data/wpuq/houses.csv``: the total active
power (``P_TOT``, W) of the household and heat-pump meters of every house without
PV, plus hourly 2 m temperature at the site from the Open-Meteo archive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import requests

from household_flex.config import PROJECT_ROOT

OUT = PROJECT_ROOT / "data" / "wpuq"
OPEN_METEO = ("https://archive-api.open-meteo.com/v1/archive?latitude=52.05&longitude=9.39"
              "&start_date=2019-01-01&end_date=2019-12-31&hourly=temperature_2m&timezone=UTC")


def site_temperature() -> pd.Series:
    hourly = requests.get(OPEN_METEO, timeout=60).json()["hourly"]
    index = pd.to_datetime(hourly["time"], utc=True)
    return pd.Series(hourly["temperature_2m"], index=index, name="temp_c_open_meteo")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hdf5", type=Path)
    args = parser.parse_args()

    columns, houses = {}, []
    with pd.HDFStore(args.hdf5, mode="r") as store:
        names = sorted({key.split("/")[2] for key in store.keys() if key.startswith("/NO_PV/")},
                       key=lambda h: int(h.removeprefix("SFH")))
        for house in names:
            for feed in ("HOUSEHOLD", "HEATPUMP"):
                frame = store.select(f"NO_PV/{house}/{feed}")
                frame.index = pd.to_datetime(frame.index, unit="s", utc=True)
                columns[f"{house}_{feed.lower()}_w"] = frame["P_TOT"]
            attrs = store.get_storer(f"NO_PV/{house}/HOUSEHOLD").attrs
            houses.append({"house": house,
                           "living_space_m2": getattr(attrs, "living_space", None),
                           "inhabitants": getattr(attrs, "n_inhabitants", None)})

    hourly = pd.concat([site_temperature(), pd.DataFrame(columns)], axis=1).round(1)
    hourly.index.name = "time_utc"
    OUT.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(OUT / "wpuq_2019_hourly.csv.gz")
    pd.DataFrame(houses).to_csv(OUT / "houses.csv", index=False)
    print(f"{len(names)} houses, {len(hourly)} hours -> {OUT}")


if __name__ == "__main__":
    main()
