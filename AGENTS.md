# Repository Guidelines

## Project Structure & Module Organization
- `qx-core/src`, `qx-data/src`, `qx-backtest/src`: domain modules; keep shared abstractions in `qx-core`, data adapters in `qx-data`, and simulation logic in `qx-backtest`.
- `qx-cli`: CLI wiring and experiment launchers; examples under `examples/`.
- `scripts/`: reusable utilities; prefer parametrized Python scripts over ad-hoc shell.
- `tests/`: integration and regression suites; scenario assets live in `test_config/`.
- `docs/` and `docs/features/`: reference guides; `experiments/` holds playbooks for VWAP/SIP workflows.

## Build, Test, and Development Commands
- `make install`: installs all `qx-*` packages in editable mode via `uv pip`.
- `make lint`: runs Ruff static analysis; address warnings before committing.
- `make format`: applies Ruff formatting to staged files; run after large edits.
- `make check-types`: invokes mypy across `qx-*` trees.
- `make test`: executes the full pytest suite; for focused checks use `pytest -k <pattern>`.
- `python examples/daily_hmm_sip_example.py` or `qx-cli exp entry-ab experiments/vwap_daily_hmm/strategy.yaml`: exercise representative pipelines.

## Coding Style & Naming Conventions
- Python 3.11, Ruff-managed style with 100-character lines, f-strings, and explicit imports.
- Modules and folders use `snake_case`; exported classes follow `CapWords`.
- Annotate public functions, keep configuration files deterministic, avoid unused code (ruff `E`, `F`, `B`, `SIM` enforced).

## Testing Guidelines
- Pytest drives unit/integration coverage; colocate new tests near the relevant package.
- Name files `test_<feature>.py` and functions `test_<scenario>`.
- Validate portfolio P&L, fills, SIP scores for workflow tests; extend `tests/test_daily_hmm_end_to_end.py` when broad coverage is needed.
- Regression smoke: `make test-daily-hmm`.

## Commit & Pull Request Guidelines
- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`); imperative subjects, add context lines when touching multiple packages.
- Before PRs, squash/rebase, note strategy impact, link configurations or experiments, and share CLI/pytest output for substantive changes.
- Review JSON/YAML diffs carefully; keep broker credentials and data extracts out of Git.

## Security & Configuration Tips
- Load secrets via environment variables or ignored `.env` files.
- Store large market data in `runs/` or external storage; only anonymized samples (e.g., AAPL CSVs) belong in-repo.
- Audit experiment configs for unintended parameter drift before merging.
