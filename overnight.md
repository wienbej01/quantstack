Here’s the full Codex CLI prompt you can paste in. It tells Codex to:

* Add **quantile / rank-based big-move gating**.
* Add a **TOD on/off switch** and create a debug config with TOD disabled.
* Recompute OOS signals with a **`bigmove_quantile`** column.
* Run a **sanity sweep** (quantile gating, TOD off) and a **wide sweep** (quantile gating, TOD on), end-to-end.

````text
You are a NON-REASONING coding assistant working in the root of the `quantstack` repo.

GOAL
Refactor the intraday big-move policy to support **quantile / rank-based gating** on `prob_bigmove`, relax TOD via a config switch, and then run end-to-end scoring and policy sweeps using the new gating.

You must:
1. Extend the big-move policy to support a new "quantile" mode (in addition to the existing probability threshold mode).
2. Extend the OOS scoring so it computes and stores a `bigmove_quantile` column for each bar.
3. Add a TOD filter enable/disable flag and create a debug policy config with TOD disabled.
4. Define a quantile-based sweep grid.
5. Re-run:
   - big-move OOS scoring, and
   - two policy sweeps (sanity + wide),
   using the quantile gating.

You MAY run long commands (full OOS / sweeps) as part of the final section; these are expected to run for a long time.

HARD RULES
- Do NOT change label definitions or retrain the big-move models. Reuse existing Stage-1 / Stage-2 artefacts.
- Do NOT introduce any look-forward using realized returns or labels. Quantile gating may use the distribution of **predicted** `prob_bigmove`, not realized outcomes.
- Avoid mock/placeholder logic in production code. Tests may use minimal data fixtures.
- Maintain backward compatibility: existing configs using the old probability-based gate must continue to work.

======================================================================
TASK 0 – INSPECT EXISTING BIG-MOVE POLICY & SCORER (READ-ONLY)
======================================================================

1. Open:
   - `extensions/intraday_ml/policy/bigmove_policy_adapter.py`
   - `extensions/intraday_ml/policy/...` main decision policy (e.g. `intraday_decision_policy.py` or equivalent) where `_bigmove_allowed` is used and `reject_bigmove_prob` is recorded.

   Confirm:
   - It currently loads `bigmove_policy.probability_threshold` from config.
   - It sets `df["_bigmove_allowed"] = prob_bigmove >= probability_threshold`.
   - `IntradayMLDecisionPolicy._evaluate_entry_candidate` (or equivalent) rejects with reason `bigmove_prob_below_threshold` when `_bigmove_allowed` is False.

2. Open:
   - `extensions/intraday_ml/experiments/score_bigmove_oos.py`

   Confirm:
   - It reads `prob_bigmove` and directional probabilities from big-move models.
   - It writes `oos_predictions_bigmove.parquet` with the combined baseline + big-move signals.

Do NOT modify anything in this step.

======================================================================
TASK 1 – ADD QUANTILE-BASED BIG-MOVE GATING
======================================================================

We will extend the big-move policy configuration and adapter to support two modes:

- `"probability"` (current behaviour, default)
- `"quantile"` (new behaviour based on rank/quantile of prob_bigmove)

1. Extend config schema

In `configs/extensions/intraday_ml/policy_config_bigmove.json`:

- Inside the `bigmove_policy` block, add two new keys:

  ```json
  "bigmove_policy": {
    "mode": "probability",          // "probability" or "quantile"
    "probability_threshold": 0.50,  // existing field
    "quantile_threshold": 0.999,    // new: default to top 0.1% when in quantile mode
    ...
  }
````

* DO NOT remove existing fields. Leave defaults as they are for backward compatibility.

2. Extend BigMovePolicyAdapter

In `extensions/intraday_ml/policy/bigmove_policy_adapter.py`:

* When loading config, read:

  ```python
  mode = bigmove_cfg.get("mode", "probability")
  prob_threshold = bigmove_cfg.get("probability_threshold", 0.5)
  quantile_threshold = bigmove_cfg.get("quantile_threshold", 0.999)
  ```

* In the place where `_bigmove_allowed` is computed, change the logic to:

  ```python
  if mode == "probability":
      df["_bigmove_allowed"] = df["prob_bigmove"] >= prob_threshold
  elif mode == "quantile":
      # Expect a quantile column to be present in signals (see Task 2)
      quant_col = "_bigmove_quantile"
      if quant_col not in df.columns:
          raise KeyError(f"Expected {quant_col} column for quantile big-move gating")
      df["_bigmove_allowed"] = df[quant_col] >= quantile_threshold
  else:
      raise ValueError(f"Unsupported bigmove_policy.mode: {mode}")
  ```

* Keep the rejection reason and instrumentation unchanged:

  * If `_bigmove_allowed` is False, rejection reason remains `REJECT_REASON_BIGMOVE_PROB` / `"bigmove_prob_below_threshold"`. We are gating on the same concept, just with a different scale.

3. Backward compatibility

* If `mode` is absent in config, default to `"probability"`, preserving the current behaviour.

======================================================================
TASK 2 – ADD bigmove_quantile TO OOS SIGNALS
============================================

We need a quantile / rank measure for `prob_bigmove` over the **OOS signals file**.

We will:

* Extend `score_bigmove_oos.py` so that after it builds the combined signals DataFrame, it computes a global quantile rank of `prob_bigmove` and stores it in a new column `_bigmove_quantile`.

Implementation details:

1. Open `extensions/intraday_ml/experiments/score_bigmove_oos.py`.

2. After the combined signals DataFrame (`df_signals` or equivalent) is constructed and before writing to parquet:

   * Compute a global rank-based quantile for `prob_bigmove`:

     ```python
     import numpy as np

     # Assume df_signals has a `prob_bigmove` column
     n = len(df_signals)
     if n == 0:
         df_signals["_bigmove_quantile"] = np.nan
     else:
         # Rank 1..n, then normalise to (0,1]
         ranks = df_signals["prob_bigmove"].rank(method="average")
         df_signals["_bigmove_quantile"] = ranks / float(n)
     ```

   * This uses **predicted probabilities only**, no label information.

3. Ensure `_bigmove_quantile` is persisted in the final parquet:

   * The `to_parquet` call must include this column (it will be included automatically if you modify `df_signals` in place).

4. Do NOT change any existing columns or behaviour, except for adding `_bigmove_quantile`.

======================================================================
TASK 3 – ADD TOD FILTER ENABLE/DISABLE FLAG
===========================================

We want the ability to **disable TOD** for debug runs, and keep existing behaviour for production.

1. Find the TOD filter logic

In the policy code (likely in the same decision policy module), locate the time-of-day check that:

* Uses `min_time = 09:35` and `max_time = 15:50` in America/New_York.
* Rejects bars outside this window with a reason like `"time_filter"` which maps to `REJECT_REASON_TOD_PROFILE`.

2. Extend policy config

In `configs/extensions/intraday_ml/policy_config_bigmove.json`:

* Add a new top-level key (or under a `time_filter` block) for TOD enable/disable, for example:

  ```json
  "tod_filter_enabled": true,
  "time_filter": {
    "min_time": "09:35",
    "max_time": "15:50",
    "timezone": "America/New_York"
  }
  ```

* Use the existing structure for `min_time`, `max_time`, `timezone`; only add `tod_filter_enabled` if it does not exist.

3. Update policy code to respect the flag

In the method that enforces TOD:

* Wrap the time-filter logic in a conditional:

  ```python
  if self.config.get("tod_filter_enabled", True):
      # existing TOD logic
      if not self._within_time_window(ts):
          self.rejection_counter[REJECT_REASON_TOD_PROFILE] += 1
          return NO_TRADE
  ```

* If `tod_filter_enabled` is `False`, skip the TOD rejection entirely (no changes to `reject_tod_profile`).

======================================================================
TASK 4 – CREATE QUANTILE-DEBUG POLICY CONFIG
============================================

Create a new policy config for quantile gating with TOD disabled, for calibration sweeps.

1. New file:

* `configs/extensions/intraday_ml/policy_config_bigmove_quantile_debug.json`

2. Contents:

* Copy `policy_config_bigmove.json` as a base.

* Modify:

  ```json
  "tod_filter_enabled": false,
  "bigmove_policy": {
    "mode": "quantile",
    "probability_threshold": 0.50,   // unused in quantile mode, keep for compatibility
    "quantile_threshold": 0.995,
    ...
  }
  ```

* Keep other fields (score_margin, prob_threshold_long, max_open_positions_global, etc.) the same as in the main config.

======================================================================
TASK 5 – DEFINE QUANTILE SWEEP GRID
===================================

We will define a new grid that sweeps **quantile thresholds** instead of absolute probabilities.

1. Create a new grid file:

* `configs/extensions/intraday_ml/policy_sweep_grid_quantile_wide.yaml`

2. Contents (exact keys must match config):

```yaml
prob_threshold_long:
  - 0.50
  - 0.55
  - 0.60

score_margin:
  - -0.10
  - -0.05
  - 0.00
  - 0.02

bigmove_policy.quantile_threshold:
  - 0.990    # top 1.0%
  - 0.995    # top 0.5%
  - 0.9975   # top 0.25%
  - 0.9990   # top 0.1%

max_open_positions_global:
  - 2
  - 3
```

* No `param_` prefixes; `policy_sweep.apply_overrides()` will add those when writing the frontier.

======================================================================
TASK 6 – QUICK TESTS
====================

1. Run unit tests to ensure no obvious breakage:

```bash
pytest tests/extensions/intraday_ml/test_policy_sweep.py
pytest tests/extensions/intraday_ml_models/test_train_lgbm.py
```

(You may reuse existing tests; add new ones only if there is already a convenient place to extend.)

2. Optional: a tiny smoke run of `score_bigmove_oos` on a subset, but not required if code is straightforward.

======================================================================
TASK 7 – END-TO-END RUNS (OVERNIGHT)
====================================

Now run the full OOS scoring with quantile column and then two sweeps.

Assumptions:

* Existing big-move models config:
  `configs/extensions/intraday_ml/bigmove_models_config.yaml`
* Existing phase A OOS features and baseline predictions:

  * `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet`
  * `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet`

1. Re-score OOS with big-move models and quantiles

```bash
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet
```

This will now write `prob_bigmove`, directional probs, and `_bigmove_quantile` to the combined signals.

2. Sanity sweep: quantile gating, TOD disabled

Use the **debug quantile config** with TOD off:

* Create a minimal sanity grid:

  `configs/extensions/intraday_ml/policy_sweep_grid_quantile_sanity.yaml`:

  ```yaml
  prob_threshold_long:
    - 0.50

  score_margin:
    - -0.10
    - -0.05
    - 0.00

  bigmove_policy.quantile_threshold:
    - 0.990

  max_open_positions_global:
    - 2
  ```

Run:

```bash
python -m extensions/intraday_ml.experiments.policy_sweep \
  --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
  --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove_quantile_debug.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_quantile_sanity.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_quantile_sanity.csv
```

Goal: verify **non-zero entries** now appear and see rejection breakdown with TOD off.

3. Wide sweep: quantile gating, TOD ON (production-like)

Use the main policy config with TOD enabled and the wide quantile grid:

```bash
python -m extensions/intraday_ml.experiments.policy_sweep \
  --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
  --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_quantile_wide.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_quantile_wide.csv
```

These runs may take a long time; they are intended to be run unattended (overnight).

======================================================================
TASK 8 – FINAL SUMMARY (PRINT ONLY, DO NOT MODIFY FILES)

After the sweeps complete, print a concise summary to stdout (for the human to copy):

* From `bigmove_frontier_quantile_sanity.csv`:

  * Number of grid rows.
  * For each row:

    * `param_bigmove_policy.quantile_threshold`
    * `entries`, `trades_per_day`
    * rejection breakdown (`reject_bigmove_prob`, `reject_tod_profile`, `reject_expected_r`, etc.)

* From `bigmove_frontier_quantile_wide.csv`:

  * Total rows.
  * At least 5 configurations with:

    * `entries > 0`
    * their `param_bigmove_policy.quantile_threshold`, `param_prob_threshold_long`, `param_score_margin`, `param_max_open_positions_global`
    * `trades_per_day`, `avg_r_multiple`, and main rejection counts.

Do NOT output extra commentary beyond this summary.

```
::contentReference[oaicite:0]{index=0}
```
