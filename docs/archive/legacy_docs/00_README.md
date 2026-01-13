# QuantStack — Overview & Quickstart

QuantStack is a modular, **infrastructure‑first** trading research stack designed for repeatable strategy development. It enforces strict data and interface contracts, separates concerns cleanly, and enables fair comparative experiments — all **without** mutating your existing data lake until an explicit, VM‑only finalization step.

## Purpose
- Provide a **clean, reproducible** foundation for new strategies.
- Keep legacy strategies working **unchanged**.
- Enable **fair A/B testing** of entries, exits, risk and costs with robust schema validation.

## What’s included
- Data contracts (Bronze → Silver → Gold) with **read‑only** runtime normalization for hashing.
- Experiments harness (**`qx-cli exp`**) and required artifacts.
- Feature library contracts and scanner spec.
- Risk, portfolio, and reporting outputs.
- Finalization plan for **one‑shot** parquet normalization (VM‑only, at the very end).

## Quickstart (Smoke Test Path)
1. Generate or point to a tiny Gold slice (or use the helper script):
   ```bash
   python check_gold_and_make_smoke_sample.py --gold-root /home/jacobw/gcs-mount/gold --family bars_1m --symbol AAPL --year 2024 --month 01 --n-files 2 --write-sample --out-dir /tmp/e2e_smoke_from_gold
   ```
2. Run an A/B experiment:
   ```bash
   python -m qx_cli exp entry-ab --cfg /tmp/e2e_smoke/config/strategy.yaml --variants /tmp/e2e_smoke/overlays/policy_*.yaml --name smoke_e2e_ab
   ```
3. Validate outputs:
   ```bash
   python test_exp_artifacts.py --runs-root runs
   ```

## Repo layout (suggested)
```
quantstack/
  qx-core/           # schemas, validation, utilities
  qx-cli/            # CLI: qx exp ...
  qx-features/       # feature packs, adapters
  qx-backtest/       # engine emitting standardized artifacts
  qx-report/         # report builders over artifacts
  tools/             # helper scripts (smoke, validators)
  docs/              # this documentation package
```

> All data‑lake rewrites and full parquet scans are **deferred** to the VM‑only Finalization Phase.
