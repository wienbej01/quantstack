# PROMPT — Gemini CLI Integration Task (qx-cli → real pipeline)

You must integrate `qx-cli exp entry-ab` with the real modules so A/B variants produce different behavior. **Do not write to the data lake.**

## Read these first (source of truth)
- `~/quantstack/docs/00_README.md`
- `~/quantstack/docs/EXPERIMENTS.md`
- `~/quantstack/docs/SCHEMAS.md`
- `~/quantstack/docs/E2E_SMOKE_TEST.md`
- `~/quantstack/docs/DEVELOPER_GUIDE.md`
- `~/quantstack/tools/check_gold_and_make_smoke_sample.py`
- `~/quantstack/tools/test_exp_artifacts.py`
- `~/hotfix_vwap_pilot_sprints.md`
- `~/quantstack_cli_integration/qx-cli_integration_wiring.md` (this repo)

## Non-negotiables
- Read-only against `/home/jacobw/gcs-mount/gold`.
- Deterministic hashing; identical inputs + config ⇒ identical `inputs_checksum.json`.
- Enforce fairness: refuse `compare` if hashes differ and `--force` not passed.

## Tasks
1. Implement orchestration in `qx_cli/exp/entry_ab.py` following the flow:
   - load_bars → apply_features → sip.screen → policy.generate_signals → risk.size → backtest.run
   - compute and write real `inputs_checksum.json` and `manifest.json`
2. Ensure overlays mutate behavior (`rvol_min` differences must change signals).
3. Emit all artifacts and pass `tools/test_exp_artifacts.py`.
4. Add console summary: trades per variant, mean pnl, median R, first differing signal rows.

## Run
```bash
cd ~/quantstack && source .venv/bin/activate

# Sample from Gold to /tmp (read-only in, write out)
python tools/check_gold_and_make_smoke_sample.py --gold-root /home/jacobw/gcs-mount/gold --family bars_1m --symbol AAPL --year 2024 --month 01 --n-files 2 --write-sample --out-dir /tmp/e2e_smoke_from_gold

# Point configs to /tmp or to real GCS Gold (read-only)
EXP_ID=vwap_revert_integrated_$(date +%Y%m%d_%H%M%S)
python -m qx_cli exp entry-ab --cfg experiments/vwap_revert/strategy.yaml --variants experiments/vwap_revert/overlays/policy_*.yaml --name $EXP_ID

python tools/test_exp_artifacts.py --runs-root runs
```

## Acceptance
- Variant separation demonstrated (trade counts or R differ).
- `inputs_checksum.json` uses real hashes and matches across variants.
- Non-zero `fees` when costs configured; `stop_dist_ps` present in trades.
- Re-run with same seed reproduces identical checksums and metrics.
