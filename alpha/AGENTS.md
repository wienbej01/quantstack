# Repository Guidelines

## Project Structure & Module Organization
`src/` contains the runtime code, split by domain: `data/` for loaders, `features/` for feature
engineering, `signals/` for hypothesis logic, `backtest/` for execution and walk-forward
evaluation, and `metrics/` for diagnostics and performance stats. Put tunable parameters in
`config/backtest_config.yaml` before changing strategy code. Use `scripts/` for entry points such
as `run_full_backtest.py` and `run_hypothesis_test.py`. Keep tests in `tests/` with `test_*.py`
names. Generated outputs belong in `output/` or `reports/`; longer research notes belong in
`docs/` or `research/`.

## Build, Test, and Development Commands
Use the existing Python entry points directly:

- `python scripts/run_full_backtest.py --start 2025-12-23 --end 2026-01-20` runs the full
  backtest pipeline.
- `python scripts/run_hypothesis_test.py --hypothesis order_flow --start 2025-12-23 --end 2026-01-20`
  runs one signal family.
- `pytest tests/ -v` runs the full test suite.
- `pytest tests/test_features.py::test_book_imbalance_range -v` runs a focused test while
  iterating.

## Coding Style & Naming Conventions
Target Python 3.11. Use 4-space indentation, keep lines within 100 characters, and prefer
Ruff-compatible formatting even though no root config is checked in here. Use snake_case for
modules, functions, and variables; CapWords for classes. Keep imports ordered as standard library,
third-party, then local. Favor pure functions, explicit imports, type hints on public APIs,
f-strings, and early validation with actionable `ValueError` or `RuntimeError` messages.

## Testing Guidelines
Tests use `pytest`. Add or update tests with every behavior change, especially in loaders,
features, signals, and walk-forward logic. Follow the current pattern: real-data integration tests
for loaders where mounts are available, and synthetic fixtures for isolated signal behavior. Name
new tests `test_<behavior>` inside the matching `tests/test_<area>.py` file when possible.

## Commit & Pull Request Guidelines
Recent commits use concise, imperative subjects with optional prefixes such as `docs:`, `v3.3:`,
or `[AUTO-FIX]`. Keep the first line specific to the change. Pull requests should explain the
behavioral impact, list verification commands run, and call out any config or data-path changes.
If you modify trading or execution logic, include proof such as metrics, report paths, or sample
logs.
