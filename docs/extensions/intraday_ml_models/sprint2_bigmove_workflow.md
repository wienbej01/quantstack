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

## SIP & Universe Prep Checklist

The SIP universe and membership must be refreshed before each full Phase A run to keep the filters aligned with the USD 5–50 universe:

1. **Build the SIP universe YAML** (creates `configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml`):

   ```bash
   python scripts/build_intraday_universe_sip_5_50.py \
     --output configs/extensions/intraday_ml/ \
     --min-price 5.0 \
     --max-price 50.0 \
     --min-dollar-vol 10000000
   ```

2. **Generate SIP membership** for the run window (writes into `/home/jacobw/quantstack/run/sip_membership`):

   ```bash
   python -m extensions.intraday_ml.cli_build_sip_membership \
     --start-date 2023-10-02 \
     --end-date 2024-05-31 \
     --universe-config configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml \
     --gold-root /home/jacobw/gcs-mount/gold \
     --top-k 60 \
     --external-premarket-root /home/jacobw/gcs-mount/gold/intraday_ml/sip_universe_pre \
     --output-root /home/jacobw/quantstack/run/sip_membership \
     --mode legacy
   ```

3. **Run Phase A** (`phaseA_sip_full.yaml` points at both the universe and membership path):

   ```bash
   python run_phaseA_pipeline.py --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
   ```

Follow this sequence every time you update the price/dollar-volume filters or SIP universe; the Phase A config will otherwise fail with `RuntimeError: No deployment symbols available after applying SIP filtering.` The membership CLI already respects the same top‑k/mode settings as the decision policy, so keeping the files in sync ensures deterministic experiments.

## 6. Big-Move OOS Scoring & Policy Sweep

### Train the sidecar models

Before scoring, train (or refresh) the Stage 1 probability and Stage 2 direction models so their artefacts live under deterministic folders that the scorer can reference:

```bash
python -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root artefacts/extensions/intraday_ml/bigmove_stage1

python -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
  --output-root artefacts/extensions/intraday_ml/bigmove_stage2_dir
```

Each script writes `model.pkl`, `features.json`, and `train_meta.json` so you can wire them into scoring/config management. Adjust `--split` or `--label-buffer-days` only when experimenting with alternative cohorts.

After training or pulling the latest stage models, run the standalone scorer to project them onto the frozen Phase A SIP features and merge them with the baseline signals:

```bash
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
  --expected-r-floor 1.0 \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet
```

All arguments are spelled out so there is zero ambiguity about which artefacts are used; the CLI defaults already point to the same locations but it is safer to pass them explicitly. Point `--models-config` at the JSON/YAML manifest describing the stage‑1/2 artefacts (the CLI can also auto-discover under `artefacts/extensions/intraday_ml` if you omit it). The command writes `prob_bigmove`, `prob_bigmove_long/short`, and (if available) `expected_r_bigmove` into `oos_predictions_bigmove.parquet` without touching the legacy predictions file.

With the enriched signals in place, run the policy sweep in big-move mode (defaults shown below can be overridden as needed):

```bash
python -m extensions.intraday_ml.experiments.policy_sweep \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier.csv
```

`policy_sweep.py` now points at `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet` by default, so the adapter sees the exact columns the big-move policy expects.

All four CLIs above emit `[heartbeat]` log entries every 60 seconds via `HeartbeatLogger`, so you can confirm they are progressing even during long-running Phase A jobs.
