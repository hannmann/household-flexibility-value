"""Prices the household pays and receives, and the annual bill."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd


def import_price(spot_eur_mwh: pd.Series, cfg: SimpleNamespace, dynamic: bool) -> pd.Series:
    """Gross retail price in EUR/kWh for each hour."""
    tariffs = cfg.tariffs
    if not dynamic:
        return pd.Series(tariffs.fixed_price_ct_per_kwh / 100.0, index=spot_eur_mwh.index)
    dyn = tariffs.dynamic
    net = (spot_eur_mwh / 1000.0 + dyn.supplier_markup_ct_per_kwh / 100.0
           + dyn.non_energy_net_ct_per_kwh / 100.0)
    return net * (1.0 + dyn.vat)


def export_price(spot_eur_mwh: pd.Series, cfg: SimpleNamespace) -> pd.Series:
    """EUR/kWh received for electricity fed into the grid."""
    feed_in = cfg.tariffs.feed_in
    spot = spot_eur_mwh / 1000.0
    if feed_in.regime == "fixed":
        price = pd.Series(feed_in.fixed_ct_per_kwh / 100.0, index=spot.index)
    elif feed_in.regime == "market":
        price = spot + feed_in.market_bonus_ct_per_kwh / 100.0
    else:
        raise ValueError(f"Unknown feed-in regime: {feed_in.regime}")
    if feed_in.no_payment_at_negative_prices:
        price = price.where(spot >= 0.0, np.minimum(price, 0.0))
    return price


def settle(
    flows: pd.DataFrame, prices: pd.DataFrame, cfg: SimpleNamespace, smart_meter: bool
) -> dict:
    """Annual money flows for one simulated year of hourly flows (kWh per hour)."""
    import_cost = float((flows["import_kw"] * prices["import"]).sum())
    export_revenue = float((flows["export_kw"] * prices["export"]).sum())
    wear = float(flows["battery_discharge_kw"].sum() * cfg.battery.wear_cost_eur_per_kwh)
    trading = float(((flows["trade_sell_kw"] - flows["trade_buy_kw"]) * prices["spot"]).sum())
    meter = cfg.tariffs.smart_meter_eur_per_year if smart_meter else 0.0
    base = cfg.tariffs.annual_base_eur
    # Wear is an opportunity cost in dispatch, not a cash payment. Replacement
    # is already charged separately by the investment appraisal.
    total = import_cost - export_revenue - trading + meter + base
    return {
        "import_cost_eur": import_cost,
        "export_revenue_eur": export_revenue,
        "battery_wear_eur": wear,
        "trading_margin_eur": trading,
        "smart_meter_eur": meter,
        "annual_base_eur": base,
        "dispatch_cost_including_wear_eur": total + wear,
        "annual_cost_eur": total,
    }
