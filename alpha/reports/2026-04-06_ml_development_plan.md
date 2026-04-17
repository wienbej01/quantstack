# ML Development Plan

Last updated: `2026-04-06`

## Status

- overall_status: `in_progress`
- current_step: `broader_any_source_offline_matrix_completed`
- update_rule: `mark each step completed in this file immediately after finishing it`
- latest_update:
  - completed hygiene implementation in loaders and dataset sanitation
  - completed explicit blocked split controls in trainer
  - completed feature-profile controls in action-ranker selection
  - corrected invalid first compact matrix caused by timestamp-resolution label bug
  - rebuilt compact feature-source cache with fixed labels
  - completed corrected compact feature-source training matrix
  - verified with targeted tests: `44 passed, 5 skipped`
  - Variant A passed the corrected internal validation/test screen
  - fixed Variant A frozen replay timeout by adding an L2-only fast scoring path
  - completed Variant A frozen forward replay, ungated and `gate_a`
  - fresh authoritative Variant A replay did not beat the repaired production baseline on frozen OOS
  - stale `*_fastpath` replay output dirs are superseded by the `*_authoritative` dirs
  - `gate_a` was harmful for Variant A on the frozen forward block
  - promotion gate revised: fewer than 3-5 trades/day is acceptable if PnL/PF materially improve
  - no promotion decision has been made because Variant A failed frozen OOS PnL/PF versus the repaired production baseline
  - final verification after replay fast paths: `44 passed, 5 skipped`
  - completed broader `any`-source offline matrix with fresh cache/output names and no reuse of superseded replay caches
  - rejected all four broader `any`-source artifacts because pre-forward test mean edge was negative

## Context

- workspace: [quantstack alpha](/home/jacobw/trading/repos/quantstack/alpha)
- branch: `alpha-homeserver-dev`
- active production-adjacent branch:
  - trainer: [train_ml_action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/train_ml_action_ranker.py)
  - model code: [action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/src/models/action_ranker.py)
  - replay runner: [run_ml_action_ranker_budget_backtest.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/run_ml_action_ranker_budget_backtest.py)
- current strongest baseline artifact:
  - [action_ranker_xgb_2026-03-19.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_2026-03-19.pkl)
- frozen forward production block:
  - `2026-03-16` to `2026-03-20`
- current official-path data status:
  - Polygon cache present through `2026-03-20`
  - L2 present through `2026-04-04`
  - SIP official path populated through `2026-02-18`, but some date dirs are missing `sip_universe.json` or contain empty symbol lists
- critical hygiene fact:
  - weekend-labeled L2 directories exist, but they are not tradable sessions
  - sampled files contain midnight ET heartbeat-like rows with null quotes/depth
  - these must be excluded from training, overlap stats, and validation

## Method

- use blocked, time-ordered evaluation
- fix data hygiene before any model work
- train only on pre-OOS data
- run a narrow variant matrix, not a wide hyperparameter search
- compare variants on frozen OOS and reject anything that only improves in-sample
- prefer lower-complexity model compositions unless added complexity gives stable OOS gain

## Research Universes

### General action-ranker universe

- use `Polygon ∩ L2`
- exclude weekend-labeled L2 dates and non-session junk rows
- keep final OOS block frozen: `2026-03-16` to `2026-03-20`

### SIP-constrained regime/context universe

- use `Polygon ∩ L2 ∩ loadable non-empty SIP`
- current usable dates: `2026-01-08` to `2026-02-18`
- suitable for context/regime analysis, not for large-capacity model branching

## Workstreams

### 1. Data Hygiene

Status: `completed`

Steps:

1. Harden L2 inventory in [l2_loader.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/l2_loader.py)
   - ignore weekend-labeled dates by default
   - ignore empty date dirs and symbol dirs without parquet files
2. Harden SIP inventory in [sip_loader.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/sip_loader.py)
   - distinguish raw date dirs vs loadable dates vs non-empty loadable dates
3. Harden symbol-day sanitation in [ml_dataset.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/ml_dataset.py)
   - keep only regular-session ET rows
   - reject symbol-days with no valid market data
4. Preserve auditability
   - quality logs must show why symbol-days were dropped
   - overlap/inventory outputs must land under `alpha/output` or `alpha/reports`

Outcome:

- weekend junk never enters compact cache, training frames, or overlap reports
- SIP availability is measured from usable files, not raw directory count
- date coverage becomes reproducible and explainable

Pass gates:

- weekend dates `2026-01-31`, `2026-02-22`, `2026-03-07`, `2026-04-04` do not appear in training coverage or overlap outputs
- midnight/null heartbeat symbol-days are rejected
- SIP inventory can report valid/loadable dates without manual inspection

Fail gates:

- any weekend date still appears in `coverage_summary`
- compact cache still includes zero-information symbol-days
- overlap scripts still count empty SIP dates as valid coverage

Completion notes:

- [l2_loader.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/l2_loader.py) now filters weekend-labeled dates and symbol dirs without parquet files
- [sip_loader.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/sip_loader.py) now distinguishes raw date dirs from loadable non-empty dates
- [ml_dataset.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/ml_dataset.py) now rejects off-session and zero-information symbol-days before they enter training

### 2. Split Discipline

Status: `completed`

Steps:

1. Add explicit date filters to [train_ml_action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/train_ml_action_ranker.py)
   - `--start-date`
   - `--end-date`
   - `--business-days-only`
2. Stop relying on blind `65/20/15` over whatever inventory happens to exist
3. Use explicit blocked dates for this cycle

Primary split template:

- train: `2025-12-19` to `2026-02-23`
- validate: `2026-02-25` to `2026-03-09`
- frozen OOS sanity block: `2026-03-10` to `2026-03-16`
- final forward block remains frozen: `2026-03-16` to `2026-03-20`

SIP-constrained split template:

- train: `2026-01-08` to `2026-01-30`
- validate: `2026-02-02` to `2026-02-06`
- OOS: `2026-02-09` to `2026-02-18`

Outcome:

- no contamination from March forward dates
- every matrix result has clear train/validation/OOS lineage

Pass gates:

- no retrained artifact includes dates beyond the declared training end date
- matrix runs are reproducible from explicit date arguments

Fail gates:

- any retrained artifact includes `2026-03-16` or later for forward-block evaluation
- validation and OOS boundaries are inferred implicitly from latest available data

Completion notes:

- [train_ml_action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/train_ml_action_ranker.py) now supports:
  - `--start-date`
  - `--end-date`
  - `--business-days-only`
  - `--train-end-date`
  - `--val-end-date`
- trainer artifacts now persist split mode and explicit blocked split metadata

### 3. Feature and Model Development

Status: `completed`

Principles:

- keep focus on XGBoost action ranking
- do not branch into RL or contextual bandits yet
- do not promote the quality overlay yet

Steps:

1. Add intentional action-ranker feature profiles in [action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/src/models/action_ranker.py)
   - `full`
   - `stable`
   - `stable_causal`
2. Exclude accidental overfitting features
   - absolute timestamps
   - metadata-like numeric fields
   - any leakage columns
3. Keep action space bounded first
   - baseline holds: `3,5,8,12`
   - expanded holds `2,3,4,5,6,8,10,12` only if simpler variants show real OOS improvement

Variant matrix:

- Variant A. baseline-cleaned XGB
  - side-aware context: on
  - causal price features: off
  - feature profile: `full` or `stable`
  - holds: `3,5,8,12`
- Variant B. stable XGB
  - side-aware context: on
  - causal price features: off
  - feature profile: `stable`
  - holds: `3,5,8,12`
- Variant C. stable causal XGB
  - side-aware context: on
  - causal price features: on
  - feature profile: `stable_causal`
  - holds: `3,5,8,12`
- Variant D. stable causal no-side-aware
  - side-aware context: off
  - causal price features: on
  - feature profile: `stable_causal`
  - holds: `3,5,8,12`
- Optional Variant E. expanded hold causal XGB
  - only if A-D show real OOS improvement
  - holds: `2,3,4,5,6,8,10,12`

Why these variants:

- test whether reduced feature sets generalize better
- test whether causal price features add real OOS value
- test whether side-aware context features help or only add variance
- test whether expanded action complexity is justified

Outcome:

- a compact, interpretable model matrix with attributable gains or regressions
- either a stronger cleaned successor to the current XGB action-ranker, or evidence that the current branch is near its ceiling

Pass gates:

- variant beats cleaned baseline on frozen OOS PnL and PF
- non-zero activation on frozen OOS
- no major collapse in trades/day relative to baseline, unless PnL/PF materially improve enough to justify lower activity
- validation and OOS move in the same direction

Fail gates:

- gain appears only in validation
- trade count collapses materially
- improvement depends on expanded complexity with unstable selection behavior

Progress notes:

- [action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/src/models/action_ranker.py) now supports `full`, `stable`, and `stable_causal` feature profiles
- metadata-like numeric columns are excluded from action-ranker feature selection
- compact matrix was run on the `features` source subset using explicit blocked dates
- the first matrix was invalid because all labels were NaN from a timestamp-resolution bug
- after [ml_labels.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/ml_labels.py) was fixed, Variant A passed the corrected internal screen
- Variants B-D were rejected on the corrected pre-forward test block

### 4. Policy / Replay Matrix

Status: `completed_for_variant_a`

Steps:

1. Evaluate retained artifacts with the same replay policy
2. Primary policy settings:
   - `daily_top_k=4`
   - `max_longs_per_day=2`
   - `min_score=0.5`
   - `bar_source=polygon`
3. Compare:
   - ungated
   - `gate_a`
     - `pressure_k <= 0.0`
     - `spread <= 0.03`
     - `depth_imb_k <= -0.02`
4. Keep policy matrix narrow during model comparison

Outcome:

- fair comparison of model variants under the same deployment-like decision rule
- clear answer on whether `gate_a` helps or hurts after cleanup

Pass gates:

- same policy applied to all retained artifacts
- ungated vs gated comparison reported separately from model comparison

Fail gates:

- policy knobs change between artifacts
- top-k or long-cap tuning is used to rescue weak models

Completion notes:

- the earlier replay attempt used an invalid pre-label-fix artifact and should be ignored
- corrected Variant A is the only compact feature-source candidate eligible for frozen forward replay
- [run_ml_action_ranker_budget_backtest.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/run_ml_action_ranker_budget_backtest.py) now batches model predictions per symbol-day instead of calling XGBoost once per bar
- the first corrected Variant A replay still timed out because scoring recomputed the full rolling ML feature frame for every minute bar
- [run_ml_action_ranker_budget_backtest.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/run_ml_action_ranker_budget_backtest.py) now also has an L2-only fast scoring path for artifacts without causal bar-history feature columns
- [engine.py](/home/jacobw/trading/repos/quantstack/alpha/src/backtest/engine.py) now skips feature preparation for replay signals that explicitly declare `requires_features = False`
- [engine.py](/home/jacobw/trading/repos/quantstack/alpha/src/backtest/engine.py) now avoids recomputing rolling ML features for precomputed feature-source L2 rows during replay scoring
- the heavy `2026-03-19` one-day probe changed from timeout under `120s` to successful completion under `120s`
- authoritative one-day sanity replay:
  - command: `python alpha/scripts/run_ml_action_ranker_budget_backtest.py --artifact-path alpha/models/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl --windows fw:2026-03-19:2026-03-19 --daily-top-ks 4 --max-longs-per-day-values 2 --min-score 0.5 --bar-source polygon --output-dir alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_2026-04-06_probe_2026-03-19_authoritative --no-resume`
  - output: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_2026-04-06_probe_2026-03-19_authoritative/summary.json)
  - result: `3` trades, `-22.594567049999853` PnL, `0.4684287247560384` PF, `3.0` trades/day, `trade_budget_pass=true`
- superseded frozen forward ungated replay:
  - command: `python alpha/scripts/run_ml_action_ranker_budget_backtest.py --artifact-path alpha/models/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl --windows fw:2026-03-16:2026-03-20 --daily-top-ks 4 --max-longs-per-day-values 2 --min-score 0.5 --bar-source polygon --output-dir alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_fast_2026-04-06`
  - superseded output: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_fast_2026-04-06/summary.json)
  - result: `14` trades, `52.63191695000205` PnL, `1.610455684853817` PF, `2.8` trades/day, `trade_budget_pass=false`
- authoritative frozen forward ungated replay:
  - command: `python alpha/scripts/run_ml_action_ranker_budget_backtest.py --artifact-path alpha/models/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl --windows fw:2026-03-16:2026-03-20 --daily-top-ks 4 --max-longs-per-day-values 2 --min-score 0.5 --bar-source polygon --output-dir alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_2026-04-06_authoritative --no-resume`
  - output: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_2026-04-06_authoritative/summary.json)
  - result: `13` trades, `-3.8057830499979417` PnL, `0.9558583074145192` PF, `2.6` trades/day, `trade_budget_pass=false`
- superseded frozen forward `gate_a` replay:
  - command: `python alpha/scripts/run_ml_action_ranker_budget_backtest.py --artifact-path alpha/models/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl --windows fw:2026-03-16:2026-03-20 --daily-top-ks 4 --max-longs-per-day-values 2 --min-score 0.5 --bar-source polygon --cache-dir alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_fast_2026-04-06 --output-dir alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_gate_a_fast_2026-04-06 --weak-context-max-pressure-k 0.0 --weak-context-max-spread 0.03 --weak-context-max-depth-imb-k -0.02`
  - superseded output: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_gate_a_fast_2026-04-06/summary.json)
  - result: `13` trades, `-45.147353049998245` PnL, `0.6039463361158175` PF, `2.6` trades/day, `trade_budget_pass=false`
- authoritative frozen forward `gate_a` replay:
  - command: `python alpha/scripts/run_ml_action_ranker_budget_backtest.py --artifact-path alpha/models/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl --windows fw:2026-03-16:2026-03-20 --daily-top-ks 4 --max-longs-per-day-values 2 --min-score 0.5 --bar-source polygon --output-dir alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_gate_a_2026-04-06_authoritative --no-resume --weak-context-max-pressure-k 0.0 --weak-context-max-spread 0.03 --weak-context-max-depth-imb-k -0.02`
  - output: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_gate_a_2026-04-06_authoritative/summary.json)
  - result: `12` trades, `-101.58505304999824` PnL, `0.10884847641533206` PF, `2.4` trades/day, `trade_budget_pass=false`
- decision:
  - do not promote `gate_a` for Variant A
  - do not promote Variant A because the authoritative ungated replay failed frozen OOS PnL/PF versus the repaired production baseline
  - keep the repaired production artifact as the baseline for the next broader `any`-source/offline comparison

### 4b. Broader Any-Source Offline Matrix

Status: `completed_rejected`

Purpose:

- test whether adding raw-source fallback data improves the compact feature-source candidate without tuning policy knobs
- preserve the same blocked split and XGBoost hyperparameters as the corrected feature-source matrix
- avoid overfitting by screening on the pre-forward test block before any frozen forward replay

Setup:

- compact cache: [ml_compact_cache_action_2026-04-06_any_windowed_labelfix](/home/jacobw/trading/repos/quantstack/alpha/output/ml_compact_cache_action_2026-04-06_any_windowed_labelfix)
- cache source type: `any`
- cached entries: `98`
- compact rows before training sampling/alignment: `254289`
- rows after live alignment/filtering: `22203`
- coverage: `31` dates, `54` symbols
- aligned source mix:
  - `features`: `9671`
  - `raw`: `12532`
- split:
  - train: `2025-12-19` to `2026-02-23`
  - validation: `2026-02-25` to `2026-03-09`
  - pre-forward test: `2026-03-10` to `2026-03-13`

Results:

| Variant | Profile | Causal Bars | Side-Aware | Val Precision | Val Edge Bps | Test Precision | Test Edge Bps | Decision |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| A | `full` | `false` | `true` | 0.650 | 42.69 | 0.375 | -55.01 | reject |
| B | `stable` | `false` | `true` | 0.450 | -35.79 | 0.562 | -8.75 | reject |
| C | `stable_causal` | `true` | `true` | 0.550 | 26.72 | 0.438 | -27.09 | reject |
| D | `stable_causal` | `true` | `false` | 0.550 | 26.72 | 0.438 | -27.09 | reject |

Artifacts:

- [action_ranker_xgb_variant_a_full_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_a_full_any_labelfix_2026-04-06.pkl)
- [action_ranker_xgb_variant_b_stable_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_b_stable_any_labelfix_2026-04-06.pkl)
- [action_ranker_xgb_variant_c_stable_causal_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_c_stable_causal_any_labelfix_2026-04-06.pkl)
- [action_ranker_xgb_variant_d_stable_causal_noside_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_d_stable_causal_noside_any_labelfix_2026-04-06.pkl)
- [2026-04-06_any_source_training_matrix.csv](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/2026-04-06_any_source_training_matrix.csv)

Decision:

- do not replay any broader `any`-source artifact on frozen OOS yet
- all four variants failed the pre-forward test edge screen
- raw-source expansion increased data volume but did not improve generalization
- keep the repaired production artifact as the baseline

### 5. Reporting

Status: `completed_current`

Steps:

1. Write a research report under `alpha/reports` or `alpha/output`
2. Include:
   - post-hygiene data inventory
   - filtered date universe
   - exact train/validation/OOS blocks
   - model variant table
   - replay matrix table
   - best artifact
   - reject list and reasons
   - operational recommendation
3. Save machine-readable outputs

Completion notes:

- report written to [2026-04-06_ml_matrix_report.md](/home/jacobw/trading/repos/quantstack/alpha/reports/2026-04-06_ml_matrix_report.md)
- machine-readable matrix written to [2026-04-06_training_matrix.csv](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/2026-04-06_training_matrix.csv)
   - one summary JSON per training run
   - one summary JSON per replay run
   - one combined matrix CSV
   - one markdown report

Outcome:

- work is compact, reproducible, and recoverable
- no detail is lost if the session is interrupted

Pass gates:

- every result in the markdown report points to a concrete artifact/output path
- every promoted conclusion is backed by frozen OOS metrics

Fail gates:

- conclusions rely on console output only
- artifact lineage cannot be reconstructed

## Execution Order

1. Implement hygiene filters in L2, SIP, and symbol-day sanitation
2. Add explicit date filters and feature-profile support to action-ranker training
3. Run targeted tests for loaders, dataset sanitation, and feature-profile selection
4. Retrain the compact model matrix on pre-OOS data only
5. Run fixed-policy replay on the frozen forward block
6. Write the matrix report and recommendation

## Promotion Rule

- promote only if a variant:
  - beats cleaned baseline on frozen OOS
  - keeps non-zero activation
  - materially improves PnL/PF; lower trade frequency is acceptable if this condition holds
  - does not require broader search or more policy tuning to look good

## Current Best Working Hypothesis

- most likely useful improvement:
  - repaired production artifact as current baseline
  - targeted diagnosis of why raw-source expansion creates negative pre-forward edge
  - XGBoost action-ranker only after source/schema effects are understood
  - bounded hold set `3,5,8,12`
  - ungated policy
- least likely useful path right now:
  - more complex overlay stacking
  - quality model promotion
  - RL or bandit exploration before expanding clean OOS coverage
