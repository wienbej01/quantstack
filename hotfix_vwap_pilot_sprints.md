# Hotfix Sprints — Make the VWAP Pilot Real (v2.1.HF)

Your report says it all: the plumbing runs, the behavior is fake. This plan rips out the stubs and wires real logic for features → policy → risk → fills → metrics. No lake mutations.

---

## 0) Principles (still binding)
- Read-only against `/home/jacobw/gcs-mount/gold`.
- Determinism: seeds set, sorting stable, identical inputs ⇒ identical outputs + hashes.
- All public boundaries validated (schemas in `qx-core/schemas.py`).

---

## 1) What’s wrong (from your pilot)
- Policy overlays don’t reach the policy. Same signals both variants.
- Dummy checksums (`dummy_*`) mask fairness; must hash real dataframes.
- Backtest emits canned trade. Fills/costs not applied. Exits not implemented.
- Risk R calculation is nonsense. No ATR stop distance persisted.

---

## 2) Scope of this hotfix
Replace stubs with minimal-but-real implementations for: features, screener, policy, risk, fills/costs, hashing, and diagnostics.
Do NOT touch Bronze/Silver. Do NOT rewrite Gold.

---

## 3) Deliverables by module (exact files)

### 3.1 qx-core
- `qx-core/hashers.py`
  - `hash_dataframe(df, cols=None, index=False, algo="blake2b") -> str` (serialize subset with stable dtype coercions, tz-normalize to UTC ns, sort by [symbol, ts], use pyarrow to buffer or pandas.to_pickle())
  - Tests validate stability across file order and identical content.

- `qx-core/schemas.py`
  - Ensure schemas cover: `trades`, `metrics`, `inputs_checksum`, `allocation_log`, `risk_rejects`.
  - Add keys: `stop_dist_ps` (per-share), `fees`, `slippage_est` to trades.

### 3.2 qx-data
- `qx-data/gold_loader.py`
  - `load_bars(root, family, symbols, dates)` returning canonical DF: [`ts[UTC ns]`, `symbol`, `open`, `high`, `low`, `close`, `volume`, optional `vwap`, `trades`].
  - No directory-wide scans. Load only requested partitions. Normalize in-memory.

### 3.3 qx-features
- `qx-features/core_basics.py`
  - `vwap_m(df, lookback_m)` compute rolling VWAP if not present.
  - `rel_volume_m(df, lookback_m)` current vol / rolling mean vol.
  - `atr_m(df, lookback_m)` intraday ATR on bar OHLC.
- `qx-features/registry.py`
  - Compose above from config and append columns named:
    - `f__ta__vwap_{m}`, `f__vol__rel_volume_{m}`, `f__vol__atr_{m}`.
- Warmup: return a boolean `f__warmup_ok` for gating.

### 3.4 qx-screener
- `qx-screener/sip.py`
  - `screen(df, rvol_col, top_n=5, whitelist=None) -> dict[ts -> set(symbol)]`

### 3.5 qx-backtest
- `qx-backtest/policies/vwap_revert.py`
  - Params: `rvol_min`, `vwap_col`, `rvol_col`, `timeout_bars`.
  - Entry long when `close < vwap` and `rvol >= rvol_min` and symbol in SIP set (if enabled) and `f__warmup_ok`.
  - Exit when `close >= vwap` (touch) or `timeout_bars` reached.
  - Emit `signals.parquet` with `signal` ∈ {1,0} and diagnostic columns used in decisions.

- `qx-backtest/engine.py`
  - Next-open fills; apply `bps` and `per_share` costs; optional `slippage_ticks` (use tick_size from config or infer minimal price step).
  - Emit standard artifacts; compute trades from position transitions.

### 3.6 qx-risk
- `qx-risk/atr_stop.py`
  - Qty sizing so `qty * atr * atr_mult <= max_risk_frac * equity`.
  - Persist `stop_dist_ps = atr * atr_mult` into trades for R computation.
  - Reject orders when caps not met; log to `risk_rejects.parquet`.

### 3.7 qx-cli (experiments)
- Ensure overlays merge into `policy.params` and `sip.*` and reach the policy/risk.
- `inputs_checksum.json` fields:
  - `bars_norm_hash` (hash of normalized bars actually used)
  - `features_hash` (hash of DF of added features)
  - `sip_hash` (hash of SIP selection mapping rendered as a stable JSON)
  - `config_hash` and `seed`

### 3.8 Diagnostics
- Manifest must record resolved params per variant.
- `signals.parquet` include `decision_trace` JSON for the first 200 signal rows.

---

## 4) Tests (must pass)

### Unit
- Hash stability across shuffles and dtype-equivalent frames.
- Feature columns numeric, deterministic; warmup enforced.
- Policy transitions around VWAP are sensible on a toy DF.

### Integration (sample data, 3 days × 2 symbols)
- Variant A (`rvol_min=1.0`) vs Variant B (`rvol_min=1.5`) produce different trade counts.
- Trades carry non-zero `fees` when costs configured.
- `R` equals `pnl / (stop_dist_ps * qty)` for each trade.
- Re-run yields identical checksums and artifacts (file hashes or metrics).

### Golden
- Freeze tiny experiment; re-run reproduces byte-for-byte `inputs_checksum.json` and stable metrics within tolerance.

---

## 5) Runbook (pilot)

```bash
cd ~/quantstack
source .venv/bin/activate

# A/B run
EXP_ID=vwap_revert_hotfix_$(date +%Y%m%d_%H%M%S)
python -m qx_cli exp entry-ab   --cfg experiments/vwap_revert/strategy.yaml   --variants experiments/vwap_revert/overlays/policy_*.yaml   --name $EXP_ID

# Validate
python tools/test_exp_artifacts.py --runs-root runs

# Prove variant separation (quick)
python - <<'PY'
import glob, pandas as pd, json, os
exp = sorted(glob.glob('experiments/vwap_revert_hotfix_*'))[-1]
runs = sorted(glob.glob('runs/*'))
print('[info] EXP', exp)
for r in runs[-2:]:
    tr = glob.glob(os.path.join(r,'trades.parquet'))[0]
    df = pd.read_parquet(tr)
    print(r, 'trades=', len(df), 'mean_pnl=', float(df['pnl'].mean()), 'median_R=', float(df['r_multiple'].median()))
PY
```

Expected: different trade counts or R across variants, non-zero fees, checksums equal between variants, and identical on re-run.

---

## 6) Prompts for the LLM coder (one per module)

**P‑CORE‑HASHERS**  
Implement `qx-core/hashers.py` and tests per §3.1. Enforce UTC ns, sort keys, stable dtype coercions. Return functions + unit tests.

**P‑DATA‑GOLD**  
Implement `qx-data/gold_loader.py` per §3.2. Accept `root,family,symbols,dates`. Normalize to canonical schema. No lake writes.

**P‑FEAT‑CORE**  
Implement `qx-features/core_basics.py` and `registry.py` per §3.3. Add warmup flag. Provide unit tests producing exact columns.

**P‑SIP‑SCREEN**  
Implement `qx-screener/sip.py` per §3.4. Deterministic top-N on ties via symbol sort. Unit test with ties.

**P‑POLICY‑VWAP**  
Implement `qx-backtest/policies/vwap_revert.py` per §3.5. Include decision_trace. Unit tests for entry/exit around VWAP.

**P‑RISK‑ATR**  
Implement `qx-risk/atr_stop.py` per §3.6. Persist `stop_dist_ps`. Unit tests for sizing and rejects.

**P‑BT‑ENGINE**  
Upgrade `qx-backtest/engine.py` per §3.5 (fills/costs, artifacts). Integration test on toy dataset.

**P‑CLI‑CHECKSUMS**  
Wire overlays and compute real `inputs_checksum.json` per §3.7. Golden test: identical on re-run.

Return: modified files tree, test outputs, and a short diff of behavior between variants.

---

## 7) Definition of Done (pilot hotfix)
- Variant separation demonstrated (trade counts or R differ).
- `inputs_checksum.json` uses real hashes.
- Trades have non-zero `fees` when costs set; `stop_dist_ps` present.
- Re-run reproduces identical checksums and metrics.
- No writes to the lake; all outputs in `experiments/` and `runs/`.
