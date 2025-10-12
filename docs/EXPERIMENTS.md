# EXPERIMENTS HARNESS

## CLI
```
qx exp entry-ab   --cfg <file> --variants overlays/policy_*.yaml --name <exp_id>
qx exp risk-grid  --cfg <file> --grid max_risk_frac=0.005,0.01,0.02 --name <exp_id>
qx exp cost-sweep --cfg <file> --grid bps=0.5,1,2 slippage_ticks=0,1,2 --name <exp_id>
qx exp wf         --cfg <file> --plan experiments/wf_60_20.yaml --name <exp_id>
qx exp regime-slice --cfg <file> --regimes vol_tercile,session,dow --name <exp_id>
qx exp portfolio  --cfg <file> --variants overlays/portfolio_*.yaml --name <exp_id>
qx exp compare    --exp experiments/<exp_id>
```

## Artifacts
- `experiments/<exp_id>/manifest.json`
- `experiments/<exp_id>/inputs_checksum.json` (hashes of in‑memory normalized bars, features DF, SIP table, merged config, seed)
- Per run (`runs/<run_id>/`): `signals.parquet`, `orders.parquet`, `fills.parquet`, `positions.parquet`, `equity.parquet`, `trades.parquet`, `risk_rejects.parquet`, `allocation_log.parquet`, `metrics.json`
- Reports: `experiments/<exp_id>/compare.json|md`

## Fairness
- Comparisons require matching `inputs_checksum.json` across variants unless `--force`.
- Seeds propagated; warmup periods enforced.
