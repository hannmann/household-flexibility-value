# Measured households: WPuQ field study, 2019

Hourly electricity of single-family houses with heat pumps, used in
`src/household_flex/measured.py` and `houses.py`.

**Source:** Schlemminger, M., Ohrdes, T., Schneider, E. and Knoop, M. (2022). Dataset on
electrical single-family house and heat pump load profiles in Germany. *Scientific Data* 9, 56.
<https://doi.org/10.1038/s41597-022-01156-1>. Data: <https://doi.org/10.5281/zenodo.5642902>,
file `2019_data_60min.hdf5`, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**Site:** a residential district near Hameln (Lower Saxony) with houses from around 2000. Each
house has a water-to-water heat pump on a cold local heating network (similar to a
ground-source pump) with a 6 kW electric backup heater. Household and heat pump are metered
separately.

## Files

- `wpuq_2019_hourly.csv.gz`: hourly mean active power in W (`P_TOT`) of the household meter
  (`<house>_household_w`) and the heat-pump meter (`<house>_heatpump_w`) for the 33 houses
  without their own PV, indexed by the UTC start of each hour. `temp_c_open_meteo` is the 2 m
  temperature at the site from the [Open-Meteo](https://open-meteo.com) archive (CC BY 4.0),
  used only to compare heating degree-hours with Berlin.
- `houses.csv`: living area and number of inhabitants from the dataset's metadata (missing for
  SFH20).

Houses with PV are left out: their household meter shows consumption net of PV output, and the
dataset's gross consumption for them is itself an estimate.

## How the files were made

Only the `P_TOT` columns were kept and rounded to 0.1 W; nothing else was changed. The
committed files were extracted in a browser with [h5wasm](https://github.com/usnistgov/h5wasm),
reading the tables `NO_PV/<house>/HOUSEHOLD` and `NO_PV/<house>/HEATPUMP`.
`scripts/extract_wpuq.py` does the same in Python with PyTables.

## How the model uses them

- **Household electricity:** a house's measured load replaces the standard profile. The 2019
  year is moved to the model year by whole weeks, so weekdays and the daylight-saving switches
  line up (holidays may not).
- **Heat:** the heat pump keeps the model's physics. Each house's heat demand is set so the
  modelled heat pump uses as much electricity in a year as the measured one, after scaling
  for heating degree-hours (Berlin 2025 had 0.8% more than Hameln 2019). Where that implies
  more than 200 kWh of heat per m², the measured use most likely includes much backup-heater
  operation; those houses are flagged in the results.
- **Forecast:** the optimiser does not know a house's load in advance. It plans with the mean
  of the same hour over the seven days before yesterday.
- **Sample:** the 27 houses with a measurement for every hour of 2019 on both meters.
