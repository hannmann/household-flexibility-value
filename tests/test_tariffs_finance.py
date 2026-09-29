from __future__ import annotations

import math

import pandas as pd

from household_flex import config
from household_flex.finance import appraise, investment_eur
from household_flex.tariffs import export_price, import_price


def test_dynamic_price_adds_fixed_parts_and_vat_to_spot() -> None:
    cfg = config.load()
    spot = pd.Series([100.0, -50.0])  # EUR/MWh
    price = import_price(spot, cfg, dynamic=True)
    expected = (0.10 + 0.015) * 1.19 + 0.218
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
