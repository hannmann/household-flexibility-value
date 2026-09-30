"""The cost bridge: from today's annual bill to the optimised setup."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
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
