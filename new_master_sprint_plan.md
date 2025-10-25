# New Master Sprint Plan (v3) — QuantStack E2E & Warehouse

**Status:** Master plan derived from the audit of `/home/jacobw/quantstack`.
**Scope:** Build a deterministic, modular research stack that can run a real VWAP pilot end-to-end on Gold data (read-only), support A/B experiments with fairness checks, and publish results to an LLM-queryable warehouse.
**Non-goals:** Live trading, broker connectivity, Bronze/Silver changes, or data lake mutations.

---

## 0. Operating Principles

* **Read-only lake:** never write under `/home/jacobw/gcs-mount`. All outputs go to `runs/`, `experiments/`, or `/tmp`.
* **Determinism:** UTC ns timestamps, stable sorting, fixed seeds. Identical inputs + config ⇒ identical outputs and checksums.
* **Contracts-first:** schemas and function signatures precede orchestration. All components validated by tests before use.
* **Fairness:** A/B comparisons require equal `bars_norm_hash`, `features_hash`, `sip_hash`, `config_hash`, `seed`.
* **Artifacts are truth:** reports read artifacts only; no re-derivation from the lake.

---

## 1. Architecture Wireframe (target)

**Data lake (read-only):** Gold bars in `/home/jacobw/gcs-mount/gold`
**Core libs:**

* `qx-core/` — `schemas.py`, `validators.py`, `hashers.py`, `utils.py`
* `qx-data/` — `gold_loader.py`
* `qx-features/` — `core_basics.py` (VWAP, RVOL, ATR), `registry.py`, `vpa.py` (later)
* `qx-screener/` — `sip.py`
* `qx-risk/` — `atr_stop.py`
* `qx-backtest/` — `engine.py`, `policies/vwap_revert.py`, `policies/ml_vpa.py` (later), `metrics.py`
* `qx_cli/exp/` — `entry_ab.py`, `cost_sweep.py`, `risk_grid.py`, `regime_slice.py`
* `qx-report/` — readers and summaries from artifacts

**Artifacts (output only):**
`runs/<run_id>/` → `signals.parquet`, `orders.parquet`, `fills.parquet`, `positions.parquet`, `equity.parquet`, `trades.parquet`, `risk_rejects.parquet`, `allocation_log.parquet`, `metrics.json`
`experiments/<exp_id>/` → `manifest.json`, `inputs_checksum.json`, `compare.{json,md}`

**LLM warehouse (separate repo):** `~/strategy_repo/` with catalog (Parquet facts/dims), DuckDB `warehouse.db`, views, ingestor, MCP server.

---

## 2. Deliverables Matrix (what “done” means)

| Area           | Deliverables                                                       |
| -------------- | ------------------------------------------------------------------ |
| Core contracts | `schemas.py`, `validators.py`, `hashers.py` with tests             |
| Loader         | `gold_loader.load_bars()` canonical bars, tests                    |
| Features       | VWAP, RVOL, ATR + registry + warmup mask                           |
| Screener       | SIP top-N by RVOL, deterministic ties                              |
| Risk           | ATR sizing, `stop_dist_ps` persisted                               |
| Engine         | Signals→orders→fills→positions→trades; costs & slippage; artifacts |
| CLI            | `entry_ab.py` orchestration; real `inputs_checksum.json`; compare  |
| Reporting      | Minimal summaries from artifacts (no lake)                         |
| Pilot          | VWAP A/B on small Gold slice; non-empty trades; variant separation |
| Warehouse      | Ingestor, facts/dims, views, read-only MCP tools                   |

---

## 3. Sprints Overview

1. **S0** Repo hygiene & env
2. **S1** Core schemas & hashing (qx-core)
3. **S2** Gold loader (qx-data)
4. **S3** Baseline features & registry
5. **S4** SIP screener
6. **S5** Risk sizing (ATR)
7. **S6** Backtest engine + artifacts
8. **S7** CLI orchestration + fairness checksums
9. **S8** Reporting minimal
10. **S9** VWAP pilot acceptance (A/B, Gold read-only)
11. **S10** VPA pack + ML dataset/trainer scaffold (optional enable)
12. **S11** Warehouse: ingestor, views, MCP server
13. **S12** CI, reproducibility, docs & governance

Each sprint below includes Objective, Design notes, Tasks, Tests, Acceptance, and a **Claude Code run-block**.

---

## S0 — Repo Hygiene & Environment

**Objective:** Create a stable Python env and repo scaffolding; enforce lint/test harness.

**Tasks**

* Create `.venv`, `pyproject.toml` with dependencies (pandas, numpy, pyarrow, polars optional, duckdb for tests, pydantic, pytest).
* Add `pre-commit` with black/isort/flake8.
* Create `tests/` with placeholder structure.

**Tests**

* `pytest -q` runs and passes trivial sanity tests.

**Acceptance**

* `python -V`, `pip list` saved to `docs/DEV_ENV.md`.
* Pre-commit hooks installed.

**Claude Code: run-block**

```
cd /home/jacobw/quantstack
python -m venv .venv && source .venv/bin/activate
printf '%s\n' "[tool.black]" > pyproject.toml  # fill full config; add deps
pip install -U pip setuptools wheel
pip install pandas pyarrow numpy pydantic pytest duckdb
pre-commit install || true
pytest -q
```

---

## S1 — Core Schemas & Hashing (qx-core)

**Objective:** Define data contracts and deterministic hashing.

**Design**

* `schemas.py` pydantic/dataclasses for Bars, Signals, Orders, Fills, Positions, Trades, Metrics, InputsChecksum.
* `hashers.py::hash_dataframe(df, cols=None, index=False, algo='blake2b')`:

  * Cast dtypes stable, tz→UTC ns, sort `[symbol, ts]`, serialize, hash.

**Tasks**

* Implement `schemas.py`, `validators.py`, `hashers.py`.
* Unit tests for hashing stability and schema validation.

**Tests**

* Shuffle/concat frames → identical hash.
* UTC norm test.
* Validator raises on missing columns.

**Acceptance**

* `tests/test_core_*` all pass.

**Claude Code: run-block**

```
# Implement qx-core; then:
pytest -q tests/test_core_*
```

---

## S2 — Gold Loader (qx-data)

**Objective:** Canonical bars from Gold without lake writes.

**Design**

* `gold_loader.load_bars(root, family, symbols, dates) -> DataFrame`
* Columns: `ts[UTC ns], symbol, open, high, low, close, volume, (opt) vwap, trades`
* Sort `[symbol, ts]`.

**Tasks**

* Implement loader with minimal partition reading.
* Add schema validation.

**Tests**

* Loads a known tiny partition; shape/columns correct; sorted.

**Acceptance**

* Unit tests pass; no writes under `/home/jacobw/gcs-mount`.

**Claude Code: run-block**

```
pytest -q tests/test_data_gold_loader.py
```

---

## S3 — Baseline Features & Registry (qx-features)

**Objective:** Deterministic VWAP, RVOL, ATR with warmup gating.

**Design**

* `core_basics.py`: `vwap_m(df, m)`, `rel_volume_m(df, m)`, `atr_m(df, m)`
* `registry.py::apply(df, packs, params) -> (df, warmup_mask)`
* Naming: `f__ta__vwap_{m}`, `f__vol__rel_volume_{m}`, `f__vol__atr_{m}`

**Tasks**

* Implement features and registry.
* Warmup computation and mask return.

**Tests**

* Exact column names and types; warmup gating correct.

**Acceptance**

* Feature unit tests pass.

**Claude Code: run-block**

```
pytest -q tests/test_features_*
```

---

## S4 — SIP Screener (qx-screener)

**Objective:** Deterministic top-N RVOL universe per bar.

**Design**

* `sip.py::screen(df, rvol_col, top_n=5, whitelist=None) -> dict[ts->set(symbol)]`
* Ties broken by symbol ascending.

**Tasks**

* Implement screener + tests with ties.

**Tests**

* Correct selection per ts; deterministic tie breaks.

**Acceptance**

* Screener tests pass.

**Claude Code: run-block**

```
pytest -q tests/test_screener_sip.py
```

---

## S5 — Risk Sizing (qx-risk)

**Objective:** ATR-based stop distance and sizing.

**Design**

* `atr_stop.py::size_orders(signals, bars, params, equity) -> (orders_df, rejects_df)`
* Ensure `qty * atr * atr_mult ≤ max_risk_frac * equity`
* Persist `stop_dist_ps = atr * atr_mult`

**Tasks**

* Implement sizing and rejects.

**Tests**

* Sizing math; rejects logged; `stop_dist_ps` present.

**Acceptance**

* Risk tests pass.

**Claude Code: run-block**

```
pytest -q tests/test_risk_atr.py
```

---

## S6 — Backtest Engine + Artifacts (qx-backtest)

**Objective:** Convert signals to trades with costs/slippage and write artifacts.

**Design**

* `engine.py::run(bars, orders, cfg) -> artifacts`
* Next-open fills; apply `bps`, `per_share`, `slippage_ticks` (tick_size from cfg).
* Emit parquet: signals, orders, fills, positions, equity, trades, risk_rejects, allocation_log; plus `metrics.json`

**Tasks**

* Implement engine and artifact writers.
* Add `metrics.py` for simple metrics (trades count, avg_R, fees_total).

**Tests**

* Integration test on synthetic data produces non-empty trades; costs applied.

**Acceptance**

* Engine tests pass; artifacts present with required columns incl `stop_dist_ps`,`fees`,`slippage_est`,`r_multiple`.

**Claude Code: run-block**

```
pytest -q tests/test_engine_integration.py
```

---

## S7 — CLI Orchestration & Fairness (qx_cli)

**Objective:** Real A/B driver that wires the pipeline and writes true `inputs_checksum.json`.

**Design**

* `entry_ab.py` pipeline:

  1. load_bars → 2) features → 3) SIP → 4) policy.generate_signals → 5) risk.size_orders → 6) engine.run
* Compute hashes: `bars_norm_hash`, `features_hash`, `sip_hash`, `config_hash`, `seed`
* Write `experiments/<exp_id>/manifest.json` and `inputs_checksum.json`
* Compare refuses if fairness keys differ (unless `--force`)

**Tasks**

* Implement `entry_ab.py`, manifest writer, checksum writer, console summary.

**Tests**

* Dry run `python -m qx_cli exp --help`
* Local A/B on synthetic data yields different trades across variants; equal checksums.

**Acceptance**

* CLI help works; checksum written; A/B produces non-identical behavior.

**Claude Code: run-block**

```
python -m qx_cli exp --help
python -m qx_cli exp entry-ab --cfg experiments/vwap_revert/strategy.yaml --variants experiments/vwap_revert/overlays/policy_*.yaml --name vwap_audit_smoke
```

---

## S8 — Reporting Minimal (qx-report)

**Objective:** Summaries from artifacts.

**Design**

* Functions to read `runs/<run_id>` and compute small tables: per-run metrics, A/B diff tables.

**Tasks**

* Implement minimal report reader.

**Tests**

* On synthetic artifacts, summary values match `metrics.json`.

**Acceptance**

* `qx-report` imports; CLI optional.

**Claude Code: run-block**

```
python - <<'PY'\nimport qx_report as r; print('ok')\nPY
```

---

## S9 — VWAP Pilot Acceptance (Gold read-only)

**Objective:** Prove an end-to-end VWAP A/B on small Gold slice with fair inputs.

**Tasks**

* Use `tools/check_gold_and_make_smoke_sample.py` to copy 1–2 files to `/tmp/e2e_smoke_from_gold` (read-only in).
* Point experiment config to `/tmp/e2e_smoke_from_gold`.
* Run two variants: `rvol_min=1.0` vs `1.5`, SIP on with `top_n=5`.

**Tests**

* `runs/*/trades.parquet` non-empty.
* Variant separation: different trade counts or median R.
* `inputs_checksum.json` equal across variants; equal on re-run.

**Acceptance**

* Pilot “PASS” recorded in `experiments/<exp_id>/compare.md`.

**Claude Code: run-block**

```
python tools/check_gold_and_make_smoke_sample.py --gold-root /home/jacobw/gcs-mount/gold --family bars_1m --symbol AAPL --year 2024 --month 01 --n-files 2 --write-sample --out-dir /tmp/e2e_smoke_from_gold
python -m qx_cli exp entry-ab --cfg experiments/vwap_revert/strategy.yaml --variants experiments/vwap_revert/overlays/policy_*.yaml --name vwap_pilot_e2e
```

---

## S10 — VPA Pack + ML Dataset/Trainer Scaffold (optional enable)

**Objective:** Prepare components to test VPA patterns and ML without affecting VWAP pilot.

**Tasks**

* `qx-features/vpa.py`: 5 pattern flags `p__vpa__*` and optional `conf__vpa__*`.
* Dataset builder: materialize `experiments/<exp_id>/datasets/{train,valid,oos}.parquet` + manifest.
* Trainer stub: read dataset, fit simple classifier, write `model.pkl`, `model_manifest.json`.
* `policies/ml_vpa.py`: load model, infer, threshold decision.

**Tests**

* Dataset manifests and hashes present; trainer outputs consistent `model_hash`.

**Acceptance**

* Disabled by default; toggled via experiment overlays.

---

## S11 — LLM Warehouse (strategy_repo)

**Objective:** Ingest runs/experiments into a queryable warehouse with read-only LLM access.

**Tasks**

* Create `~/strategy_repo` structure with `catalog/` Parquet facts/dims, `warehouse.db`, `ingestors/ingest_runs.py`, `views/mv_*`, `llm/mcp_server.py`.
* Ingest a handful of runs and build views: `mv_runs_wide`, `mv_vpa_leaderboard`, `mv_sip_effects`, `mv_repro_checks`.

**Tests**

* DuckDB returns rows from `mv_runs_wide`; MCP `get_schema` and `sql` read-only calls succeed.

**Acceptance**

* Warehouse skeleton functional on sample.

---

## S12 — CI, Reproducibility, Docs & Governance

**Objective:** Lock reproducibility and document the system.

**Tasks**

* Add GitHub Actions (or local CI runner) for `pytest -q`, style, and a mini smoke.
* Golden tests: re-run same config and assert identical `inputs_checksum.json`.
* Docs: `docs/SCHEMAS.md`, `docs/E2E_SMOKE_TEST.md`, `docs/EXPERIMENTS.md`, `docs/GOVERNANCE.md`.

**Acceptance**

* CI green; docs present.

---

## 4. Signatures and Interfaces (authoritative)

* **`hashers.hash_dataframe(df, cols=None, index=False, algo='blake2b') -> str`**
  Normalize and hash the exact view used downstream.

* **`gold_loader.load_bars(root, family, symbols, dates) -> DataFrame`**
  Columns: `ts:int64(UTC ns)`, `symbol:str`, `open:float64`, `high:float64`, `low:float64`, `close:float64`, `volume:int64`, optional `vwap:float64`, `trades:int64`.

* **`registry.apply(df, packs, params) -> (df_with_features, warmup_mask:Series[bool])`**

* **`sip.screen(df, rvol_col, top_n=5, whitelist=None) -> dict[int,set[str]]`**

* **`policies.vwap_revert.generate_signals(df, params, universe_map, warmup_mask) -> DataFrame[signals]`**
  Must include `decision_trace` JSON for first N rows.

* **`atr_stop.size_orders(signals, bars, params, equity) -> (orders_df, rejects_df)`**
  Must set `stop_dist_ps`.

* **`engine.run(bars, orders, cfg) -> artifacts`**
  Writes full artifact suite and `metrics.json`.

* **`entry_ab.main(...)`**
  Writes `manifest.json` and real `inputs_checksum.json` with keys: `bars_norm_hash`, `features_hash`, `sip_hash`, `config_hash`, `seed`.

---

## 5. Tests & Acceptance Summary

* **Unit:** core hashing; loader IO; feature correctness; screener tie breaks; risk math.
* **Integration:** engine artifacts; CLI A/B wiring; checksums; repeatability.
* **Pilot E2E:** non-empty trades, variant separation, equal checksums across variants and re-runs.
* **Warehouse:** ingestor populates facts/dims; views return; MCP read-only works.

---

## 6. Implementation Prompts (Claude Code etiquette)

For each sprint:

1. **Implement:** file list and functions exactly as specified.
2. **Run:** provided run-block commands.
3. **Return:** paths created, test results, and a brief summary including any failures with stack traces.
4. **Do not** modify `/home/jacobw/gcs-mount` or existing legacy repos.

---

## 7. Back-out & Fallback

* If any sprint fails tests, stop and return:

  * failing test names
  * stack traces
  * suggested patch list with file paths
* Do not proceed to the next sprint until acceptance criteria met.

---

## 8. Post-Pilot Roadmap (not in scope of this plan)

* Portfolio allocator and multi-asset/multi-policy routing
* Broker interface beyond placeholder
* Full regime detection library
* Advanced slippage/impact models

---

## 9. Appendix: Minimal Pilot Config Hints

* **Policy overlay A:** `rvol_min: 1.0`, `vwap_lookback_m: 10`, `sip.top_n: 5`
* **Policy overlay B:** `rvol_min: 1.5`, `vwap_lookback_m: 10`, `sip.top_n: 5`
* **Risk:** `max_risk_frac: 0.02`, `atr_mult: 2.0`
* **Costs:** set bps and per-share such that `fees` are non-zero in trades.

---

### End of Plan

Execute sprints in order. This plan is the single source of truth for the build.
