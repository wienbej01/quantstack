# E2E SMOKE TEST

## Using a Gold slice
1. Inspect a small AAPL partition and optionally write a tiny sample:
   ```bash
   python check_gold_and_make_smoke_sample.py --gold-root /home/jacobw/gcs-mount/gold --family bars_1m --symbol AAPL --year 2024 --month 01 --n-files 2 --write-sample --out-dir /tmp/e2e_smoke_from_gold
   ```
2. Run an A/B experiment and validate artifacts:
   ```bash
   python -m qx_cli exp entry-ab --cfg /tmp/e2e_smoke/config/strategy.yaml --variants /tmp/e2e_smoke/overlays/policy_*.yaml --name smoke_e2e_ab
   python test_exp_artifacts.py --runs-root runs
   ```

## Minimal gates
- At least 10 trades, no NaN in `pnl`, equity curve present.
- Compare report rendered, checksum rules enforced.
