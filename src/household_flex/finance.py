"""Investment appraisal: net present value and payback of the hardware."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np


def investment_eur(cfg: SimpleNamespace, pv: bool, battery_kwh: float) -> float:
    inv = cfg.investment
    cost = 0.0
    if pv:
        cost += cfg.pv.peak_kw * inv.pv_eur_per_kwp
    if battery_kwh > 0:
        cost += battery_kwh * inv.battery_eur_per_kwh + inv.energy_management_eur
    return cost


def appraise(annual_saving_eur: float, cfg: SimpleNamespace, pv: bool, battery_kwh: float) -> dict:
    """Cash flows over the PV lifetime for a first-year saving versus today.

    Savings shrink with PV degradation; PV operation and maintenance and one
    battery replacement are costs. Prices are held at the simulated year's level.
    """
    inv = cfg.investment
    capex = investment_eur(cfg, pv, battery_kwh)
    years = np.arange(1, inv.pv_lifetime_years + 1)
    savings = annual_saving_eur * (1.0 - inv.pv_degradation_per_year) ** (years - 1)
    costs = np.zeros(len(years))
    if pv:
        costs += inv.pv_om_share_per_year * cfg.pv.peak_kw * inv.pv_eur_per_kwp
    if battery_kwh > 0 and inv.battery_lifetime_years < inv.pv_lifetime_years:
        replacement_year = inv.battery_lifetime_years + 1
        costs[years == replacement_year] += (
            inv.battery_replacement_cost_share * battery_kwh * inv.battery_eur_per_kwh
        )
    cash = savings - costs
    discount = (1.0 + inv.discount_rate) ** -years
    cumulative = np.cumsum(cash * discount) - capex
    paid_back = np.flatnonzero(cumulative >= 0)
    return {
        "investment_eur": capex,
        "first_year_saving_eur": annual_saving_eur,
        "npv_eur": float(cumulative[-1]),
        "payback_years": float(years[paid_back[0]]) if paid_back.size else float("nan"),
    }
