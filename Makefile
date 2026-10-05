.PHONY: install data test lint analysis quick houses clean

PYTHON ?= python3
export PYTHONPATH := src

install:
	$(PYTHON) -m pip install -e '.[dev]'

data:
	$(PYTHON) scripts/download_data.py --year 2025

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src scripts tests

analysis: test
	$(PYTHON) scripts/run_analysis.py

quick:
	$(PYTHON) scripts/run_analysis.py --quick

clean:
	rm -rf .pytest_cache .ruff_cache tests/.cache_synthetic_2024.csv

houses: test
	$(PYTHON) scripts/run_houses.py
