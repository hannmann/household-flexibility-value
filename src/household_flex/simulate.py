"""Hour-by-hour simulation shared by all controllers.

Every hour a controller proposes setpoints (heat pump power, battery
charge and discharge, optional exchange trades). ``realise`` then applies
them to what actually happened that hour, with the same physics and
accounting for every controller, so scenario differences come only from
the decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pandas as pd


@dataclass
class Setpoints:
    hp_space_kw: float = 0.0
    hp_hot_water_kw: float = 0.0
    battery_charge_kw: float = 0.0      # total, including exchange purchases
    battery_discharge_kw: float = 0.0   # total, including exchange sales
    trade_buy_kw: float = 0.0
    trade_sell_kw: float = 0.0
    self_consumption_battery: bool = False  # battery follows the measured surplus


@dataclass
class State:
    soc_kwh: float
    building_kwh: float     # heat stored in the building relative to the setpoint
    tank_kwh: float
    grid_charged_kwh: float = 0.0
    trade_soc_kwh: float = 0.0  # energy bought on the exchange, reserved for resale (S7)


@dataclass
class Household:
    """Static parameters derived from the configuration."""

    has_pv: bool
    has_battery: bool
    capacity_kwh: float
    power_kw: float
    eta: float                      # one-way battery efficiency
    grid_charging_budget_kwh: float
    building_capacity_kwh_per_k: float
    building_decay: float           # per-hour retention of stored building heat
    building_band_kwh: float
    tank_capacity_kwh: float
    tank_retention: float
    hp_thermal_kw: float
    export_cap_kw: float | None
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: SimpleNamespace, loss_kw_per_k: float, has_pv: bool,
                    has_battery: bool) -> Household:
        tau = cfg.building.time_constant_h
        capacity_per_k = loss_kw_per_k * tau
        battery = cfg.battery
        budget = 0.0
        if has_battery and battery.grid_charging and has_pv:
            budget = battery.grid_charging_kwh_per_kwp_year * cfg.pv.peak_kw
        cap_share = cfg.tariffs.feed_in.export_cap_share_of_peak
        return cls(
            has_pv=has_pv,
            has_battery=has_battery,
            capacity_kwh=battery.capacity_kwh if has_battery else 0.0,
            power_kw=battery.power_kw if has_battery else 0.0,
            eta=float(np.sqrt(battery.round_trip_efficiency)),
            grid_charging_budget_kwh=budget,
            building_capacity_kwh_per_k=capacity_per_k,
            building_decay=float(np.exp(-1.0 / tau)),
            building_band_kwh=capacity_per_k * cfg.building.comfort_band_k,
            tank_capacity_kwh=cfg.hot_water_tank.capacity_kwh_th,
            tank_retention=1.0 - cfg.hot_water_tank.loss_per_hour,
            hp_thermal_kw=cfg.heat_pump.thermal_capacity_kw,
            export_cap_kw=None if cap_share is None else cap_share * cfg.pv.peak_kw,
        )

    def initial_state(self) -> State:
        return State(soc_kwh=0.5 * self.capacity_kwh, building_kwh=0.0,
                     tank_kwh=0.5 * self.tank_capacity_kwh)


FLOW_COLUMNS = (
    "household_kw", "hp_kw", "pv_kw", "pv_self_kw", "pv_to_battery_kw", "pv_export_kw",
    "curtail_kw", "grid_to_house_kw", "grid_to_battery_kw", "battery_to_house_kw",
    "battery_export_kw", "battery_charge_kw", "battery_discharge_kw", "trade_buy_kw",
    "trade_sell_kw", "import_kw", "export_kw", "soc_kwh", "building_kwh", "tank_kwh",
    "comfort_deficit_kwh", "backup_heat_kw",
)


def realise(sp: Setpoints, state: State, hh: Household, actual: dict, export_price: float) -> dict:
    """Apply setpoints to one actual hour; update ``state`` in place; return flows."""
    cop_sp, cop_hw = actual["cop_space"], actual["cop_hot_water"]
    hp_sp, hp_hw = max(sp.hp_space_kw, 0.0), max(sp.hp_hot_water_kw, 0.0)
    backup = 0.0

    # Thermal capacity limit: hot water keeps priority, space heating gets the rest.
    hp_hw = min(hp_hw, hh.hp_thermal_kw / cop_hw)
    hp_sp = min(hp_sp, max(hh.hp_thermal_kw - cop_hw * hp_hw, 0.0) / cop_sp)

    # Hot-water tank: the tap never runs dry; missing heat comes from extra heat-pump runtime.
    tank = hh.tank_retention * state.tank_kwh + cop_hw * hp_hw - actual["hot_water_kw"]
    if tank < 0.0:
        extra = -tank / cop_hw
        hp_hw += extra
        backup += extra
        tank = 0.0
    tank = min(tank, hh.tank_capacity_kwh)

    # Building: below the comfort band the thermostat adds heat within the pump's capacity.
    building = hh.building_decay * state.building_kwh + cop_sp * hp_sp - actual["space_heat_kw"]
    lower, upper = -hh.building_band_kwh, hh.building_band_kwh
    deficit = 0.0
    if building < lower:
        spare_thermal = max(hh.hp_thermal_kw - cop_sp * hp_sp - cop_hw * hp_hw, 0.0)
        extra_heat = min(lower - building, spare_thermal)
        hp_sp += extra_heat / cop_sp
        backup += extra_heat / cop_sp
        building += extra_heat
        deficit = max(lower - building, 0.0)
    building = min(building, upper)  # above the band, surplus heat is vented

    house = actual["household_kw"] + hp_sp + hp_hw
    pv = actual["pv_kw"] if hh.has_pv else 0.0

    # Battery power, limited by rating and state of charge.
    if hh.has_battery and sp.self_consumption_battery:
        surplus = pv - house
        charge = min(max(surplus, 0.0), hh.power_kw, (hh.capacity_kwh - state.soc_kwh) / hh.eta)
        discharge = min(max(-surplus, 0.0), hh.power_kw, state.soc_kwh * hh.eta)
        trade_buy = trade_sell = 0.0
    elif hh.has_battery:
        free = hh.capacity_kwh - state.soc_kwh - state.trade_soc_kwh
        charge = min(max(sp.battery_charge_kw, 0.0), hh.power_kw, max(free, 0.0) / hh.eta)
        trade_buy = min(max(sp.trade_buy_kw, 0.0), charge)
        trade_sell = min(max(sp.trade_sell_kw, 0.0), state.trade_soc_kwh * hh.eta)
        retail_out = min(max(sp.battery_discharge_kw - sp.trade_sell_kw, 0.0),
                         state.soc_kwh * hh.eta)
        discharge = min(trade_sell + retail_out, hh.power_kw)
        trade_sell = min(trade_sell, discharge)
    else:
        charge = discharge = trade_buy = trade_sell = 0.0

    pv_self = min(pv, house)
    pv_rest = pv - pv_self
    retail_charge = charge - trade_buy
    pv_to_battery = min(pv_rest, retail_charge)
    pv_rest -= pv_to_battery
    grid_budget = max(hh.grid_charging_budget_kwh - state.grid_charged_kwh, 0.0)
    grid_to_battery = min(retail_charge - pv_to_battery, grid_budget)
    # A PV shortfall is made up from the grid only within the grid-charging budget.
    charge = trade_buy + pv_to_battery + grid_to_battery

    retail_discharge = discharge - trade_sell
    battery_to_house = min(retail_discharge, house - pv_self)
    battery_export = retail_discharge - battery_to_house
    grid_to_house = house - pv_self - battery_to_house

    curtail = 0.0
    pv_export = pv_rest
    if export_price < 0.0:
        curtail, pv_export = pv_export, 0.0
    if hh.export_cap_kw is not None and pv_export + battery_export > hh.export_cap_kw:
        excess = pv_export + battery_export - hh.export_cap_kw
        cut = min(excess, pv_export)
        pv_export -= cut
        curtail += cut

    retail_in = charge - trade_buy
    state.soc_kwh = min(max(state.soc_kwh + hh.eta * retail_in - retail_discharge / hh.eta, 0.0),
                        hh.capacity_kwh)
    state.trade_soc_kwh = max(state.trade_soc_kwh + hh.eta * trade_buy - trade_sell / hh.eta, 0.0)
    state.building_kwh = building
    state.tank_kwh = tank
    state.grid_charged_kwh += grid_to_battery

    return {
        "household_kw": actual["household_kw"], "hp_kw": hp_sp + hp_hw, "pv_kw": pv,
        "pv_self_kw": pv_self, "pv_to_battery_kw": pv_to_battery, "pv_export_kw": pv_export,
        "curtail_kw": curtail, "grid_to_house_kw": grid_to_house,
        "grid_to_battery_kw": grid_to_battery, "battery_to_house_kw": battery_to_house,
        "battery_export_kw": battery_export, "battery_charge_kw": charge,
        "battery_discharge_kw": discharge, "trade_buy_kw": trade_buy,
        "trade_sell_kw": trade_sell, "import_kw": grid_to_house + grid_to_battery,
        "export_kw": pv_export + battery_export,
        "soc_kwh": state.soc_kwh + state.trade_soc_kwh,
        "building_kwh": building, "tank_kwh": tank, "comfort_deficit_kwh": deficit,
        "backup_heat_kw": backup,
    }


class RuleController:
    """Default behaviour of off-the-shelf devices, with no price awareness.

    Heat pump: thermostat holding the setpoint and a half-full hot-water tank.
    Battery: charge from PV surplus, discharge whenever the house needs power.
    """

    def __init__(self, hh: Household):
        self.hh = hh

    def plan(self, t: int, state: State, inputs: pd.DataFrame) -> Setpoints:
        row = inputs.iloc[t]
        hh = self.hh
        space = (row["space_heat_kw"] - hh.building_decay * state.building_kwh) / row["cop_space"]
        tank_target = 0.5 * hh.tank_capacity_kwh
        hot_water = (tank_target - hh.tank_retention * state.tank_kwh + row["hot_water_kw"])
        hot_water /= row["cop_hot_water"]
        return Setpoints(
            hp_space_kw=max(space, 0.0),
            hp_hot_water_kw=max(hot_water, 0.0),
            self_consumption_battery=True,
        )


def run(inputs: pd.DataFrame, hh: Household, controller, export_prices: np.ndarray) -> pd.DataFrame:
    state = hh.initial_state()
    rows = []
    records = inputs.to_dict("records")
    for t, actual in enumerate(records):
        setpoints = controller.plan(t, state, inputs)
        rows.append(realise(setpoints, state, hh, actual, float(export_prices[t])))
    return pd.DataFrame(rows, index=inputs.index, columns=list(FLOW_COLUMNS))
