"""Shared test data: two synthetic weeks, built once."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synthetic import synthetic_snapshot  # noqa: E402

from household_flex import config  # noqa: E402
from household_flex.inputs import build_inputs, read_snapshot  # noqa: E402


@lru_cache(maxsize=4)
def inputs_for(start: str = "2024-01-08", end: str = "2024-01-21",
               overrides: tuple = ()) -> tuple[pd.DataFrame, object]:
    cfg = config.load(overrides=dict(overrides))
    snapshot = synthetic_snapshot(2024)
    path = Path(__file__).resolve().parent / ".cache_synthetic_2024.csv"
    if not path.exists():
        snapshot.to_csv(path)
    inputs = build_inputs(read_snapshot(path), cfg)
    window = inputs.loc[start:end].copy()
    window.attrs = inputs.attrs
    return window, cfg
