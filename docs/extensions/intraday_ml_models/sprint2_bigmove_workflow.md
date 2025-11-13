# Sprint 2 – Big-Move Label & Model Workflow

Sprint 2 focuses on higher-ATR “big move” targets and a class-weighted LightGBM model tuned for sparse SIP cohorts. Use this guide alongside the Sprint 1 instrumentation/evaluator tooling.

## 1. Generate Big-Move Labels

```bash
python -m extensions.intraday_ml.cli.instrument_datasets \
  --config configs/extensions/intraday_ml/phaseA_master_bigmove.yaml \
  --splits train val test oos
```

This drops artefacts under `artefacts/extensions/intraday_ml/phaseA_bigmove/instrumentation/` so you can verify ±1 counts per day/symbol before training. Compare against the Sprint 1 summary to ensure directional coverage remains ≥25 samples per split.

## 2. Train the Class-Weighted Model

```bash
python run_phaseA_pipeline.py \
  --config configs/extensions/intraday_ml/phaseA_master_bigmove.yaml
```

Key changes in `model_lgbm.yaml`:

- Lower learning rate + deeper tree budget (900 estimators) to capture rare targets.
- Stronger `reg_alpha/reg_lambda` and `min_split_gain` for regularisation.
- Deterministic seeds (`seed`, `bagging_seed`, `feature_fraction_seed`) for reproducibility.
- Directional class weights (2.1×) plus tighter neutral cap via the auto-balancer.

The master config stores artefacts in `artefacts/.../phaseA_bigmove` so baseline and big-move runs remain separate.

## 3. Post-Training PnL Evaluation

Use the Sprint 1 evaluator to quantify trade frequency and risk-adjusted returns:

```bash
python -m extensions/intraday_ml.cli.evaluate_trading \
  --bars artefacts/extensions/intraday_ml/phaseA_bigmove/oos_features.parquet \
  --predictions artefacts/extensions/intraday_ml/phaseA_bigmove/oos_predictions.parquet \
  --policy-config policy_custom.yaml
```

Example `policy_custom.yaml`:

```yaml
policies:
  - name: bigmove_threshold
    kind: threshold
    prob_threshold: 0.7
    min_edge: 0.03
    min_score: 0.02
  - name: bigmove_top2
    kind: topk
    top_k: 2
    prob_threshold: 0.65
    score_column: trade_score
```

Inspect `{policy}_metrics.json` to ensure daily trade counts fall inside the 3–5 range with positive Sharpe/Sortino before moving to Sprint 3 tuning.

## 4. Calibration + SIP Checks

- Calibration stats are written to `policy_calibration_bigmove.json`; make sure at least 150 samples contribute per SIP day.
- Keep `sip_filter.enabled=true` and regenerate membership daily; the new master config assumes precomputed SIP parquet partitions exist.

Document any evaluator runs (command lines plus headline metrics) in the sprint journal so we can trace improvements relative to the Sprint 1 baseline.

## 5. Sprint 2.v2 – Confidence Uplift + Risk Logging

1. Switch the phase‑A SIP config to the new defaults (ATR stops + expected‑R gate):

   ```bash
   python run_phaseA_pipeline.py \
     --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
   ```

   The config now points to `targets_bigmove.yaml`, enables class‑weighted LightGBM,
   and wires calibration stats to `policy_calibration.json`.

2. Confirm the `oos_rejections.parquet` schema contains the new diagnostics:
   `prob_long`, `prob_short`, `directional_gap`, `atr_stop`, `atr_target`,
   `expected_R`, and `gap_reason`. Rejections due to the expected‑R floor will
   surface as `expected_r_low`.

3. Review `trade_summary.md` to ensure it reports `trades_by_symbol` plus the
   daily trade frequency versus the 3–5 trades/day target window.

4. Acceptance tests:

   ```bash
   pytest tests/extensions/intraday_ml_policies/test_intraday_ml_decision_policy.py \
     tests/extensions/intraday_ml/test_risk_levels.py
   ```

   These cover the ATR level helper, the ≥1.5 R gate, and the enriched rejection logging.
