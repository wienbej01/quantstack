Good, constraint is crystal clear: no OOS forward-look, period.

I’ll do two things:

1. Give you a **Codex CLI prompt** that:

   * Removes all OOS temporal violations (no quantile-based gating, no OOS-wide `_bigmove_quantile` use).
   * Keeps TOD as a hard gate.
   * Switches the policy to **pure probability-based big-move gating** with a wide, *fixed* threshold grid to open the gates for trades.
2. Then I’ll give you the **exact terminal commands** you should run:

   * (1) “end-to-end” from Phase A training through policy sweeps.
   * (2) “from here” minimal re-run (starting at big-move scoring + sweeps).

---

## 1. Codex CLI prompt to clean temporal integrity and open the gates

Paste this into Codex CLI:

````text
You are a NON-REASONING coding assistant working in the root of the `quantstack` repo.

HARD CONSTRAINTS (DO NOT VIOLATE)
- ABSOLUTELY NO temporal forward-look in OOS:
  - At time t, decisions may only use information available at t.
  - No use of OOS-wide or day-wide quantiles, ranks, or any statistic that depends on future bars relative to t.
- TOD gates must remain HARD:
  - Bars outside [09:35, 15:50] America/New_York are hard-rejected.
- Supervised training may use future returns to define labels, but OOS research and trading may not look “forward in time” within the OOS window.

GOAL
1. Remove all OOS temporal integrity violations by:
   - Disabling quantile-based big-move gating in the policy for OOS.
   - Stopping the computation/use of `_bigmove_quantile` in OOS scoring.
2. Switch back to **probability-based** big-move gating only, with:
   - A wide set of FIXED thresholds for `prob_bigmove` (no quantiles).
   - TOD kept as a hard gate.
3. Provide a clear way to:
   - Run a “sanity” sweep.
   - Run a wide sweep to open up enough trades to evaluate performance.

You must:
- Modify configs and code for **policy** and **sweeps**.
- Keep the existing big-move models and labels intact.
- Provide a short summary at the end with the exact shell commands the human can run for:
  - End-to-end (Phase A → big-move training → big-move scoring → sweeps).
  - Minimal re-run starting at big-move scoring.

======================================================================
TASK 0 – DISABLE QUANTILE-BASED GATING IN OOS
======================================================================

1. POLICY CONFIGS

Open:
- `configs/extensions/intraday_ml/policy_config_bigmove.json`
- `configs/extensions/intraday_ml/policy_config_bigmove_quantile_debug.json` (if present)

Ensure both configs are set to **probability mode**, not quantile:

- In each file, under `"bigmove_policy"`:

  ```json
  "bigmove_policy": {
    "mode": "probability",
    "probability_threshold": 0.50,
    "quantile_threshold": 0.999,
    ...
  }
````

* Keep `quantile_threshold` in the JSON for backward compatibility, but it MUST NOT be used for OOS decisions. `mode` must be `"probability"` in all configs used by policy_sweep.

If there are any configs explicitly setting `"mode": "quantile"` that are used by experiments on OOS (`policy_sweep`), change them to `"probability"`.

2. POLICY ADAPTER SAFETY GUARD

Open:

* `extensions/intraday_ml/policy/bigmove_policy_adapter.py`

Currently, it likely does something like:

```python
mode = bigmove_cfg.get("mode", "probability")
if mode == "probability":
    ...
elif mode == "quantile":
    ...
```

Modify this so that:

* `mode == "probability"` is supported.
* For now, **raise** if `mode == "quantile"` to prevent accidental use in OOS:

```python
if mode == "probability":
    df["_bigmove_allowed"] = df["prob_bigmove"] >= prob_threshold
elif mode == "quantile":
    raise ValueError("Quantile mode for big-move gating is disabled for OOS to preserve temporal integrity.")
else:
    raise ValueError(f"Unsupported bigmove_policy.mode: {mode}")
```

We are not deleting the code, but we are preventing it from being used for any OOS runs.

======================================================================
TASK 1 – REMOVE `_bigmove_quantile` FROM OOS SCORING
====================================================

Open:

* `extensions/intraday_ml/experiments/score_bigmove_oos.py`

This script currently:

* Builds a combined signals DataFrame with `prob_bigmove`, direction probs, etc.
* Computes `_bigmove_quantile` as a rank/quantile over **all OOS rows**.
* Writes this to `oos_predictions_bigmove*.parquet`.

You must:

1. Remove or disable the `_bigmove_quantile` computation for OOS:

   * Delete or comment out the block that computes ranks/quantiles over the entire OOS DataFrame, e.g.:

     ```python
     # REMOVE / COMMENT OUT:
     # ranks = df_signals["prob_bigmove"].rank(method="average")
     # df_signals["_bigmove_quantile"] = ranks / float(len(df_signals))
     ```

   * DO NOT add any replacement that uses future OOS bars.

   * The final OOS signals file must include only:

     * raw model probabilities (`prob_bigmove`, `prob_bigmove_long`, etc.)
     * baseline policy fields
     * metadata (ts, symbol, etc.)

2. Ensure `_bigmove_quantile` is not used anywhere else in the OOS path:

   * Search the repo for `_bigmove_quantile`.
   * Confirm it is not referenced in `policy_sweep.py`, `BigMovePolicyAdapter`, or any policy used by OOS sweeps.
   * If any OOS-related code is using `_bigmove_quantile`, remove that usage and replace it with pure probability-based logic.

We are allowed to keep `_bigmove_quantile` computation around in **training-only** tools if it exists, but it must not be computed or used on the OOS scoring path.

======================================================================
TASK 2 – PROBABILITY-BASED SWEEP GRIDS (NO QUANTILES)
=====================================================

We will define grids that sweep **probability thresholds** only, without any quantiles.

1. SANITY GRID

Open:

* `configs/extensions/intraday_ml/policy_sweep_grid_sanity.yaml`

Replace the contents with a small probability-based sanity grid, using the **real config keys**, not `param_`:

```yaml
bigmove_policy.probability_threshold:
  - 1.0e-05
  - 2.0e-05
  - 5.0e-05

prob_threshold_long:
  - 0.50

score_margin:
  - -0.10
  - -0.05
  - 0.00

max_open_positions_global:
  - 2
```

Notes:

* No `param_` prefixes in YAML keys; `policy_sweep.apply_overrides()` will prefix them when writing the frontier CSV.
* These three thresholds (1e-5–5e-5) are deliberately loose to open the gates.

2. WIDE GRID

Open:

* `configs/extensions/intraday_ml/policy_sweep_grid_wide.yaml`

Replace contents with a wider probability-based grid:

```yaml
bigmove_policy.probability_threshold:
  - 1.0e-05
  - 2.0e-05
  - 5.0e-05
  - 1.0e-04
  - 2.0e-04
  - 5.0e-04
  - 1.0e-03

prob_threshold_long:
  - 0.50
  - 0.55
  - 0.60

score_margin:
  - -0.10
  - -0.05
  - 0.00
  - 0.02

max_open_positions_global:
  - 2
  - 3
```

These thresholds span several orders of magnitude and will produce enough candidate bars for us to see trades while still focusing on relatively high `prob_bigmove` given the rare-event base rate.

3. TOD GATES

Do NOT change TOD logic:

* TOD must remain a hard filter:

  * Only bars within [09:35, 15:50] ET are considered.
* Confirm:

  * `tod_filter_enabled` (or equivalent) is `true` in `policy_config_bigmove.json`.
  * TOD rejection reason remains mapped as `REJECT_REASON_TOD_PROFILE` / `reject_tod_profile`.

======================================================================
TASK 3 – TESTS / SANITY CHECKS
==============================

1. Run the main tests to ensure nothing is broken:

```bash
pytest tests/extensions/intraday_ml/test_policy_sweep.py
pytest tests/extensions/intraday_ml_models/test_train_lgbm.py
```

2. Optional: quick smoke-policy sweep on a tiny grid (e.g., the new sanity grid) to confirm:

* No error from quantile mode (it must not be used).
* Frontier CSV columns show:

  * `param_bigmove_policy.probability_threshold`
  * No `param_bigmove_policy.quantile_threshold`.
* Rejection reasons:

  * `reject_bigmove_prob`, `reject_tod_profile`, etc., but **no use of any quantile fields**.

======================================================================
TASK 4 – FINAL USER-FACING SUMMARY
==================================

At the end, print to stdout a concise summary for the human that includes:

1. Confirmation that:

   * `bigmove_policy.mode` is `"probability"` in all OOS policy configs.
   * `score_bigmove_oos` no longer computes `_bigmove_quantile` for OOS.
   * Quantile-based gating is hard-disabled (raises) in `BigMovePolicyAdapter`.

2. The **exact shell commands** the human can use going forward:

   (A) Full end-to-end run (Phase A → big-move models → big-move scoring → sweeps):

   ```bash
   # 1) Phase A training + baseline OOS predictions
   python run_phaseA_pipeline.py \
     --config configs/extensions/intraday_ml/phaseA_sip_full.yaml

   # 2) Big-move Stage 1 training
   python -m extensions.intraday_ml_models.train_bigmove_stage1 \
     --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
     --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
     --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
     --output-root artefacts/extensions/intraday_ml/bigmove_stage1

   # 3) Big-move Stage 2 (direction) training
   python -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
     --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
     --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
     --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
     --output-root artefacts/extensions/intraday_ml/bigmove_stage2_dir

   # 4) Score big-move models on OOS (probability-based, no quantiles)
   python -m extensions.intraday_ml.experiments.score_bigmove_oos \
     --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
     --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
     --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
     --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet

   # 5) Sanity sweep (TOD on, loose probability thresholds)
   python -m extensions.intraday_ml.experiments.policy_sweep \
     --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
     --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
     --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
     --grid configs/extensions/intraday_ml/policy_sweep_grid_sanity.yaml \
     --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
     --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_sanity.csv

   # 6) Wide sweep (TOD on, wide probability threshold grid)
   python -m extensions/intraday_ml.experiments.policy_sweep \
     --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
     --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
     --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
     --grid configs/extensions/intraday_ml/policy_sweep_grid_wide.yaml \
     --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
     --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_wide.csv
   ```

   (B) Minimal re-run starting “from here” (assuming Phase A and big-move models already exist):

   ```bash
   # 1) Re-score big-move models on OOS with updated, probability-only scorer
   python -m extensions.intraday_ml.experiments.score_bigmove_oos \
     --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
     --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
     --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
     --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet

   # 2) Sanity sweep
   python -m extensions.intraday_ml.experiments.policy_sweep \
     --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
     --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
     --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
     --grid configs/extensions/intraday_ml/policy_sweep_grid_sanity.yaml \
     --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
     --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_sanity.csv

   # 3) Wide sweep
   python -m extensions/intraday_ml.experiments.policy_sweep \
     --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
     --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
     --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
     --grid configs/extensions/intraday_ml/policy_sweep_grid_wide.yaml \
     --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
     --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_wide.csv
   ```

3. Confirm that:

   * The frontier CSVs (`bigmove_frontier_prob_sanity.csv`, `bigmove_frontier_prob_wide.csv`) show non-zero `entries` for at least some grid points.
   * No column or policy path uses `_bigmove_quantile` or quantile-based gating.

Do not emit any additional commentary beyond this summary and the two command blocks.

````

---

## 2. Your shell commands (what you asked me for explicitly)

These are the commands you should actually run after Codex has made the changes above.

### A. Full end-to-end run (from Phase A down to sweeps)

```bash
# 1) Phase A training + baseline OOS predictions (multi-class baseline)
python run_phaseA_pipeline.py \
  --config configs/extensions/intraday_ml/phaseA_sip_full.yaml

# 2) Big-move Stage 1 training (big-move classifier)
python -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root artefacts/extensions/intraday_ml/bigmove_stage1

# 3) Big-move Stage 2 (direction) training
python -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
  --output-root artefacts/extensions/intraday_ml/bigmove_stage2_dir

# 4) Score big-move models on OOS (probability-only, no quantiles)
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet

# 5) Sanity sweep (TOD on, loose probability thresholds)
python -m extensions/intraday_ml.experiments.policy_sweep \
  --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
  --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_sanity.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_sanity.csv

# 6) Wide sweep (TOD on, wide probability threshold grid)
python -m extensions/intraday_ml.experiments.policy_sweep \
  --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
  --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_wide.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_wide.csv
````

### B. Minimal re-run from your current state (no need to redo Phase A or big-move training)

If you already have:

* `artefacts/.../phaseA_full_sip/oos_features.parquet`
* `artefacts/.../phaseA_full_sip/oos_predictions.parquet`
* `artefacts/.../bigmove_stage1/*`
* `artefacts/.../bigmove_stage2_dir/*`

then this is enough:

```bash
# 1) Re-score OOS with probability-only scorer
python -m extensions/intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet

# 2) Sanity sweep
python -m extensions/intraday_ml.experiments.policy_sweep \
  --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
  --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_sanity.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_sanity.csv

# 3) Wide sweep
python -m extensions/intraday_ml.experiments.policy_sweep \
  --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
  --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_wide.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_prob_wide.csv
```

Once these finish, you should finally see a frontier with **non-zero `entries`** and TOD-respecting trades, with zero OOS temporal cheating.
