# Quantstack Intraday SIP + PnL Enhancement Plan

## 1. Objectives

- **Finish the SIP integration sprint (`quantstack_intraday_sip_sprint_plan.md`)** so that daily SIP selections drive dynamic training/backtest symbol lists without regressing legacy behavior.
- **Layer a PnL‑first optimization program** (three sprints) on top of the SIP-enabled pipeline to achieve 3–5 profitable, high-conviction trades per day, measured by risk-adjusted returns rather than classification metrics.
- Keep the implementation **modular and configuration-driven** so daily SIP outputs can be injected without code changes.
- you are **prohibited** from creating or using mock/synth/dummy data outside function testing. Any mock/synth/dummy data generation or usage code must be removed after completion of the test.
- youare **prohibited** from introducing any forward-look bias or data leakage. this is a **real-life** trade system that must follow market reality
## 2. Current Status Snapshot

| SIP Plan Step | Status | Notes |
| --- | --- | --- |
| 0. Git hygiene | ✅ | Dedicated feature branch exists. |
| 1–2. SIP discovery & membership I/O layer | ✅ | `HMMSIPUniverseSelector` documented; `extensions/intraday_ml/sip_membership.py` implemented. |
| 3. CLI to precompute SIP membership | ✅ | CLI produces parquet partitions per trade date. |
| 4. Config updates | ✅ | `sip_filter` block available in Phase-A configs. |
| 5–6. Pipeline & data-prep integration | ✅ | `run_phaseA_pipeline.py` retrieves SIP-filtered universes dynamically; non-SIP path unchanged. |
| 7. Tests & validation | ⚠️ **Partial** | Membership I/O tests exist, but helper tests/smoke config/regression coverage still pending. |
| 8. Wrap-up (tooling, docs, QA) | ⏳ **Pending** | Need final lint/test pass, runbook updates, and SIP-enabled smoke instructions. |

The new PnL-first enhancement plan must build on this SIP foundation while ensuring unfinished Step 7–8 work is completed first.

## 3. Workstream A – Complete SIP Integration (Steps 7 & 8)

### Step 7: Tests & Validation (finish partially completed items)

1. **Extend SIP membership tests**
   - Cover overwrite/idempotency when re-saving overlapping trade dates.
   - Validate error messaging when partitions are missing for requested ranges.
2. **Unit tests for `get_phase_symbols_with_sip`**
   - Mock `splits_config`, `sip_filter`, and temporary parquet partitions.
   - Cases: `sip_only`, `no_sip`, `all`, and `enabled=False` (legacy path).
3. **SIP-enabled smoke config**
   - Add `configs/extensions/intraday_ml/phaseA_sip_smoke.yaml` (tiny universe, short date range).
   - Document prerequisite CLI commands to generate matching SIP partitions.
4. **Regression guardrails**
   - Add/extend tests to assert symbol counts remain unchanged when SIP is disabled.
   - Log symbol counts per phase when SIP is enabled to aid debugging.

_Exit criteria_: automated tests cover SIP I/O + selector helper, smoke config parses, and legacy behavior tests pass.

### Step 8: Wrap-up & QA

1. **Toolchain pass**: `make format`, `make lint`, `make check-types`, targeted `pytest`.
2. **Runbook updates**
   - Document SIP CLI usage, data locations, expected runtime, and failure handling.
   - Update Phase-A pipeline instructions to show how to toggle SIP modes per day.
3. **Final verification checklist**
   - Record `git status`; ensure only expected files touched.
   - Provide commit/push guidance and sample commands for reproducing SIP-enabled runs.

_Exit criteria_: SIP plan fully complete, with documented workflows and green CI.

## 4. Workstream B – PnL-First Model Enhancement (Three Sprints)

These sprints assume Workstream A is done so the SIP-filtered universes are reliable inputs.

### Sprint 1 – Instrument Trading Performance

1. **Dataset instrumentation**
   - Rebuild train/test/OOS sets (with OHLCV) for SIP-filtered cohorts.
   - Publish daily label distributions (global + per symbol) to quantify ±1 sparsity.
2. **Prediction loader & scoring**
   - Standardize `trade_prob`, `trade_direction`, `edge_margin`, and `trade_score` extraction from model outputs.
   - Ensure these utilities accept dynamic symbol lists from SIP each day.
3. **Evaluation module**
   - Implement `extensions/intraday_ml/eval/eval_trading_performance.py` with:
     - Top‑K-per-day and probability-threshold policies.
     - Realized returns aligned with target horizons, including transaction costs.
     - Outputs: per-trade stats, daily PnL, Sharpe, Sortino, drawdown; JSON/CSV artifacts.
4. **Acceptance criteria**
   - Evaluation script runs on both SIP-enabled and legacy configs.
   - Reports highlight where current pipeline fails to meet 3–5 profitable trades/day.

### Sprint 2 – Redefine Labels & Model for Big-Move Profitability

1. **Targets**
   - Introduce `configs/extensions/intraday_ml/targets_bigmove.yaml` (higher ATR multipliers, session-aware constraints).
   - Confirm ±1 sample counts remain trainable per SIP-filtered cohort.
2. **Model adjustments**
   - Update `model_lgbm.yaml` with explicit class weights, deeper regularization, and reproducibility seeds.
   - Retrain LightGBM on big-move labels; store artifacts separately for A/B comparison.
3. **Policy recalibration**
   - Recompute policy calibration statistics per SIP cohort using Sprint 1 evaluator.
4. **Evaluation**
   - Re-run trading evaluator on validation month first, then on OOS once validation Sharpe/Sortino improve.
   - Compare old vs new configs strictly on PnL metrics; retain diagnostics only for sanity checks.

_Exit criteria_: big-move model shows higher risk-adjusted returns (Sharpe/Sortino) on validation data without catastrophic drawdowns; documentation updated.

### Sprint 3 – Robustness & PnL-Guided Tuning

1. **CV hardening**
   - Ensure `cv_runner` enforces purge/embargo per `configs/extensions/intraday_ml/cv/phaseA.yaml`.
   - Log trading metrics per fold using the evaluator to prevent silent regressions.
2. **Joint grid search**
   - Explore a constrained grid over LightGBM hyperparameters, class weights, and policy thresholds (including daily top-K caps).
   - Optimize for validation Sharpe/Sortino subject to drawdown constraints, not logloss.
3. **Finalization**
   - Lock in model/policy pair with best validation PnL metrics.
   - Run untouched OOS month with SIP-selected deployment symbols; publish final PnL/Sharpe/Sortino/drawdown plus trade frequency.
4. **Reporting**
   - Produce a concise report plus artifact links (evaluation JSON, plots).
   - Update `docs/extensions/intraday_ml_models/BACKTEST_RUNBOOK.md` with the PnL-first workflow.

_Exit criteria_: reproducible validation process tied to risk-adjusted metrics, final OOS sign-off, and updated runbooks.

## 5. Integrated Timeline & Dependencies

1. **Week 0**: Finish SIP Steps 7–8 (tests, smoke config, docs).
2. **Week 1**: Sprint 1 (instrumentation + evaluator). Depends on SIP data availability.
3. **Week 2**: Sprint 2 (new labels/model/policy). Requires Sprint 1 evaluator.
4. **Week 3**: Sprint 3 (robust tuning + final OOS). Requires stable Sprint 2 artifacts.

Parallelization guidance:
- SIP CLI can run daily in parallel with Sprint 1 once Step 7 tests land.
- Documentation/runbook updates should be finalized at the end of each sprint.

## 6. Acceptance & Reporting Checklist

- **SIP integration**: Passing tests, smoke config documented, users can toggle SIP modes per run.
- **Evaluator**: Generates daily PnL JSON/CSV, supports SIP-filtered universes, and enforces no look-ahead.
- **Big-move model**: Separate configs/artifacts; validation reports focus on PnL metrics.
- **Tuning & reporting**: Grid-search scripts log trading metrics; final OOS report summarizes trade frequency, PnL, Sharpe, Sortino, and max drawdown.
- **Documentation**: SIP runbook + PnL-first workflow appended to `docs/extensions/intraday_ml_models/BACKTEST_RUNBOOK.md`.

Once every checkbox above is satisfied, the SIP plan and the three PnL-focused sprints are considered complete and integrated. Continuous daily SIP filtering, dynamic training cohorts, and PnL-first evaluation will then be part of the standard intraday ML process.

