# Sprint Plan: SIP Phase-A Model Enhancement v2

## Context
- Current SIP-enabled Phase-A pipeline (config: `configs/extensions/intraday_ml/phaseA_sip_full.yaml`) produced only 3 trades (all JNJ, all losers) for 2024-05 OOS despite 10-name SIP deployment list.
- OOS probabilities collapse toward neutral (`prob_long` median ~0.007), so policy thresholds (0.55 prob, 0.05 gap) almost never trigger; 7,915/8,574 decisions rejected for `gap_insufficient`.
- Risk controls use fixed ±1%/1.5% levels instead of ATR/support-based stops, so trades do not satisfy ≥1.5 R payoff mandate.
- Goal: deliver 3–5 trades/day, ≥60 % win rate, ≥1.5 R expected payoff, with stops/targets set at entry using market structure or ATR, while preserving SIP discipline and zero leakage.

## Hard Rules
1. **Scope containment**: Only touch files under `extensions/intraday_ml*`, `configs/extensions/intraday_ml*`, `docs/extensions`, and artefact templates. Do **not** modify other modules (backtest, broker, etc.) without explicit user approval.
2. **Data integrity**: No forward-look bias or label leakage. All features must use data available at or before decision timestamp. Label definitions must respect the configured horizons and guard bands.
3. **No synthetic data**: Do not fabricate mock/synthetic datasets outside unit tests. Any temporary fixtures must be removed post-test.
4. **Deterministic outputs**: Keep stochastic processes seeded. Follow existing `Makefile` targets (`make format`, `make lint`, `make check-types`, focused `pytest`).
5. **Policy discipline**: Stops and profit targets must be set at order creation and remain fixed; they must be derived from observable market factors (ATR, support/resistance) and enforce ≥1.5 R expected payoff.
6. **Logging/diagnostics**: Any new logging must avoid leaking future data and must be optional/config-driven.

## Objectives
1. **Model confidence uplift**: Re-label training data for high-move events (≥1.5 R) and retrain LightGBM with imbalance-aware settings so OOS probabilities for true positives exceed policy gates.
2. **Policy calibration**: Auto-tune probability, gap, and score thresholds per split so ~0.5–1.0 % of signals fire, yielding ~3–5 trades/day across SIP names.
3. **Risk/Reward enforcement**: Replace fixed % stops/targets with ATR/support-derived levels that guarantee ≥1.5 R before order submission.
4. **Diagnostics**: Enrich rejection logging with probability, gap, ATR, and expected-R fields for post-run analysis.

## Workstreams & Tasks
### WS1 – High-Move Labeling & Training
- Update `configs/extensions/intraday_ml/targets_bigmove.yaml` to encode 1.5 R move requirements (e.g., ATR-multiple thresholds, session-aware horizons).
- Modify feature/label builder (`extensions/intraday_ml/data_prep.py` and related helpers) to honor new target config without leakage.
- Add class weights/focal loss params to `configs/extensions/intraday_ml/model_lgbm.yaml`; ensure trainer wires them through.
- Retrain via `python run_phaseA_pipeline.py --config configs/extensions/intraday_ml/phaseA_sip_full.yaml` and archive training metrics.

### WS2 – Policy Calibration & Expected-R Gate
- Extend policy calibration tooling (`extensions/intraday_ml_policies/calibration.py`) to emit recommended thresholds for `prob`, `score_margin`, `min_directional_gap`, and `expected_R` cutoffs.
- Add expected-R computation in `IntradayMLDecisionPolicy.process_signals`; require `expected_R >= 1.5` for entries.
- Feed ATR/support-based stop/target calculations from a new helper (e.g., `extensions/intraday_ml/risk/levels.py`) that consumes merged feature set.

### WS3 – Diagnostics & Logging
- Extend `oos_rejections.parquet` schema to include `prob_long`, `prob_short`, `directional_gap`, `atr_stop`, `atr_target`, `expected_R`, `gap_reason`.
- Update pilot report/trade summary to highlight trade counts per symbol and daily trade frequency vs. target range.

### WS4 – Config & Documentation
- Update `configs/extensions/intraday_ml/phaseA_sip_full.yaml` with new policy defaults (ATR settings, calibration toggles).
- Document the workflow in `docs/extensions/intraday_ml_models/sprint2_bigmove_workflow.md` (section for v2) plus a new section in `20251111_model_enhancement_2.md` referencing commands and acceptance tests.

## Testing & Validation
- `make format && make lint && make check-types` for code hygiene.
- Focused unit tests:
  - Label builder test ensuring no future bars used (`tests/extensions/intraday_ml/test_functional_sip_pipeline.py` or new test).
  - Policy expected-R gate test verifying ATR-based stops/targets produce ≥1.5 R before order creation.
  - Rejection logging test confirming new columns populated for both gap and threshold failures.
- Functional run: `python run_phaseA_pipeline.py --config configs/extensions/intraday_ml/phaseA_sip_full.yaml` with SIP membership regenerated if configs change; verify summary shows ≥3 trades/day average, ≥60 % win rate, R≥1.5.
- Optional: targeted `pytest tests/extensions/intraday_ml -k policy` to cover policy logic changes.

## Deliverables
1. Updated configs (`targets_bigmove.yaml`, `model_lgbm.yaml`, `phaseA_sip_full.yaml`).
2. Enhanced policy logic + diagnostics in `extensions/intraday_ml_policies/`.
3. New/updated docs capturing workflow and tuning guidance.
4. Artefact bundle from validation run demonstrating improved trade frequency and profitability.

## Command Reference
```bash
# Format/lint/type-check
make format && make lint && make check-types

# Run focused unit tests
pytest tests/extensions/intraday_ml -k policy

# End-to-end pipeline
python run_phaseA_pipeline.py --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
```

## Sprint 2.v2 Execution Log
- **WS1 – Label + model refresh**
  - Updated `targets_bigmove.yaml` with ≥1.5 R ATR thresholds and risk‑reward controls.
  - Added focal-loss weighting hooks in `model_lgbm.yaml` + trainer.
  - **Validation:**
    ```bash
    pytest tests/extensions/intraday_ml_policies/test_intraday_ml_decision_policy.py \
      tests/extensions/intraday_ml/test_risk_levels.py
    ```
    (passes with joblib serial warning only).
- **WS2 – Policy calibration + expected‑R gate**
  - Introduced `risk_levels` helper and wired it through calibration + decision policy.
  - Added new calibration percentiles (`expected_r`, `score_margin`) and per-symbol min `expected_r`.
- **WS3 – Diagnostics & reporting**
  - `oos_rejections.parquet` now carries `prob_long`, `prob_short`, `directional_gap`, `atr_stop`, `atr_target`, `expected_R`, `gap_reason`.
  - `trade_summary.md` + run summary highlight `trades_by_symbol` and daily trade frequency vs the 3–5 trades/day target band.
- **WS4 – Config + docs**
  - `phaseA_sip_full.yaml` defaults to `targets_bigmove.yaml`, enables calibration, and sets ATR risk knobs (`min_expected_r=1.5`, `target_trades_min/max=3/5`).
  - Added Sprint 2.v2 guidance with commands + acceptance tests in `docs/extensions/intraday_ml_models/sprint2_bigmove_workflow.md`.
