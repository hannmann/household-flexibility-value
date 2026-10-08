# What PV, a Home Battery and a Flexible Heat Pump Are Worth on a Dynamic Tariff

**Question:** For a house in Berlin with a ground-source heat pump, is it worth adding rooftop PV
and a home battery, and switching to a dynamic electricity tariff? How much of the value comes
from the hardware, and how much from controlling it well?

The model simulates one full year (2025, hourly) for eight setups, from today's house on a fixed
tariff to an optimised house with PV, battery and a price-aware heat pump. It then turns the
annual savings into net present value and payback, and checks the results against 27 households
whose consumption was measured.

## Main findings

![Annual energy cost by setup](reports/cost_bridge.png)

- **PV is clearly worth it.** An 8 kWp east-west system saves about €1,130 a year on the fixed
  tariff and pays back in about 15 years, with a net present value of about +€3,200 over 20 years.
- **The best setup is PV plus a dynamic tariff with a price-aware heat pump, without a battery.**
  It saves about €1,290 a year, with an NPV of about +€5,500 and a payback of about 12 years. This
  holds with 10% less sun (+€4,400) and under the planned feed-in reform (+€5,500).
- **A battery does not pay at today's prices.** A 5 kWh battery adds €235 a year and breaks even
  at an installed price of about €405/kWh; a 10 kWh battery adds only €287 and breaks even at
  about €255/kWh. The model assumes €600/kWh. Most of the value comes from the first few kWh,
  which cover the evening after a sunny day.
- **Smart control alone is worth little once the battery is there** (€117 a year). Without a
  battery, a price-aware heat pump on a dynamic tariff adds about €160 a year over PV alone.
- **Charging the battery from the grid is worth about nothing.** Grid fees, taxes and levies of
  about 22 ct/kWh are paid on every kWh bought, so exchange price spreads rarely cover storage
  losses and wear.
- **After the planned feed-in reform, a battery gains value.** When exports are paid at market
  prices, the battery shifts solar exports from midday (about 7 ct/kWh) to evening peaks (about
  18 ct/kWh). A 5 kWh battery then breaks even at about €480/kWh.
- **Better forecasts would add €58 a year, full exchange trading at most €166 more.** Both are
  upper bounds. Trading assumes fees on stored and re-exported power were waived.
- **Running the dishwasher, washing machine and dryer around midday is worth about €60–70 a
  year without a battery**, as much as smart heat-pump control, for the price of a start-delay
  button. With a battery it adds only €15–25, because the battery already moves solar power into
  the evening. Letting the optimiser time the appliances does no better than the simple habit.
- **The results hold for 27 households with measured consumption, and the battery looks weaker
  still.** PV pays in 26 of them and PV with a dynamic tariff in all 27. A 5 kWh battery breaks
  even at a median €276/kWh, partly because real household load is hard to forecast
  ([details](#do-the-results-hold-for-real-households)).

| Setup (8 kWp PV where present) | Annual cost | Saving vs. today | Investment | NPV (20 y) | Discounted payback |
|---|---:|---:|---:|---:|---:|
| Today: fixed tariff, no PV | €2,530 | – | – | – | – |
| PV, fixed tariff | €1,401 | €1,129 | €11,200 | +€3,239 | 15 y |
| PV + dynamic tariff + smart heat pump | €1,243 | €1,287 | €11,200 | +€5,481 | 12 y |
| … + 5 kWh battery | €1,008 | €1,522 | €14,700 | +€4,112 | 15 y |
| … + 10 kWh battery | €956 | €1,574 | €17,700 | +€628 | 20 y |
| … + 15 kWh battery | €937 | €1,593 | €20,700 | −€3,322 | never |

All results: [scenarios](reports/scenarios.csv), [every run incl. sensitivities](reports/all_runs.csv),
[investment appraisal](reports/investment.csv), [battery value](reports/battery_value.csv),
[price structure](reports/price_structure.csv), [measured households](reports/houses.csv).

## Why smart control adds so little here

Optimised control lowers the annual cost by €117 over simple rules on the same hardware. With
perfect forecasts it would be €175. Four things cap it for this house:

- **Most of the household price is fixed.** Of the average 34.2 ct/kWh on the dynamic tariff,
  21.8 ct (64%) are grid fees, taxes and levies that are the same in every hour. Only the
  exchange part moves, so the household price varies within a day by 17 ct/kWh on average in
  summer and only 10 ct/kWh in winter.
- **Simple rules already capture most of the value.** A battery run by the usual inverter rule
  (charge from solar surplus, discharge when the house needs power) saves €384 a year. Better
  timing adds only the €117 above.
- **The heat pump has little room to shift, and more room would not help.** It may pre-heat the
  house by up to 1.5 K and must never let it cool below 21 °C. Restricting it to on/off
  operation costs only €27 a year, and a three times larger hot-water tank adds nothing. The
  limit is not flexibility but the small price differences in winter, when it uses the most
  power. A 20% more efficient heat pump would save €172 a year in the optimised setup, and
  optimisation would add only €98 on top of simple rules.
- **Negative prices mostly coincide with the household's own solar surplus.** 89% of the 576
  negative-price hours in 2025 fall when the roof already produces more than the house uses, so
  the battery is filled with free solar power anyway. Because the fixed charges remain, the
  dynamic tariff still cost 22.3 ct/kWh on average in those hours.

Shifting household appliances is a cheap lever the same limits do not cap. If 600 kWh a year
(dishwasher, washing machine, dryer) are started between 11:00 and 15:00 instead of when they
usually run, PV on the fixed tariff saves €71 more a year, PV with the dynamic tariff and smart
heat pump €57 more. With a 10 kWh battery the habit adds €16, and an optimiser that picks the
hours for the appliances adds €58 without a battery and €12 with one, so it is not better than
the habit.

Control matters more where one of these limits is lifted. After the planned feed-in reform,
exports are paid at market prices and the battery can time them: the optimised setup then costs
€87 a year less than under the fixed feed-in tariff. It would also matter more with a large
flexible load such as an electric car. And a supplier running many households can use flexibility
in markets a single home cannot reach.

## Do the results hold for real households?

The main analysis uses one assumed household with a standard load profile. To test it, the same
comparison was re-run for 27 single-family houses with ground-coupled heat pumps whose household
and heat-pump electricity were metered every hour in 2019 ([WPuQ field study](data/wpuq/README.md)).
Each house keeps the roof, PV system, tariffs and 2025 Berlin prices of the main analysis. Its
household load is its measured load, and its heat demand is set so that the modelled heat pump
uses as much electricity as the real one did. The optimiser no longer knows the household load in
advance: it plans with the average of the same hour on the seven days before yesterday.

![Value per measured household](reports/houses.png)

| Per house | Median of 27 houses | 10th–90th percentile | Assumed household |
|---|---:|---:|---:|
| Household electricity | 3,058 kWh | 2,030–3,991 kWh | 3,500 kWh |
| Heat-pump electricity | 4,123 kWh | 2,110–9,650 kWh | 3,728 kWh |
| PV: NPV over 20 years | +€3,179 | +€476 to +€5,266 | +€3,239 |
| PV + dynamic tariff + smart heat pump: NPV | +€5,604 | +€2,614 to +€8,476 | +€5,481 |
| 5 kWh battery on top: extra saving | €171 a year | €127–238 | €235 |
| 5 kWh battery: break-even price | €276/kWh | €186–412/kWh | €406/kWh |

- **PV and the dynamic tariff hold up.** PV has a positive NPV in 26 of 27 houses. The exception
  is a one-person household that uses 1,150 kWh a year. PV with a dynamic tariff and a
  price-aware heat pump pays in all 27. The more electricity a house uses, the more PV saves.
- **The battery case gets weaker.** A 5 kWh battery adds a median €171 a year and would have to
  cost less than €276/kWh installed. Even the best house stays below €480/kWh. Part of the gap to
  the assumed household is that real household load is hard to predict a day ahead: in the
  median house, the forecast is off by 48% of the average hourly load. Knowing the load in
  advance would be worth €33 a year there. The rest comes mostly from lower consumption, since
  the battery earns more in houses that use more.
- **The smooth standard profile was not the problem.** Real household load is spiky: its peak
  hour is about 9 times the average hour, against 2 times in the standard profile. Yet for the
  same annual consumption, the standard profile gives almost the same PV self-consumption (a
  median 30% either way) and PV saving (a median €11 a year apart), and a battery run by simple
  rules saves about the same. At hourly resolution, how much a house uses matters far more than
  the shape of its load.
- **Four houses used much more heat-pump electricity than their size suggests** (hollow in the
  figure), most likely because the backup heater ran often. Leaving them out changes little:
  medians of +€2,878 for PV, +€5,025 for the best setup and €290/kWh for the battery.

All per-house results: [houses](reports/houses.csv), [summary](reports/houses_summary.csv),
[every run](reports/houses_all_runs.csv).

## Approach

- **Data:** 2025 German day-ahead prices from [SMARD](https://www.smard.de) (15-minute prices from
  October averaged to hours) and hourly weather for Berlin 14197 from
  [Open-Meteo](https://open-meteo.com): temperature, irradiance on east- and west-facing panels,
  and the same weather as forecast the day before. See `data/`.
- **Measured households:** hourly household and heat-pump electricity of 27 houses near Hameln
  from the [WPuQ field study](data/wpuq/README.md) (2019, CC BY 4.0), used only in the check
  against real households.
- **Household:** BDEW H25 standard load profile scaled to 3,500 kWh a year; 13,000 kWh of heat a
  year (space heating from degree-hours, hot water with a daily profile); a ground-source heat
  pump whose COP follows the flow temperature (seasonal COP 3.5).
- **Building:** a one-node thermal model. Every controller keeps the house at or above 21 °C; the
  optimiser may pre-heat up to 1.5 K above that. Savings never come from a colder house.
- **Controllers:**
  - Simple rules: thermostat control, and a battery that charges from PV surplus and covers load.
  - Optimiser: a linear programme re-solved every hour up to the last hour with a published
    price, committing only the next hour. It uses day-ahead weather forecasts (S5) or actual
    values (S6). Like a home energy manager, the battery then adapts to the actual hour: when
    the sun or the load differs from the forecast, it charges or discharges less rather than
    buying from or exporting to the grid beyond the plan.
- **Tariffs (2026):** fixed tariff at 35 ct/kWh. Dynamic tariff: spot price + 1.5 ct markup +
  VAT + 21.8 ct of fixed grid fees, taxes and levies. Feed-in at 7.70 ct/kWh, nothing at
  negative prices (Solarspitzengesetz). Smart meter €50 a year. Battery grid charging within
  the MiSpeL limit of 500 kWh per kWp.
- **Money:** investment €1,400/kWp PV, €600/kWh battery + €500 energy management. 20-year
  lifetime, battery replaced after 12 years at 60% of its price, 1% PV maintenance, 0.5% yearly
  PV degradation, 3% real discount rate, prices held at 2025 levels. Payback is discounted.

All inputs are in [config/household.yaml](config/household.yaml).

## Limitations

- **Consumption is assumed, not measured, for the main household.** Household electricity, heat
  demand, roof, tariff and investment costs are working assumptions for a typical house. Real
  bills and quotes will move the numbers. The 27 measured households show how much the results
  vary with consumption, but they come from another town and year.
- **In the main analysis, the standard load profile serves as its own forecast.** This overstates
  the battery: with measured load and a real forecast, a 5 kWh battery earns about €60 a year
  less in the median house.
- **Hourly resolution.** Peaks within the hour are averaged out, which overstates PV
  self-consumption somewhat for every household, measured or not.
- **Heat demand of the measured houses is inferred** from their heat-pump electricity at the
  model's efficiency. Where the backup heater ran often, this overstates the heat demand and the
  room for pre-heating; those four houses are flagged.
- **2025 was unusually sunny** (1,011 kWh per kWp here). The 10%-less-sun sensitivity
  approximates an average year.
- **The heat pump is assumed fully controllable.** A 2010 unit may be on/off only; the on/off
  sensitivity costs €27 a year. If it runs on a separate heat-pump meter and tariff, PV and
  battery cannot supply it without merging the meters, which this model does not cover.
- **Not modelled:** §14a grid-fee reductions for controllable heat pumps, electricity price
  trends, and any intraday or balancing revenue.

## Reproduce

```bash
python3 -m pip install -e '.[dev]'
make test
make analysis      # all scenarios and sensitivities, about 20 minutes on two cores
make houses        # the 27 measured households, about 40 minutes on two cores
```

`make data` refreshes the snapshot from SMARD and Open-Meteo (needs internet access).
