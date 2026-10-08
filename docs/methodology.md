# Decision timing, settlement and physical assumptions

This is a counterfactual household investment study, not a record of realised trading returns.
The main house is parametrised, not calibrated to my parents' metered consumption or a supplier
quote. Prices and weather are from 2025; equipment costs and tariff assumptions are illustrative.

## Information at a decision

At the start of each UTC hour, the controller observes stored energy and re-plans until the
last local hour whose day-ahead price is published. Publication is assumed at 13:00 Berlin time.
Local calendar boundaries, including daylight-saving transitions, determine the horizon.
Only the first hour's setpoints are executed. Prices within this horizon are inputs, not forecasts.

The weather series uses Open-Meteo `previous_day2`, which means a fixed 48-hour lead for each
valid timestamp. It is **not** a single forecast run issued for the whole following day. Solar
radiation is an average over the preceding hour and is shifted back one hour before use.
The latest nominal origin of the temperature and radiation values is therefore the model hour
minus 47 hours. The controller adds a conservative six-hour dissemination buffer, giving an
assumed availability time of model hour minus 41 hours. Every planned weather value must pass
`assumed_available_at <= decision_time`; failure raises an error instead of falling back silently.

This removes the former use of 24-hour lead forecasts inside a horizon longer than 24 hours.
The availability timestamps are reconstructed from the API's documented lead-time convention,
not observed download timestamps or an archive of exact publication vintages. A production
backtest should retain individual runs with observed `issued_at`, `available_at` and `valid_time`.
See [Open-Meteo's lead-time documentation](https://open-meteo.com/en/docs/previous-runs-api).

Snapshots with missing values, duplicate hours, missing availability metadata or insufficient
forecast lead time are rejected. If weather forecasts are absent entirely, the explicit baseline
uses observations from 48 hours earlier, with a declared 10 C / zero-PV startup prior. It never
backfills startup forecasts with future observations. The bundled year has a zero-irradiance
night-time final boundary; its last radiation value is set to zero during label alignment.

The main household's H25 standard load profile and hot-water schedule are deterministic model
assumptions. For measured houses, load forecasts average the same hour at lags of two to eight
days. Startup uses the configured 3,500 kWh/year prior, not the held-out year's average load.
Heat demand and physical parameters are annual scenario calibrations, not forecasts learned
from an independent training year. The known-load run changes only household load information.

## Household bill and investment cash flows

Dynamic import price in EUR/kWh is:

```
(spot_EUR_MWh / 1000 + supplier_markup_net + non_energy_component_net) * (1 + VAT)
```

VAT is applied once. The constant net component is an illustrative BDEW-average proxy:
21.8 ct/kWh minus the 5.904675 ct/kWh VAT component reported for 2026, giving 15.895325 ct net
or 18.915437 ct gross. The gross average component cannot be added to an already VAT-inclusive
energy component. Sources: [BDEW analysis](https://www.bdew.de/service/daten-und-grafiken/bdew-strompreisanalyse/)
and its [component data](https://charts.bdew-data.de/tOB6u/26/data.csv).

This proxy is **not a verified Berlin dynamic tariff**. BDEW averages blend bill components,
including annual charges expressed per kWh. The separately configurable annual base charge is
zero in this illustration, equal across contracts. Actual offers must replace both the marginal
components and annual charges before this becomes an investment decision.

Reported `annual_cost_eur` is import payments minus export revenue and hypothetical trading
margin, plus meter and base charges. Dispatch still penalises battery discharge by 2 ct/kWh.
That imputed wear is reported separately, not deducted again from investment cash flows that
already include a battery replacement after 12 years. `dispatch_cost_including_wear_eur`
allows the dispatch objective's operating-cost convention to be inspected separately.

NPV assumes a 20-year horizon, 3% real discount rate, 1% annual PV maintenance, a replacement
battery at 60% of its initial price, and unchanged prices. Scaling all annual savings by the PV
degradation factor is a conservative simplification, not a component-by-component lifetime
simulation. No terminal hardware resale value is assumed.
The EUR 500 energy-management allowance is charged with the battery only. Price-aware heat-pump
control is assumed already available without an additional controller or subscription charge.

A constant per-kWh fee cancels when shifting the same energy between hours. It matters for
storage losses and for import-versus-export settlement; its share of the bill alone does not
explain a small optimisation gain. Seasonal spreads, solar overlap and the rule baseline must
also be considered.

## Export and hypothetical market access

In the main fixed-feed-in case, PV exports directly and battery exports are disabled. Retail
grid charging is allowed for later household consumption; no annual grid-charge limit is
inferred from MiSpeL. This is a deliberately restricted operational scenario: it does not award
feed-in remuneration to mixed-origin battery exports or implement MiSpeL settlement.

The 500 kWh/kWp quantity in MiSpeL concerns eligible export remuneration under the relevant
option, not permission to charge a battery from the grid. The study makes no claim to implement
that option. See the [Bundesnetzagentur's MiSpeL materials](https://www.bundesnetzagentur.de/1067830).

The separate market-feed-in sensitivity is hypothetical: exported solar energy earns spot
plus an assumed 1.5 ct/kWh premium. It permits solar-charged battery exports and disables grid
charging. The premium is a scenario assumption, not a promised legislative entitlement.
Direct-marketing fees, qualification, origin accounting and contract implementation are absent.

S7 is a further counterfactual: a virtual trading compartment shares the household battery's
capacity and inverter but buys and sells at wholesale spot without retail taxes/fees on these
trades. This financial settlement is not available to the modelled household. Perfect information
is also assumed. It is a sensitivity to idealised market access, not executable household income.
Intraday execution, liquidity, portfolio procurement and balancing revenue are not simulated.

## Physical execution and comparisons

Charge and discharge share one inverter: their hourly energy sum is at most its rated power
times one hour. Discharge can use only energy held at the start of the hour; charging can use
only headroom available at the start. Both trading and household compartments share storage
capacity. The LP allows within-hour time-sharing of charging and discharging, not two concurrent
devices at the full rating. Sub-hour timing, switching losses and market execution are omitted.
The simulator independently enforces the same limits and applies export caps to PV, battery
and exchange sales together. A full binary device schedule would be a stricter extension.

The heat pump's space-heating and hot-water output share one thermal capacity. Thermostat
recourse stays inside that rating. Any residual room-temperature or hot-water shortfall is
reported; no unlimited heater is invented. The setpoint is a target, not a guarantee of zero
shortfalls. `backup_heat_kwh` denotes extra electricity used by the same heat pump's thermostat
recourse; it is not an independently modelled resistance heater.

Appliance-shifting sensitivities are potential calculations: appliance energy is a divisible
share of the assumed daily profile, rather than independently observed jobs announced in advance.
The forced end-of-window completion is not a validated device power schedule. These cases should
not be interpreted as operational forecast-controller results for real washing machines.

Smart-control value compares S4 and S5 on the same tariff and hardware. Battery value compares
optimised configurations with and without a battery. S6 has perfect information within the same
rolling horizon and terminal-value heuristic: it is a benchmark, **not a proven global annual
upper bound**. Annual net import balance includes grid-charged battery energy and is labelled as
such; it does not measure the exact PV origin of household consumption.

Storage starts half full; there is no cyclic year-end inventory constraint or complete cash
valuation of the final storage state. The terminal-value share is a heuristic within each
rolling solve. Boundary inventories and that heuristic can affect small annual differences.

## Measured-household robustness

The 27 complete WPuQ households contribute 2019 household load profiles, shifted by whole
weeks to the 2025 calendar, then combined with Berlin weather and prices. Their heat-pump
metering calibrates annual heat demand at the model's efficiency; hourly measured heat-pump
operation is not replayed. The source meters include auxiliary equipment and, in some homes,
backup-heater electricity. These are individual synthetic scenario replays, not 27 observed
investment outcomes or a portfolio diversification experiment.

See the [dataset provenance](../data/wpuq/README.md). Forecast errors, battery marginal value,
comfort deficits and solver fallbacks are exported for inspection. More price/weather years,
actual tariffs and a calibration year held separate from evaluation are needed to assess
investment robustness. No result here proves the benefit of aggregating a portfolio.
