# Repository Guidelines

## Project Structure & Module Organization
- `src/` holds the discovery pipeline modules (data loading, features, filters, validation).
- Entry scripts live at repo root: `discover.py`, `run_long_short_discovery.py`,
  `discover_aaa.py`, `run_aaa_discovery_wrapper.py`.
- Configuration is YAML in `config/aaa_config.yaml`.
- Generated outputs and caches go under `output*/`; do not edit these by hand.
- Tests currently include root-level `test_*.py`; add new tests under `tests/` and place
  fixtures in `tests/fixtures/`.

## Build, Test, and Development Commands
- From the workspace root `/home/jacobw/quantstack`:
  - `make install` (UV-managed editable setup)
  - `make lint` (Ruff lint)
  - `make format` (format targeted files)
  - `make check-types` (mypy for qx-* packages)
  - `make test` (full test suite)
  - `make test-daily-hmm` and `python examples/daily_hmm_sip_example.py` (SIP smoke tests)
- From this repo:
  - `python3 run_long_short_discovery.py` (default discovery run)
  - `python3 run_aaa_discovery_wrapper.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD`
  - `pytest -q sip_pattern_discovery/test_aaa_quick.py` (run from workspace root so
    pythonpath resolves)

## Coding Style & Naming Conventions
- Python 3.11; Ruff-managed style; keep edits deterministic; 100-character lines.
- Use snake_case modules/functions, CapWords classes, explicit imports, no wildcard imports.
- Import order: standard library, third-party, local.
- Prefer pure functions and typed public APIs/configs.
- Validate inputs early; raise `ValueError`/`RuntimeError` with actionable messages.
- Use f-strings; avoid silent `except`; log via existing utilities when context matters.
- Use Makefile targets when available; do not add ad-hoc scripts without review.

## Testing Guidelines
- Pytest-based. Name tests `test_*.py` and keep them close to the code they cover.
- Use focused runs during iteration: `pytest -k keyword` or
  `pytest tests/path/to_file.py::test_case`.
- For large changes, review `.pre-commit-config.yaml` and run required hooks locally.

## Commit & Pull Request Guidelines
- Commit subjects are concise and imperative; common prefixes include `docs:` and `Fix:`.
- PRs should describe scope, link issues when applicable, and include validation evidence
  (commands run; logs/metrics if trading logic changes).

## Configuration & Data Notes
- Favor configuration changes (`config/aaa_config.yaml`) before altering strategy logic.
- Use real Gold/SIP data for analysis; do not introduce synthetic data in reports/fixtures.
