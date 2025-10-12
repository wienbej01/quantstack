
# Sprint Plan (v2.1) — VWAP Mean‑Reversion Pilot

**Source spec:** `~/restructure_v2.md` (unchanged).  
**Objective:** Add a minimal, end‑to‑end path to pilot a simple strategy — *Return‑to‑VWAP on elevated volume with optional SIP filter* — **without mutating the data lake**. All parquet scans/restructures remain deferred to the VM‑only Finalization Phase.

---

## 0) Scope & Constraints

- **No lake mutations.** Gold is read‑only. In‑run normalization is allowed **in memory** only for hashing and schema assertions.  
- **Legacy repos untouched.** `timegpt_v2` and `intraday_stack` must continue to run as-is.  
- **Determinism & validation.** All public boundaries validated by JSON Schema; identical inputs + config ⇒ identical outputs.  
- **Artifacts over side effects.** Backtest writes standardized artifacts under `runs/<run_id>` and experiment manifests under `experiments/<exp_id>`.

---

## 1) Dependencies & Inputs

- Sprint 1 complete (repo scaffolding).  
- Use a tiny **Gold** slice for smoke & pilot (e.g., `AAPL` January 2024). If needed, prepare a local sample via `check_gold_and_make_smoke_sample.py` (already provided).  
- Defer Bronze→Silver full scans and Silver normalization.

---

## 2) Sprint Breakdown

### Sprint 1.9 — Experiments CLI & Validators (from Plan v2)
**Goal:** Implement `qx-cli exp` command group and schema validators.  
**Deliverables:**
- `qx-cli exp` subcommands: `entry-ab`, `risk-grid`, `cost-sweep`, `wf`, `regime-slice`, `portfolio`, `compare`  
- Validators in `qx-core/schemas.py` for: `manifest`, `inputs_checksum`, `trades`, `risk_rejects`, `allocation_log`, `metrics`, `compare`  
**Tests:** unit + integration (synthetic dataset), golden replay.  
**Acceptance:** `python -m qx_cli exp --help` lists commands; `entry-ab` writes manifests, checksums, run artifacts; `compare` enforces fairness.

---

### Sprint 1.10 — Gold Loader v0 (Read‑Only, In‑Memory Normalization)
**Goal:** Minimal loader to read Gold bars into canonical schema and compute a **bars_norm_hash** from the in‑memory normalized DataFrame.  
**Deliverables:**
- `qx-data/gold_loader.py`: `load_bars(root, family, symbols, dates)` → canonical DF with columns `ts, symbol, open, high, low, close, volume` (+optional `vwap,trades`)  
- `qx-core/hashers.py`: `hash_dataframe(df, cols=...)` stable hashing for fairness  
**Tests:**  
- Loads 1–2 files and returns canonical dtypes; tz‑aware UTC `ts`; no high<low.  
- Hash is stable across runs and insensitive to file order.  
**Acceptance:** `bars_norm_hash` appears in `experiments/<exp_id>/inputs_checksum.json`.

---

### Sprint 1.11 — Feature Pack “core_basics” v0
**Goal:** Provide the minimum features for the pilot.  
**Features:**
- `f__ta__vwap_m`: rolling VWAP (configurable window minutes) if missing in Gold  
- `f__vol__rel_volume_m`: relative volume vs rolling mean  
- `f__vol__atr_m`: ATR for risk sizing  
**Deliverables:**  
- `qx-features/core_basics.py` with pure functions: `(df, **params) -> df_with_features`  
- Registry glue: `qx-features/registry.py` to compose feature packs  
**Tests:** deterministic outputs; proper warmup; feature column names follow `f__{pack}__{signal}`.  
**Acceptance:** Features added with correct types; warmup bars excluded from trading in the backtest.

---

### Sprint 1.12 — SIP Screener v0 (Optional Filter)
**Goal:** Minimal universe selector based on relative volume and optional whitelist.  
**Deliverables:**  
- `qx-screener/sip.py`: `screen(df, rvol_col, top_n=5, whitelist=None) -> {ts: [symbols]}`  
**Tests:** picks top‑N by RVOL per bar; respects whitelist.  
**Acceptance:** Experiment variant can toggle `sip_filter: on|off` and changes universe accordingly.

---

### Sprint 1.13 — Policy “vwap_revert” v0
**Goal:** Simple mean‑reversion policy: enter long when `close < vwap` **and** `rvol >= threshold`; exit at VWAP touch or end‑of‑session fallback.  
**Deliverables:**  
- `qx-backtest/policies/vwap_revert.py`: `generate_signals(df, params)` emitting long/flat signals with warmup respected  
- Entry condition: `close < vwap` and `f__vol__rel_volume_m >= rvol_min` and symbol in SIP universe (if enabled)  
- Exit rules: VWAP touch or stop from Risk module  
**Tests:** signal monotonicity around VWAP; no signals during warmup; SIP gating respected.  
**Acceptance:** Signals exist and are plausible over the sample window.

---

### Sprint 1.14 — Risk “atr_stop” & Sizing v0
**Goal:** ATR‑based stop, with max 2 % equity at risk.  
**Deliverables:**  
- `qx-risk/atr_stop.py`: qty sizing so `qty * ATR * atr_mult <= max_risk_frac * equity`; stop/target tagging  
**Tests:** edge cases for tiny ATR; notional limits; metadata appears in `risk_rejects.parquet` when sizing fails.  
**Acceptance:** Orders sized; rejects logged when caps breached.

---

### Sprint 1.15 — Backtest Engine v0 (Next‑Open Fill + Costs)
**Goal:** Minimal event loop to turn signals into orders, simulate fills at next open, apply costs, track positions & PnL.  
**Deliverables:**  
- `qx-backtest/engine.py` with hooks for policy, risk, portfolio  
- Cost model: bps + per‑share; Fill model: next_open with optional skid  
- Artifacts per run: `signals.parquet`, `orders.parquet`, `fills.parquet`, `positions.parquet`, `equity.parquet`, `trades.parquet`, `risk_rejects.parquet`, `allocation_log.parquet`, `metrics.json`  
**Tests:** identity fills on synthetic data; fees applied; equity equals cum PnL; required columns present.  
**Acceptance:** Full artifact set present and validated by `test_exp_artifacts.py`.

---

### Sprint 1.16 — Experiments: Pilot Setup
**Goal:** Wire an A/B experiment toggling SIP filter and thresholds.  
**Deliverables:**  
- Configs under `experiments/vwap_revert/`: `strategy.yaml`, `overlays/policy_*.yaml`, `overlays/sip_on.yaml`  
- `qx-cli exp entry-ab` integration to launch both variants  
**Tests:** manifests and checksums created; compare report produced; fairness enforced (matching checksums).  
**Acceptance:** `experiments/vwap_revert/compare.json|md` created with leaderboard and p‑values.

---

### Sprint 1.17 — Pilot Run & Report
**Goal:** Execute the pilot over a tiny date range and produce a human‑readable report.  
**Deliverables:**  
- Run over AAPL 2024‑01‑02 (or small window)  
- `experiments/vwap_revert/compare.md` with: trades count, Sharpe, ES@95, U‑test p‑value, summary table  
**Tests:** smoke assertions: ≥10 trades, no NaN PnL, report renders.  
**Acceptance:** All artifacts + compare report present; run reproducible with same seed and inputs.

---

## 3) Execution Order & Rough Timeline

1. **1.9** Experiments CLI & validators  
2. **1.10** Gold loader v0  
3. **1.11** Features “core_basics” v0  
4. **1.12** SIP screener v0  
5. **1.13** Policy “vwap_revert” v0  
6. **1.14** Risk “atr_stop” v0  
7. **1.15** Backtest engine v0  
8. **1.16** Experiments pilot configs  
9. **1.17** Pilot run & report

> If build pressure is high, Sprints **1.11–1.14** can be developed in parallel behind the schema contracts from **1.9–1.10**.

---

## 4) Acceptance Checklist (Pilot)

- [x] `python -m qx_cli exp --help` shows all commands  
- [x] `experiments/vwap_revert/manifest.json` and `inputs_checksum.json` exist  
- [x] `runs/<run_id>/trades.parquet` contains required columns; `metrics.json` contains extended keys  
- [x] `experiments/vwap_revert/compare.md|json` written; U‑test p‑value computed  
- [x] Re‑run with same seed reproduces identical artifacts/hashes

---

## 5) Guardrails & Non‑goals

- Do **not** scan or rewrite parquet lake files.  
- Do **not** modify legacy strategies or their inputs.  
- Keep feature functions pure and deterministic; enforce warmup.  
- Gold remains **additive‑only**; no resampling across sessions.

---

## 6) Runbook (Pilot Commands)

```bash
# 1) Verify CLI
python -m qx_cli exp --help

# 2) Point configs to Gold slice (AAPL Jan 2024); or use tiny sample under /tmp
# 3) Launch A/B pilot (SIP on vs off or thresholds)
python -m qx_cli exp entry-ab   --cfg experiments/vwap_revert/strategy.yaml   --variants experiments/vwap_revert/overlays/policy_*.yaml   --name vwap_revert_pilot

# 4) Validate artifacts
python tools/test_exp_artifacts.py --runs-root runs
```

---

## 7) Post‑Pilot

- Triage results; decide whether to expand universe, add session logic or introduce VPA/ICT overlays.  
- If stable, proceed toward Finalization Phase (VM) for parquet normalization and Gold validation across real partitions.
