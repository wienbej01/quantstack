Here’s a Codex CLI prompt you can paste in directly. It assumes Codex is running in the root of the `quantstack` repo and has full repo context.

```text
You are a NON-REASONING coding assistant working in the root of the `quantstack` repository.

GOAL
Wire the “big-move” models into the OUT-OF-SAMPLE (OOS) signals so that the BigMovePolicyAdapter can actually run.

Concretely:
1. Add an OOS scoring script that:
   - Loads the existing OOS feature set for Phase A SIP (10m/1m intraday).
   - Loads the trained big-move models (Stage 1 big-move probability, Stage 2 direction, Stage 2 expected-R).
   - Computes:
     - `prob_bigmove`
     - `prob_bigmove_long` (and optionally `prob_bigmove_short` if applicable)
     - `expected_r_bigmove`
   - Joins these with the existing baseline signals in `oos_predictions.parquet`.
   - Writes a new combined signals file (do NOT overwrite the old one).
2. Update the policy sweep so we can point it at this new signals file and run BigMovePolicyAdapter end-to-end.
3. Add minimal tests and a short doc note.

You must be EXPLICIT. Do NOT “guess” behaviour; instead, locate existing patterns in the repo and reuse them.

HARD RULES
- READ-ONLY w.r.t. modelling and training: do NOT re-train any models. Only load and apply existing trained big-move models.
- Do NOT run any long Phase A pipelines or multi-hour jobs. Only short, focused scripts/smoke tests.
- Do NOT overwrite existing artefacts like `oos_predictions.parquet`. Always write new outputs.
- NO mock data, NO placeholder logic in production paths. If you need dummy data for tests, keep it inside test files only.
- ZERO forward-looking bias: you are only scoring a frozen OOS feature file with trained models; do not introduce any new label logic.

----------------------------------------------------------------------
TASK 0 – REPO RECON (READ-ONLY)
----------------------------------------------------------------------

1. Locate the big-move training code and models:
   - Search for big-move targets and training scripts:
     - `extensions/intraday_ml/labeling/big_move_labels.py`
     - `extensions/intraday_ml_models/train_lgbm_bigmove.py` (or similarly named).
   - Find where big-move model artefacts are saved under `artefacts/`:
     - Search for directories or files under `artefacts/extensions/intraday_ml` containing “bigmove” or similar.
   - Identify:
     - Path(s) to Stage 1 big-move probability model.
     - Path(s) to Stage 2 direction model(s).
     - Path(s) to Stage 2 expected-R regression model, if present.

2. Locate the existing baseline inference utilities:
   - Look for existing LGBM inference helpers, e.g.:
     - `extensions/intraday_ml_models/predict_lgbm.py`
     - Any `load_model` / `predict_proba` utilities in that package.
   - You must reuse these patterns for loading models and scoring, not hand-roll ad hoc LightGBM logic.

3. Confirm the BigMovePolicyAdapter expectations:
   - Open `extensions/intraday_ml/policy/bigmove_policy_adapter.py`.
   - Confirm EXACT expected column names:
     - `prob_bigmove`
     - `prob_bigmove_long` (and possibly `prob_bigmove_short`)
     - `expected_r_bigmove`
   - Confirm how they are referenced internally (attribute names, keys).

4. Confirm config expectations:
   - Open `configs/extensions/intraday_ml/policy_config_bigmove.json`.
   - In the `bigmove_policy` block, note:
     - Any key referencing those column names (prob/expected_R fields).
   - You must respect these names exactly.

DO NOT CHANGE ANYTHING YET. This step is just reconnaissance.

----------------------------------------------------------------------
TASK 1 – IMPLEMENT OOS BIG-MOVE SCORING SCRIPT
----------------------------------------------------------------------

Create a new module to score big-move models on the OOS features and write a combined signals file.

FILES TO CREATE / MODIFY
- NEW: `extensions/intraday_ml/experiments/score_bigmove_oos.py`
- READ: 
  - `extensions/intraday_ml_models/train_lgbm_bigmove.py` (for model loading patterns and feature expectations)
  - `extensions/intraday_ml_models/*predict*.py` (for inference patterns)
  - `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet`
  - `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet`

1. New script: score_bigmove_oos.py
   - Place the script at: `extensions/intraday_ml/experiments/score_bigmove_oos.py`.
   - Implement a CLI using `argparse` with at least the following arguments:
     - `--features`: path to OOS features parquet
       - DEFAULT: `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet`
     - `--baseline-signals`: path to the existing baseline signals parquet
       - DEFAULT: `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet`
     - `--output-signals`: path for the new combined signals parquet
       - DEFAULT: `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet`
     - `--models-config`: OPTIONAL if you have a config file for big-move models; otherwise you can hard-code model paths based on the training script conventions. If you hard-code them, keep them as module-level constants, clearly named.

   - Script responsibilities:
     1. Load the OOS features parquet into a DataFrame (`df_features`).
        - Confirm it has `ts` and `symbol` columns for joining.
     2. Load the baseline signals parquet (`df_signals`).
        - Confirm it also has `ts` and `symbol`.
     3. Load the big-move models:
        - Stage 1 model: big-move probability.
        - Stage 2 direction model(s).
        - Stage 2 expected-R regression model, if present.
        - Use the same load mechanism as existing LGBM inference (for example, LightGBM Booster or sklearn interface).
     4. Extract the feature matrix for scoring:
        - Figure out the feature column list used for big-move training by inspecting `train_lgbm_bigmove.py` and any associated config (e.g., `targets_bigmove.yaml` or model config).
        - Make sure the order and names of feature columns in `df_features` match what the model expects.
        - Do not invent a new feature list; reuse what the training script used.
     5. Run Stage 1 scoring:
        - Compute `prob_bigmove` as a float in [0, 1] for every row of `df_features`.
        - Store it in a new Series aligned with `df_features`.
     6. Run Stage 2 direction scoring:
        - Depending on how Stage 2 is trained:
          - If it is a classifier returning `[P(short), P(long)]`, derive:
            - `prob_bigmove_long` as P(long).
            - `prob_bigmove_short` as P(short) if available.
          - If it returns multi-class probabilities, map them to long/short in the same way the training script did.
        - At minimum, you must populate `prob_bigmove_long`.
     7. Run Stage 2 expected-R scoring:
        - If an expected-R regression model exists:
          - Predict `expected_r_bigmove` for each row.
          - Apply any clipping/flooring consistent with adapter/config expectations (e.g. floor at 1.0 or 1.5 as defined).
        - If no regression model exists yet:
          - DO NOT fake it.
          - In that case, you may omit the column and BigMovePolicyAdapter must be able to handle its absence. If the adapter currently expects it as mandatory, you MUST either:
            - Implement the regression inference properly, or
            - Extend the adapter to treat missing `expected_r_bigmove` as a derived value from ATR/SL/TP R (only if that pattern already exists in the code base).
          - Do not make up numbers.

     8. Combine with baseline signals:
        - Use `ts` and `symbol` to join `df_features` (with new big-move columns) onto `df_signals`.
        - The result must contain:
          - All original baseline columns (e.g. `prob_short`, `prob_neutral`, `prob_long`, etc.).
          - The new columns:
            - `prob_bigmove`
            - `prob_bigmove_long`
            - (optional) `prob_bigmove_short`
            - `expected_r_bigmove` (if implemented).
        - The join must be 1-to-1; if any rows do not match on `ts`+`symbol`, log a warning and drop the orphans.

     9. Write the combined DataFrame:
        - Save as parquet to `--output-signals`.
        - Do NOT overwrite `oos_predictions.parquet`.

   - Logging:
     - Log row counts for features, baseline signals, and the combined DataFrame.
     - Log basic stats for `prob_bigmove` and `prob_bigmove_long` (min, max, mean).
     - Log the output path.

2. Minimal smoke script / function
   - Inside `score_bigmove_oos.py`, expose a `main()` function and guard it with `if __name__ == "__main__": main()`.
   - This allows invoking:

     python -m extensions.intraday_ml.experiments.score_bigmove_oos

----------------------------------------------------------------------
TASK 2 – UPDATE POLICY SWEEP TO USE BIG-MOVE SIGNALS
----------------------------------------------------------------------

FILES TO MODIFY
- `extensions/intraday_ml/experiments/policy_sweep.py`
- `docs/INTRA_ML_PIPELINE.md` or `docs/extensions/intraday_ml_models/sprint2_bigmove_workflow.md` (whichever describes policy sweeps)

1. Add a CLI flag or set a new default:
   - In `policy_sweep.py`, either:
     - Keep the existing `--signals` argument but update docs/usage to recommend the BIGMOVE signals file; OR
     - Add a separate example invocation in the doc for big-move mode.

   - The intention is to run sweeps like:

     python -m extensions.intraday_ml.experiments.policy_sweep \
       --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
       --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
       --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
       --grid configs/extensions/intraday_ml/policy_sweep_grid.yaml \
       --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
       --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier.csv

2. Verify integration with BigMovePolicyAdapter
   - Ensure that `policy_sweep.py` uses a policy factory that can pick up `policy_mode: "bigmove"` from `policy_config_bigmove.json`, or equivalent.
   - Ensure that the policy adapter reads the combined signals DataFrame and finds:
     - `prob_bigmove`
     - `prob_bigmove_long`
     - `expected_r_bigmove` (if used)
     in the columns.

   - Do NOT change the BigMovePolicyAdapter column names. Instead, make sure the new combined signals provide exactly those.

----------------------------------------------------------------------
TASK 3 – TESTS AND SMOKE RUNS
----------------------------------------------------------------------

FILES TO CREATE / MODIFY
- NEW: `tests/extensions/intraday_ml/test_score_bigmove_oos.py`
- Possibly adjust existing tests for `policy_sweep.py` if present.

1. Unit-level test for the scorer:
   - Create `tests/extensions/intraday_ml/test_score_bigmove_oos.py`.
   - In the test, you are allowed to:
     - Construct a tiny synthetic DataFrame for features and baseline signals in memory.
     - Monkeypatch the model loading functions so they return trivial mock models that:
       - For Stage 1: always return a fixed prob (e.g. 0.3).
       - For Stage 2: always return some fixed directional probabilities and expected-R.
     - Call the core scoring function (factored out of `main()` to a testable function).
   - Assert:
     - The combined DataFrame contains all original baseline columns plus the 3–4 new big-move columns.
     - Shapes and dtypes are consistent.
   - This test is allowed to use mock models because it does NOT touch production code paths that will be used at runtime; you will only mock at the test level.

2. Manual smoke run (short, not full Phase A):
   - On the real artefacts, run:

     python -m extensions.intraday_ml.experiments.score_bigmove_oos

   - Confirm:
     - `oos_predictions_bigmove.parquet` is created.
     - It has columns: baseline probs, `prob_bigmove`, `prob_bigmove_long` (and possibly `prob_bigmove_short`, `expected_r_bigmove`).
   - Then run a small sweep:

     python -m extensions.intraday_ml.experiments.policy_sweep \
       --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
       --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
       --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
       --grid configs/extensions/intraday_ml/policy_sweep_grid.yaml \
       --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
       --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier.csv

   - This smoke run must complete successfully and produce a CSV with:
     - Non-zero `entries` for at least some grid points (if thresholds are not insanely tight).
   - Do NOT extend this into a multi-hour full run.

----------------------------------------------------------------------
TASK 4 – DOCS UPDATE
----------------------------------------------------------------------

1. Add a brief section to an existing doc:
   - Update either:
     - `docs/INTRA_ML_PIPELINE.md`, OR
     - `docs/extensions/intraday_ml_models/sprint2_bigmove_workflow.md`
   - Add a short section “Big-move OOS Scoring and Policy Sweep” containing:
     - A one-paragraph description that OOS big-move predictions are now written to `oos_predictions_bigmove.parquet` via `score_bigmove_oos`.
     - The exact command-line example for the policy sweep using that file.

Keep this doc addition small and factual.

----------------------------------------------------------------------
FINAL CHECK
----------------------------------------------------------------------

When you are done, the following must hold:

1. `extensions/intraday_ml/experiments/score_bigmove_oos.py` exists and runs without error on the real artefacts (short run).
2. `artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet` exists and has the columns:
   - `prob_bigmove`
   - `prob_bigmove_long`
   - (optional) `prob_bigmove_short`
   - `expected_r_bigmove` (if regression model implemented)
   plus original baseline probs and metadata (`ts`, `symbol`).
3. `policy_sweep.py` can consume the new signals file and, together with `policy_config_bigmove.json`, runs the BigMovePolicyAdapter without KeyErrors.
4. A short smoke sweep produces a `bigmove_frontier.csv` where at least some grid rows have non-zero entries/trades (assuming thresholds are not absurdly tight).

Do NOT add any extra commentary in your output. Just implement the code and keep any printed logs concise and machine/operator friendly.
```
