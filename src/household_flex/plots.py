"""Figures: the cost bridge for the main household and the per-house comparison."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
TOTAL = "#9d9c96"
SAVING = "#2a78d6"   # categorical slot 1
COST = "#eb6834"     # categorical slot 2

STEPS = (  # label, from scenario, to scenario, kind
    ("Today", None, "S0", "total"),
    ("+ PV", "S0", "S2", "step"),
    ("+ battery", "S2", "S3", "step"),
    ("+ dynamic\ntariff", "S3", "S4", "step"),
    ("+ smart\ncontrol", "S4", "S5", "step"),
    ("With\neverything", None, "S5", "total"),
    ("Perfect\nforecasts", "S5", "S6", "whatif"),
    ("+ exchange\ntrading", "S6", "S7", "whatif"),
)


def _euro(value: float, signed: bool = False) -> str:
    text = f"€{abs(value):,.0f}"
    if signed:
        return ("−" if value < 0 else "+") + text
    return text


def cost_bridge(scenarios: pd.DataFrame, path: Path) -> None:
    cost = scenarios.set_index("scenario")["annual_cost_eur"]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.spines.left": False})
    fig, ax = plt.subplots(figsize=(10.5, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for x, (_label, start, end, kind) in enumerate(STEPS):
        if kind == "total":
            bottom, height, color, alpha = 0.0, cost[end], TOTAL, 1.0
            text = _euro(cost[end])
        else:
            change = cost[end] - cost[start]
            bottom, height = min(cost[start], cost[end]), abs(change)
            color = SAVING if change <= 0 else COST
            alpha = 1.0 if kind == "step" else 0.45
            text = _euro(change, signed=True)
            # Connector from the previous level to this step.
            ax.plot([x - 0.9 + 0.31, x - 0.31], [cost[start]] * 2, color=INK_2, lw=0.8)
        ax.bar(x, height, bottom=bottom, width=0.62, color=color, alpha=alpha,
               edgecolor=SURFACE, linewidth=2)
        ax.text(x, bottom + height + 25, text, ha="center", va="bottom", color=INK,
                fontsize=10, fontweight="bold" if kind == "total" else "normal")

    ax.axvline(5.5, color=INK_2, lw=0.8, ls=(0, (3, 3)))
    ax.text(5.6, cost.max() * 1.08, "Upper bounds, not achievable in practice",
            color=INK_2, fontsize=9, va="top")
    ax.set_xticks(range(len(STEPS)), [s[0] for s in STEPS], color=INK)
    ax.tick_params(axis="x", length=0)
    ax.tick_params(axis="y", length=0, colors=INK_2)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"€{v:,.0f}"))
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_ylim(0, cost.max() * 1.12)
    ax.set_ylabel("Annual energy cost (electricity incl. heat pump)", color=INK_2)

    pv = cost["S0"] - cost["S2"]
    battery = cost["S2"] - cost["S3"]
    control = cost["S3"] - cost["S5"]
    fig.suptitle(
        f"PV saves {_euro(pv)} a year; the battery adds {_euro(battery)}, "
        f"dynamic tariff + smart control {_euro(control)}",
        x=0.01, ha="left", fontsize=13, color=INK, fontweight="bold",
    )
    fig.text(0.01, 0.905, "Berlin 14197, 2025 weather and prices · 8 kWp PV, 10 kWh battery, "
             "ground-source heat pump · working assumptions, not measured consumption",
             color=INK_2, fontsize=9.5)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def _strip(ax, values: pd.Series, flagged: pd.Series, y: float, color: str) -> None:
    """One row of dots, one per house, jittered vertically; flagged houses hollow."""
    rng = np.random.default_rng(0)
    jitter = rng.uniform(-0.17, 0.17, len(values))
    solid = ~flagged.to_numpy()
    ax.scatter(values[solid], y + jitter[solid], s=34, color=color, alpha=0.85,
               edgecolor=SURFACE, linewidth=0.6, zorder=3)
    ax.scatter(values[~solid], y + jitter[~solid], s=34, facecolor="none", edgecolor=color,
               linewidth=1.1, zorder=3)
    ax.plot([values.median()] * 2, [y - 0.3, y + 0.3], color=INK, lw=2.0, zorder=4)


def houses_figure(per_house: pd.DataFrame, path: Path, reference: dict | None = None) -> None:
    """NPV of PV and of the best setup, and the battery break-even price, per house."""
    reference = reference or {}
    flagged = per_house["likely_backup_heater"].astype(bool)
    n = len(per_house)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.spines.left": False})
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.5, 4.6), dpi=150,
                                      gridspec_kw={"width_ratios": [1.6, 1.0]})
    fig.patch.set_facecolor(SURFACE)

    rows = (("PV, fixed tariff", "pv_npv_eur", "pv_npv"),
            ("PV + dynamic tariff\n+ smart heat pump", "best_npv_eur", "best_npv"))
    for y, (label, column, ref_key) in enumerate(rows):
        _strip(left, per_house[column], flagged, y, SAVING)
        if ref_key in reference:
            left.scatter(reference[ref_key], y + 0.38, marker="v", s=46, color=COST, zorder=5)
    left.axvline(0, color=INK_2, lw=0.8)
    left.set_yticks(range(len(rows)), [r[0] for r in rows], color=INK)
    left.set_ylim(-0.6, len(rows) - 0.4)
    left.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _euro(v, signed=v != 0)))
    left.set_xlabel("Net present value over 20 years, per house", color=INK_2)
    left.set_title("Investment value", loc="left", color=INK, fontsize=11)

    breakeven = per_house["battery_5kwh_breakeven_eur_per_kwh"]
    _strip(right, breakeven, flagged, 0, SAVING)
    if "battery_breakeven" in reference:
        right.scatter(reference["battery_breakeven"], 0.38, marker="v", s=46, color=COST, zorder=5)
    assumed = reference.get("battery_price", 600.0)
    right.axvline(assumed, color=INK_2, lw=0.8, ls=(0, (3, 3)))
    right.text(assumed, 0.55, f" assumed price\n €{assumed:,.0f}/kWh", color=INK_2, fontsize=8.5,
               va="top")
    right.set_yticks([0], ["5 kWh battery\non top"], color=INK)
    right.set_ylim(-0.6, 0.6)
    right.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"€{v:,.0f}"))
    right.set_xlabel("Break-even installed price (EUR/kWh), per house", color=INK_2)
    right.set_title("Battery", loc="left", color=INK, fontsize=11)

    for ax in (left, right):
        ax.set_facecolor(SURFACE)
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", length=0, colors=INK_2)

    pv_positive = int((per_house["pv_npv_eur"] > 0).sum())
    battery_pays = int((breakeven >= assumed).sum())
    battery_text = "none" if battery_pays == 0 else f"{battery_pays}"
    fig.suptitle(f"PV pays in {pv_positive} of {n} measured houses; a 5 kWh battery at "
                 f"€{assumed:,.0f}/kWh in {battery_text}",
                 x=0.01, ha="left", fontsize=13, color=INK, fontweight="bold")
    fig.text(0.01, 0.92, "Each dot is one household from the WPuQ field study (measured 2019 load) "
             "on the same roof, tariffs and 2025 Berlin prices.\nBar: median · triangle: the "
             "assumed household of the main analysis · hollow: heat-pump use points to a backup "
             "heater.", color=INK_2, fontsize=9, va="top", linespacing=1.4)
    fig.tight_layout()
    fig.subplots_adjust(top=0.78)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
