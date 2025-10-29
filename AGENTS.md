# AGENTS GUIDE
1. Repo uses Python 3.11 with Ruff-managed style; keep edits deterministic.
2. Install workspace once via `make install`; use UV-managed editable packages.
3. Lint with `make lint`; format targeted files using `make format`.
4. Type-check using `make check-types` (mypy across all qx-* packages).
5. Run full tests with `make test`; prefer focused runs when iterating.
6. Single test: `pytest tests/path/to_file.py::test_case` or `pytest -k keyword`.
7. Daily HMM smoke: `make test-daily-hmm`; use for SIP regression sanity.
8. CLI smoke: `python examples/daily_hmm_sip_example.py` for pipeline validation.
9. Keep modules in domain packages (core/data/backtest/cli/screener) per existing layout.
10. Enforce 100-character lines, snake_case modules, CapWords classes, explicit imports.
11. Favor pure functions; annotate public APIs and configs with precise types.
12. Validate inputs early; raise `ValueError`/`RuntimeError` with actionable messages.
13. Avoid silent excepts; log via existing logging utilities when context matters.
14. Use f-strings, no wildcard imports, import standard libs, third-party, local (in that order).
15. Configuration-first: prefer toggles/YAML updates before touching strategy logic.
16. Keep tests colocated; add fixtures under `tests/fixtures`, never leak synthetic data elsewhere.
17. Respect existing Makefile targets; do not invent ad-hoc scripts without review.
18. No additional Cursor or Copilot rules are defined in this repo.
19. Before large changes, review `.pre-commit-config.yaml` and run required hooks locally.
20. Share proofs (logs, metrics) when modifying trading logic; document run commands.
