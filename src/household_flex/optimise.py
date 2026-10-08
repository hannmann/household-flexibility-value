"""Rolling cost-minimising controller: a linear programme re-solved every hour.

At each hour the controller plans until the last hour whose day-ahead price
is already published (prices for tomorrow appear at about 13:00 local time),
then commits only the first hour. Sunshine, household load and heat demand
come from forecasts (scenario S5) or from the actual values (S6, perfect
foresight). Prices inside the horizon are always known.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import coo_matrix

from .simulate import Household, RuleController, Setpoints, State

# Flow variables, each with one value per hour of the horizon.
FLOWS = ("u_load", "u_bat", "u_exp", "curt", "g_load", "g_bat", "d_load", "d_exp",
         "p_sp", "p_hw", "t_in", "t_out", "p_app")
F = {name: k for k, name in enumerate(FLOWS)}
COMFORT_PENALTY_EUR_PER_KWH = 10.0


def horizon_ends(index: pd.DatetimeIndex, timezone: str, publication_hour: int) -> np.ndarray:
    """For each hour, the exclusive end index of the hours with known prices."""
    local = index.tz_convert(timezone)
    days_ahead = np.where(local.hour >= publication_hour, 2, 1)
    # Wall-clock midnights, so days with a daylight-saving switch stay correct.
    naive_midnights = local.tz_localize(None).normalize() + pd.to_timedelta(days_ahead, unit="D")
    ends = naive_midnights.tz_localize(timezone)
    return np.minimum(index.searchsorted(ends.tz_convert("UTC")), len(index))


class OptimisingController:
    def __init__(self, hh: Household, cfg: SimpleNamespace, inputs: pd.DataFrame,
                 prices: pd.DataFrame, *, perfect_foresight: bool, trading: bool = False,
                 on_off: bool = False):
        self.hh = hh
        self.cfg = cfg
        self.trading = trading
        self.on_off = on_off
        self.share = cfg.control.terminal_value_share
        self.wear = cfg.battery.wear_cost_eur_per_kwh
        self.ends = horizon_ends(inputs.index, cfg.location.timezone,
                                 cfg.control.price_publication_hour_local)
        suffix = "" if perfect_foresight else "_fc"
        self.pv = inputs[f"pv{suffix}_kw"].to_numpy() if hh.has_pv else np.zeros(len(inputs))
        self.load = inputs[f"household{suffix}_kw"].to_numpy()
        self.space = inputs[f"space_heat{suffix}_kw"].to_numpy()
        self.hot_water = inputs[f"hot_water{suffix}_kw"].to_numpy()
        self.cop_sp = inputs[f"cop_space{suffix}"].to_numpy()
        self.cop_hw = inputs["cop_hot_water"].to_numpy()
        self.p_imp = prices["import"].to_numpy()
        self.p_exp = prices["export"].to_numpy()
        self.spot = prices["spot"].to_numpy()
        self.min_on = cfg.heat_pump.min_on_fraction
        appliance_day = "app_day_kwh" if perfect_foresight else "app_day_fc_kwh"
        self.app_day_kwh = inputs[appliance_day].to_numpy()
        self.app_window = inputs["app_window"].to_numpy() > 0
        self.app_day_id = inputs["app_day_id"].to_numpy()
        self.app_max_kw = cfg.household.appliances.max_kw
        self.fallback = RuleController(hh)
        self.failures = 0

    def plan(self, t: int, state: State, inputs: pd.DataFrame) -> Setpoints:
        end = max(int(self.ends[t]), t + 1)
        try:
            return self._solve(t, end, state)
        except RuntimeError:
            self.failures += 1
            return self.fallback.plan(t, state, inputs)

    def _solve(self, t0: int, end: int, state: State) -> Setpoints:
        hh = self.hh
        n = end - t0
        sl = slice(t0, end)
        pv, load, space, hw = self.pv[sl], self.load[sl], self.space[sl], self.hot_water[sl]
        cop_sp, cop_hw = self.cop_sp[sl], self.cop_hw[sl]
        p_imp, p_exp, spot = self.p_imp[sl], self.p_exp[sl], self.spot[sl]  # EUR/kWh

        nf = len(FLOWS) * n
        base_soc, base_s, base_w = nf, nf + (n + 1), nf + 2 * (n + 1)
        base_slack = nf + 3 * (n + 1)
        base_trade = base_slack + n          # exchange-trading compartment of the battery
        base_z = base_trade + (n + 1)
        n_var = base_z + (n if self.on_off else 0)
        hours = np.arange(n)

        def f(name: str) -> np.ndarray:
            return F[name] * n + hours

        rows, cols, vals = [], [], []

        def add(r: np.ndarray, c: np.ndarray, v) -> None:
            rows.append(np.asarray(r))
            cols.append(np.asarray(c))
            vals.append(np.broadcast_to(np.asarray(v, dtype=float), np.shape(r)))

        eta = hh.eta
        # Equalities: PV split, house balance, battery, building, tank.
        r = hours
        for name in ("u_load", "u_bat", "u_exp", "curt"):
            add(r, f(name), 1.0)
        r = n + hours
        for name, sign in (("u_load", 1), ("g_load", 1), ("d_load", 1), ("p_sp", -1), ("p_hw", -1),
                           ("p_app", -1)):
            add(r, f(name), sign)
        r = 2 * n + hours
        add(r, base_soc + hours + 1, 1.0)
        add(r, base_soc + hours, -1.0)
        for name in ("u_bat", "g_bat"):
            add(r, f(name), -eta)
        for name in ("d_load", "d_exp"):
            add(r, f(name), 1.0 / eta)
        r = 3 * n + hours
        add(r, base_s + hours + 1, 1.0)
        add(r, base_s + hours, -hh.building_decay)
        add(r, f("p_sp"), -cop_sp)
        r = 4 * n + hours
        add(r, base_w + hours + 1, 1.0)
        add(r, base_w + hours, -hh.tank_retention)
        add(r, f("p_hw"), -cop_hw)
        r = 5 * n + hours
        add(r, base_trade + hours + 1, 1.0)
        add(r, base_trade + hours, -1.0)
        add(r, f("t_in"), -eta)
        add(r, f("t_out"), 1.0 / eta)
        # Shiftable appliances: each local day's energy, within that day's window.
        b_app = []
        if hh.appliances_flexible:
            window = self.app_window[sl]
            days = self.app_day_id[sl]
            for day in np.unique(days):
                in_day = np.flatnonzero((days == day) & window)
                if in_day.size == 0:
                    continue
                energy = (state.appliance_left_kwh if day == days[0]
                          else float(self.app_day_kwh[t0 + in_day[0]]))
                add(np.full(in_day.size, 6 * n + len(b_app)), f("p_app")[in_day], 1.0)
                b_app.append(min(energy, self.app_max_kw * in_day.size))
        a_eq = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                          shape=(6 * n + len(b_app), n_var)).tocsr()
        b_eq = np.concatenate([pv, load, np.zeros(n), -space, -hw, np.zeros(n), b_app])

        # Inequalities.
        rows, cols, vals = [], [], []
        b_ub = []
        k = 0
        for name in ("u_bat", "g_bat", "t_in"):
            add(k + hours, f(name), 1.0)
        b_ub.append(np.full(n, hh.power_kw))
        k += n
        for name in ("d_load", "d_exp", "t_out"):
            add(k + hours, f(name), 1.0)
        b_ub.append(np.full(n, hh.power_kw))
        k += n
        add(k + hours, f("p_sp"), cop_sp)
        add(k + hours, f("p_hw"), cop_hw)
        if self.on_off:
            add(k + hours, base_z + hours, -hh.hp_thermal_kw)
            b_ub.append(np.zeros(n))
            k += n
            add(k + hours, f("p_sp"), -cop_sp)
            add(k + hours, f("p_hw"), -cop_hw)
            add(k + hours, base_z + hours, self.min_on * hh.hp_thermal_kw)
            b_ub.append(np.zeros(n))
        else:
            b_ub.append(np.full(n, hh.hp_thermal_kw))
        k += n
        add(k + hours, base_soc + hours + 1, 1.0)      # both compartments share the capacity
        add(k + hours, base_trade + hours + 1, 1.0)
        b_ub.append(np.full(n, hh.capacity_kwh))
        k += n
        add(k + hours, base_s + hours + 1, -1.0)       # S + slack >= 0: never below setpoint
        add(k + hours, base_slack + hours, -1.0)
        b_ub.append(np.zeros(n))
        k += n
        if hh.export_cap_kw is not None:
            add(k + hours, f("u_exp"), 1.0)
            add(k + hours, f("d_exp"), 1.0)
            b_ub.append(np.full(n, hh.export_cap_kw))
            k += n
        a_ub = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                          shape=(k, n_var)).tocsr()
        b_ub = np.concatenate(b_ub)

        # Bounds.
        lower = np.zeros(n_var)
        upper = np.full(n_var, np.inf)
        grid_budget = max(hh.grid_charging_budget_kwh - state.grid_charged_kwh, 0.0)
        if grid_budget <= 1e-9:
            upper[f("g_bat")] = 0.0
        else:
            upper[f("g_bat")] = min(hh.power_kw, grid_budget)
        if not (self.trading and hh.has_battery):
            upper[f("t_in")] = 0.0
            upper[f("t_out")] = 0.0
        upper[f("p_app")] = (self.app_max_kw * self.app_window[sl]
                             if hh.appliances_flexible else 0.0)
        if not hh.has_battery:
            for name in ("u_bat", "g_bat", "d_load", "d_exp", "t_in", "t_out"):
                upper[f(name)] = 0.0
        upper[base_soc:base_soc + n + 1] = hh.capacity_kwh
        lower[base_s:base_s + n + 1] = -np.inf
        upper[base_s:base_s + n + 1] = hh.building_max_kwh
        upper[base_w:base_w + n + 1] = hh.tank_capacity_kwh
        lower[base_soc] = upper[base_soc] = state.soc_kwh
        lower[base_s] = upper[base_s] = state.building_kwh
        lower[base_w] = upper[base_w] = state.tank_kwh
        upper[base_trade:base_trade + n + 1] = hh.capacity_kwh if self.trading else 0.0
        lower[base_trade] = upper[base_trade] = state.trade_soc_kwh
        if self.on_off:
            upper[base_z:base_z + n] = 1.0

        # Objective: money over the horizon minus the value of energy left in storage.
        c = np.zeros(n_var)
        c[f("g_load")] = p_imp
        c[f("g_bat")] = p_imp
        c[f("u_exp")] = -p_exp
        c[f("d_exp")] = -p_exp + self.wear
        c[f("d_load")] = self.wear
        c[f("curt")] = 1e-6
        c[f("t_in")] = spot
        c[f("t_out")] = -spot + self.wear
        c[base_slack:base_slack + n] = COMFORT_PENALTY_EUR_PER_KWH
        mean_price = float(np.mean(p_imp))
        c[base_soc + n] = -self.share * mean_price * eta
        c[base_s + n] = -self.share * mean_price / float(np.mean(cop_sp))
        c[base_w + n] = -self.share * mean_price / float(np.mean(cop_hw))
        c[base_trade + n] = -self.share * float(np.mean(spot)) * eta

        if self.on_off:
            integrality = np.zeros(n_var)
            integrality[base_z:base_z + n] = 1
            result = milp(c, integrality=integrality, bounds=Bounds(lower, upper),
                          constraints=[LinearConstraint(a_eq, b_eq, b_eq),
                                       LinearConstraint(a_ub, -np.inf, b_ub)],
                          options={"time_limit": 10.0, "mip_rel_gap": 0.01})
        else:
            result = linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq,
                             bounds=np.column_stack([lower, upper]), method="highs")
        if result.x is None or not result.success:
            raise RuntimeError(result.message)
        x = result.x

        def first(name: str) -> float:
            return float(x[F[name] * n])

        return Setpoints(
            hp_space_kw=first("p_sp"),
            hp_hot_water_kw=first("p_hw"),
            battery_charge_kw=first("u_bat") + first("g_bat") + first("t_in"),
            battery_discharge_kw=first("d_load") + first("d_exp") + first("t_out"),
            trade_buy_kw=first("t_in"),
            trade_sell_kw=first("t_out"),
            grid_charge_kw=first("g_bat"),
            export_discharge_kw=first("d_exp"),
            appliance_kw=first("p_app"),
        )
