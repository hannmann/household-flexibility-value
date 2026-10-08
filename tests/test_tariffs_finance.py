from __future__ import annotations

import math
from types import SimpleNamespace

import pandas as pd

from household_flex import config, finance
from household_flex.finance import appraise, investment_eur
from household_flex.tariffs import export_price, import_price


def test_dynamic_price_adds_fixed_parts_and_vat_to_spot() -> None:
    cfg = config.load()
    spot = pd.Series([100.0, -50.0])  # EUR/MWh
    price = import_price(spot, cfg, dynamic=True)
    expected = (0.10 + 0.015 + 0.15895325) * 1.19
    assert math.isclose(price.iloc[0], expected)
    assert price.iloc[1] > 0  # fixed parts keep retail positive at negative spot


def test_fixed_feed_in_pays_nothing_at_negative_prices() -> None:
    cfg = config.load()
    price = export_price(pd.Series([50.0, -1.0]), cfg)
    assert math.isclose(price.iloc[0], 0.077)
    assert price.iloc[1] == 0.0


def test_market_feed_in_can_cost_money_at_negative_prices() -> None:
    cfg = config.load(overrides={"tariffs.feed_in.regime": "market"})
    price = export_price(pd.Series([50.0, -80.0]), cfg)
    assert math.isclose(price.iloc[0], 0.05 + 0.015)
    assert price.iloc[1] < 0


def test_appraisal_without_savings_loses_the_investment() -> None:
    cfg = config.load()
    result = appraise(0.0, cfg, pv=True, battery_kwh=10.0)
    assert result["investment_eur"] == investment_eur(cfg, True, 10.0)
    assert result["npv_eur"] < -result["investment_eur"]
    assert math.isnan(result["payback_years"])


def test_large_savings_pay_back_within_lifetime() -> None:
    cfg = config.load()
    result = appraise(3000.0, cfg, pv=True, battery_kwh=0.0)
    assert result["npv_eur"] > 0
    assert 1 <= result["payback_years"] <= 6


def test_battery_breakeven_price_gives_zero_npv() -> None:
    cfg = config.load()
    price = finance.battery_breakeven_eur_per_kwh(218.0, cfg, 5.0)
    inv = SimpleNamespace(**{**vars(cfg.investment), "battery_eur_per_kwh": price})
    probe = SimpleNamespace(**{**vars(cfg), "investment": inv,
                               "pv": SimpleNamespace(peak_kw=0.0)})
    assert abs(appraise(218.0, probe, False, 5.0)["npv_eur"]) < 1e-6
    assert 300.0 < price < 450.0  # hand calculation: about 375 EUR/kWh
