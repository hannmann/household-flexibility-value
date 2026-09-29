"""Load the configuration as nested attribute-access objects."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "household.yaml"


def _to_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _to_namespace(item) for key, item in value.items()})
    return value


def load_raw(path: Path = DEFAULT_CONFIG) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build(raw: dict, overrides: dict[str, Any] | None = None) -> SimpleNamespace:
    """Turn a raw config dict into a namespace, applying dotted-path overrides.

    Example: build(raw, {"battery.capacity_kwh": 5.0})
    """
    data = copy.deepcopy(raw)
    for dotted, value in (overrides or {}).items():
        node = data
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        if leaf not in node:
            raise KeyError(f"Unknown config key: {dotted}")
        node[leaf] = value
    return _to_namespace(data)


def load(path: Path = DEFAULT_CONFIG, overrides: dict[str, Any] | None = None) -> SimpleNamespace:
    return build(load_raw(path), overrides)
