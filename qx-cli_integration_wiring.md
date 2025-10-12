# qx-cli Integration Wiring — From Stubs to Real Runs

You already built the modules. Now glue them together so A/B variants actually diverge.

## 0) Non‑negotiables
- **Read-only**: never write under `/home/jacobw/gcs-mount/gold`.
- **Determinism**: set seed, stable sorts, UTC ns timestamps everywhere.
- **Fairness**: variants must share identical `inputs_checksum.json` (bars/features/SIP/config hash), else `compare` refuses.

## 1) Orchestration flow (entry-ab)

File: `qx_cli/exp/entry_ab.py`

```text
load_base_cfg + overlays → resolve_config
         │
         ▼
load_bars()  → bars_norm_hash
         │
         ▼
apply_features() → features_df, features_hash, warmup gating
         │
         ▼
sip.screen() → universe_map{ts→symbols}, sip_hash
         │
         ▼
policy.generate_signals() (uses bars + features + universe)
         │
         ▼
risk.size_and_stops() → orders with qty, stop_dist_ps
         │
         ▼
backtest.run() → artifacts (orders, fills, positions, trades, equity, metrics)
         │
         ▼
write manifest + inputs_checksum (real hashes) + compare
```

## 2) Concrete calls & signatures

- `qx_data.gold_loader.load_bars(root, family, symbols, dates) -> pd.DataFrame`
  - Columns: `ts[UTC ns], symbol, open, high, low, close, volume, (optional) vwap, trades`
  - Sort by `[symbol, ts]`

- `qx_features.registry.apply(df, packs, params) -> (df_with_features, warmup_mask)`
  - Adds `f__ta__vwap_{m}`, `f__vol__rel_volume_{m}`, `f__vol__atr_{m}`
  - Returns `f__warmup_ok` mask or equivalent

- `qx_screener.sip.screen(df, rvol_col, top_n=5, whitelist=None) -> dict[int, set[str]]`
  - Deterministic on ties: sort symbols asc

- `qx_backtest.policies.vwap_revert.generate_signals(df, params, universe_map, warmup_mask) -> pd.DataFrame[signals]`
  - Must add diagnostic cols used in decisions for first 200 rows as `decision_trace` JSON

- `qx_risk.atr_stop.size_orders(signals, df, params, equity) -> (orders_df, rejects_df)`

- `qx_backtest.engine.run(bars, orders, cfg) -> artifacts`
  - Apply `bps`, `per_share`, `slippage_ticks` (tick_size from cfg or 0.01 fallback)
  - Emit parquet: `signals, orders, fills, positions, equity, trades, risk_rejects, allocation_log`
  - Emit `metrics.json`

- `qx_core.hashers.hash_dataframe(df, cols=...) -> str`
  - Use for `bars_norm_hash` (bars used), `features_hash` (new feature cols only)
  - For SIP, hash a deterministically serialized mapping (JSON with sorted keys)

## 3) Inputs checksum schema (real, not dummy)
Write `experiments/<exp_id>/inputs_checksum.json`:
```json
{
  "bars_norm_hash": "<blake2b>",
  "features_hash": "<blake2b>",
  "sip_hash": "<blake2b>",
  "config_hash": "<blake2b of merged cfg>",
  "seed": 42
}
```
Fail `compare` if any of the hashes differ between variants.

## 4) Manifest
`experiments/<exp_id>/manifest.json` must include:
- resolved config (fully merged)
- exact feature packs and params
- policy params and SIP params actually used
- data slice (symbols, dates, gold_root)
- git commit or “dirty” flag if repo changed

## 5) Error messages that save hours
- When warmup prevents trading: log `warmup_bars_required` and first tradable ts.
- When SIP is empty: log “SIP returned 0 symbols for {ts}” count.
- When sizing rejects: write reason and thresholds in `risk_rejects.parquet`.

## 6) Tests to wire into CI
- **Variant separation**: with `rvol_min=1.0` vs `1.5`, trade counts differ.
- **Checksum identity**: rerun same config → identical `inputs_checksum.json`.
- **Costs present**: non-zero `fees` in trades when costs configured.
- **R sanity**: `R == pnl / (stop_dist_ps * qty)` per trade within 1e‑9.

## 7) Exit conditions
- On VWAP touch, close position that bar; if `timeout_bars`, close at timeout close.
- End-of-day flatten only if explicitly configured; don’t silently hold overnight.

## 8) CLI UX
- `qx exp entry-ab --cfg ... --variants ... --name ... --force` only bypasses fairness, not schema validation.
- Print a concise run summary: trades per variant, mean pnl, median R, first differences in `signals` if counts equal.

## 9) Performance notes
- Hash large frames in chunks (by symbol) if needed; combine with incremental blake2b.
- Always hash the **normalized view actually used** by the backtest, not raw parquet buffers.
