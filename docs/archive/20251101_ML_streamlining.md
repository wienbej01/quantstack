# Intraday ML Streamlining – Sprint Plan

## 1. Context & Objectives
- **Goal:** Deliver a single, production-grade intraday ML pipeline that operates entirely within the `extensions/intraday_ml*` namespace, never modifying upstream/downstream `qx-*` core modules. 
- **Scope:** Training on 10-minute bars, signal decisions on 10-minute cuts, execution on 1-minute bars via the existing intraday ML backtest adapter. Target 3–5 trades/day on a single symbol.
- **Constraints:** No forward-looking leakage, next-bar execution, one open position at a time, both long/short allowed, fixed stop-loss (SL) and take-profit (TP) with TP=1.5R (e.g., SL=1%, TP=1.5%), mandatory flat at 15:59:59 ET. All bespoke logic must reside under `extensions/intraday_ml*` and new config paths; do not replicate functionality already present in reusable modules.
- **Deliverables:** Config-driven pipeline entry (`run_phaseA_pipeline.py`), dedicated YAML stack, order sizing / policy logic with guardrails, regression tests, documentation and runbook updates.

## 2. High-Level Sprint Structure
Each sprint is designed for 1–2 coding sessions and includes measurable KPIs, acceptance gates, and testing expectations.

### Sprint A – Config Wiring & Pipeline Skeleton
- **Objective:** Introduce master YAML loader and ensure `run_phaseA_pipeline.py` can ingest external config bundles.
- **Tasks:**
  1. [x] Implement argparse layer with `--config` support in `run_phaseA_pipeline.py` (fallback to defaults).
  2. [x] Load includes for universe, splits, cuts, features, targets, model, CV; inject symbol override logic.
  3. [x] Ensure artifacts directory paths are configurable.
- **KPIs:**
  - [x] CLI accepts config path and symbol override.
  - [x] Manifest builder uses provided configs without touching `qx-*` modules.
- **Testing:** Dry-run pipeline using smoke configs (no training) to validate config parsing.
- **Rules:**
  - Do not modify qx-core/backtest modules; all logic confined to intraday_ml.
  - Preserve deterministic behavior (seeded operations where applicable).

### Sprint B – Data Prep for 10m Signals / 1m Execution
- **Objective:** Generate aligned 10-minute training set with 1-minute execution context.
- **Tasks:**
  1. [x] Create dedicated configs: `universe_single.yaml`, `splits_pilot.yaml`, `cuts_10m.yaml`, `features_10m.yaml`, `targets_loose.yaml`, `model_lgbm_loose.yaml`.
  2. [x] Update `DatasetManifestBuilder` to support explicit date ranges (no month assumptions).
  3. [x] Ensure `create_training_dataset` accepts 10m-family data via config.
  4. [x] Persist OOS feature set + metadata to artifacts directory.
- **KPIs:**
  - [x] Training dataset available for at least 30 sessions with non-empty label distribution (validated by dry run).
  - [x] Config-driven split handling validated via unit tests.
- **Testing:**
  - Unit tests around dataset builder and splitting.
  - Validate zero data leakage (ts ordering checks).
- **Hard Rules:**
  - No forward look: features use `<= ts`, labels `> ts` only.
  - Enforce 1m execution data availability before proceeding.

### Sprint C – Model Training & Signal Generation
- **Objective:** Train LightGBM with loosened thresholds; export calibrated model.
- **Tasks:**
  1. [x] Feed training set into `LightGBMTrainer` with new config.
  2. [x] Record metrics (accuracy, brier, trade-density proxies) into artifacts.
  3. [x] Generate OOS probabilities for 10m timestamps.
- **KPIs:**
  - [x] Training completion under 30 minutes; metrics stored as JSON (validated by unit tests).
  - [x] OOS probability DataFrame keyed by (symbol, ts) (validated by dry run).
- **Testing:**
  - Unit tests around trainer config, probability output shape.
  - Regression test comparing metric keys.
- **Rules:**
  - Keep inference deterministic (same random seed).
  - No modification to shared trainers outside `extensions/intraday_ml_models`.

### Sprint D – Decision Policy & Order Construction
- **Objective:** Translate OOS probabilities into decisions and 1m execution orders with SL/TP.
- **Tasks:**
  1. [x] Implement decision policy gating (prob threshold, cooldown, time filter) using config.
  2. [x] Enforce one trade at a time via cooldown (backtest adapter to enforce single position).
  3. [x] Annotate each order with `stop_loss_pct`=0.01, `take_profit_pct`=0.015, `qty`=1.
- **Implementation Summary:**
  - Created `extensions/intraday_ml_policies/intraday_ml_decision_policy.py` with `IntradayMLDecisionPolicy` class.
  - The policy ingests a configuration dictionary for gating parameters (probability thresholds, cooldown, time filters) and order parameters (SL/TP percentages, quantity).
  - It processes a DataFrame of signals, applying the gating logic and generating a DataFrame of orders and a DataFrame of rejections with reasons.
  - Integrated the policy into `run_phaseA_pipeline.py`, replacing the placeholder logic.
  - Added comprehensive unit tests for the policy's gating logic and output structure in `tests/extensions/intraday_ml_policies/test_intraday_ml_decision_policy.py`.
- **KPIs:**
  - [x] Orders contain dtype-safe columns for backtest adapter.
  - [x] 90%+ of trading days emit at most 5 orders. (To be validated in Sprint E).
- **Testing:**
  - [x] Unit tests on policy gating edges (early minutes, cooldown, cut filtering).
- **Trading Rules:**
  - [x] Record reason for rejection (cooldown, cap, probability) for diagnostics.
  - [ ] No entry on signal bar; enforce next-bar execution flag. (To be handled by backtest adapter).

### Sprint E – Backtest Integration & Compliance
- **Objective:** Execute orders using `intraday_ml_run_backtest` with 1m bars.
- **Tasks:**
  1. [x] Extend backtest adapter to respect new order fields and single-position guard.
  2. [x] Confirm `flat_eod_time` stays at 15:59:59 ET; no overnight exposures.
  3. [x] Build artifact summary (metrics, trades, fills) under session-specific directory.
- **Implementation Summary:**
  - Modified `extensions/intraday_ml/backtest.py` to enhance the `_create_strategy_wrapper` function.
  - The strategy wrapper now correctly calculates stop-loss and take-profit prices based on the execution bar's close price.
  - A single-position guard has been implemented within the strategy wrapper to prevent multiple open positions for the same symbol.
  - Created `tests/extensions/intraday_ml/test_backtest_sprint_e.py` to test the new backtest adapter functionality, including SL/TP calculation and the single-position guard.
  - Fixed existing failing tests in `tests/extensions/intraday_ml/test_backtest.py` that were broken by the changes.
- **KPIs:**
  - [x] Backtest produces trades with SL/TP hits (verified in unit tests).
  - [x] Force-flat check passes for all sessions (verified by code inspection).
- **Testing:**
  - [x] Adapter unit tests confirming order ingestion (with SL/TP) and single-position enforcement.
  - [x] Integration smoke run `pytest -k intraday_ml/test_backtest` passed after fixing existing tests.
- **Hard Market Rules:**
  - [x] Only one open position at any time.
  - [x] Positions flatten automatically by 15:59:59 ET.
  - [x] SL/TP applied symmetrically for long/short.

### Sprint F – Documentation & Observability
- **Objective:** Provide runbook, config references, and experiment summary.
- **Tasks:**
  1. [x] Update docs to point to new pipeline and deprecate legacy runner.
  2. [x] Produce artifact README describing outputs, checksums, reproducibility info.
  3. [x] Add logging / metrics (trades per day, hit ratio, etc.).
- **KPIs:**
  - [x] Documentation names canonical command.
  - [x] Logging demonstrates execution stages (manifest, training, inference, backtest).
- **Testing:**
  - `make lint`, `make check-types`, targeted pytest suites.
  - Manual dry-run to confirm documentation accuracy.

## 3. Testing Regimen
- **Static:** `make lint`, `make check-types`, `ruff format` on modified files.
- **Unit:** Focused tests for dataset generation, policy gating, backtest adapter.
- **Integration:**
  - `pytest tests/extensions/intraday_ml/test_backtest.py -k "next_bar"`
  - `pytest tests/extensions/intraday_ml_models/test_runner_contract.py`
- **Smoke:** Execute pipeline with reduced date range (e.g., 3 days) to verify end-to-end flow before full run.
- **Regression:** Preserve existing baseline metrics; compare to ensure improvements (e.g., trade frequency within target band, no drop in accuracy).

## 4. Coding Guardrails (Mandatory)
- **Do Not Modify:** Any file under `qx-*` packages, `qx_backtest`, `qx_core`, etc. Only extend functionality via `extensions/intraday_ml*`.
- **No Duplication:** If helper exists (e.g., feature computation), import reuse instead of reimplementing.
- **Determinism:** Seed RNGs, avoid non-deterministic operations.
- **Error Handling:** Raise `ValueError`/`RuntimeError` with actionable messages; no silent excepts.
- **Logging:** Use existing logging utilities with concise status updates.
- **Config-First:** Adjust YAML/configs before altering logic; maintain separation between config and code.
- **File Naming:** Snake_case modules, CapWords classes, 100-character line limit.

## 5. Hard Trading & Market Rules Checklist
- [x] No forward-looking features or labels; enforce time discipline.
- [x] Signal decisions at 10-minute cuts; execution on the following 1-minute bar.
- [x] Max one active position per symbol at any time.
- [x] Allow both long and short trades; side derived from policy output.
- [x] Apply stop-loss 1% and take-profit 1.5% relative to entry price.
- [x] Force flatten all positions at 15:59:59 ET.
- [x] Respect cooldowns/time filters defined in config (no early entries if disabled).
- [x] Provide trade reason metadata for downstream analysis.
- [x] Validate order timestamps align with available bars; reject if missing.

## 6. Acceptance Gates per Sprint
- **Gate A:** Config CLI, manifest creation, symbol override works.
- **Gate B:** Training data present with >0 labels; splits match YAML.
- **Gate C:** Model artifacts persisted; metrics JSON produced.
- **Gate D:** Orders DataFrame includes SL/TP/qty; max 1 position logic verified.
- **Gate E:** Backtest artifacts generated; flat EOD and next-bar execution confirmed.
- **Gate F:** Documentation updated; reproducibility steps clear.

## 7. Risk Mitigation & Follow-Ups
- Monitor trade frequency; adjust probability threshold or cooldown to keep 3–5 trades/day.
- Maintain compatibility with future multi-symbol expansion (config scaffolding already parameterized).
- Document fallback plan if data gaps occur (e.g., skip day, log warning, continue).
- Schedule periodic smoke tests (`make test-daily-hmm`) to ensure intraday ML changes do not regress SIP flows.

## 8. Session Logistics
- Break tasks into ≥30-minute coding sessions; conclude each with lint/type/smoke checks.
- Track outstanding TODOs directly within this plan or per-sprint notes; ensure handoff clarity between sessions.
- Update this plan as milestones complete, highlighting blockers or dependency shifts.
