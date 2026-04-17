# ML Matrix Report

Last updated: `2026-04-06`

## Correction

- the earlier matrix result showing `0.0` precision and `nan` edge for every variant was invalid
- root cause:
  - feature-source `ts_utc` values were stored as `datetime64[us, UTC]`
  - [ml_labels.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/ml_labels.py) converted datetime integers as if they were always nanoseconds
  - this compressed a full market session into a few seconds of apparent epoch time
  - all forward horizons then looked unavailable, making every `ret_fwd_*` value `NaN`
- fix:
  - timestamp-to-epoch conversion now explicitly converts timestamps to `datetime64[ns]` before dividing by `1e9`
  - the corrected cache is [ml_compact_cache_action_2026-04-06_features_windowed_labelfix](/home/jacobw/trading/repos/quantstack/alpha/output/ml_compact_cache_action_2026-04-06_features_windowed_labelfix)

## Scope

- objective: implement the saved ML development plan through hygiene, controlled retraining, and a compact model matrix
- frozen production-forward block remains:
  - `2026-03-16` to `2026-03-20`
- matrix execution was narrowed to the `features` source subset for tractability and lower variance
- the full `any`-source cache rebuild remains appropriate for offline work, not same-turn iteration

## Implemented Changes

- data hygiene:
  - [l2_loader.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/l2_loader.py)
  - [sip_loader.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/sip_loader.py)
  - [ml_dataset.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/ml_dataset.py)
- timestamp label fix:
  - [ml_labels.py](/home/jacobw/trading/repos/quantstack/alpha/src/data/ml_labels.py)
- training controls:
  - [train_ml_action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/train_ml_action_ranker.py)
  - explicit `start/end` filters
  - explicit blocked `train_end/val_end` split
  - `business_days_only`
  - `feature_profile`
  - `cache_source_type`
- feature selection and model robustness:
  - [action_ranker.py](/home/jacobw/trading/repos/quantstack/alpha/src/models/action_ranker.py)
  - `full`, `stable`, and `stable_causal` profiles
  - metadata-like numeric columns excluded
  - constant-probability fallback for single-class per-action targets
- replay performance:
  - [run_ml_action_ranker_budget_backtest.py](/home/jacobw/trading/repos/quantstack/alpha/scripts/run_ml_action_ranker_budget_backtest.py)
  - batches model prediction by symbol-day
  - uses an L2-only fast scoring path for artifacts without causal OHLCV feature columns
  - skips feature preparation in the backtest engine when replaying scheduled signals that do not require features
  - avoids recomputing rolling ML features for precomputed feature-source L2 rows
  - the heavy `2026-03-19` one-day probe changed from timeout under `120s` to successful completion under `120s`

## Verification

- targeted tests:
  - `pytest alpha/tests/test_ml_dataset.py alpha/tests/test_action_ranker.py alpha/tests/test_data_loaders.py -q`
  - result: `44 passed, 5 skipped`
- corrected label sanity check:
  - on `HIMS/2026-03-13`, `ret_fwd_180s` NaN ratio dropped from `1.0` to `0.038846`
  - on `HIMS/2026-03-13`, `ret_fwd_300s` NaN ratio dropped from `1.0` to `0.064231`

## Matrix Setup

- compact cache:
  - [ml_compact_cache_action_2026-04-06_features_windowed_labelfix](/home/jacobw/trading/repos/quantstack/alpha/output/ml_compact_cache_action_2026-04-06_features_windowed_labelfix)
  - cache source type: `features`
  - cached compact symbol-days: `32`
- explicit blocked split:
  - train dates:
    - `2025-12-19`
    - `2025-12-23`
    - `2026-01-08`
    - `2026-01-09`
    - `2026-01-15`
    - `2026-01-16`
    - `2026-01-20`
    - `2026-01-27`
    - `2026-01-28`
  - validation date:
    - `2026-03-09`
  - pre-forward test dates:
    - `2026-03-10`
    - `2026-03-11`
    - `2026-03-12`
    - `2026-03-13`
- coverage:
  - rows: `9671`
  - dates: `14`
  - symbols: `21`

## Corrected Training Matrix

| Variant | Feature Profile | Causal Bars | Side-Aware Context | Val Selected | Val Precision | Val Mean Edge Bps | Test Selected | Test Precision | Test Mean Edge Bps | Gate |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A | `full` | `false` | `true` | 4 | 0.500 | 18.56 | 16 | 0.625 | 34.29 | pass |
| B | `stable` | `false` | `true` | 4 | 0.750 | 52.24 | 16 | 0.250 | -10.02 | fail |
| C | `stable_causal` | `true` | `true` | 4 | 0.750 | 46.59 | 16 | 0.500 | 14.48 | fail |
| D | `stable_causal` | `true` | `false` | 4 | 0.750 | 46.59 | 16 | 0.500 | 14.48 | fail |

Interpretation:

- Variant A is the only compact feature-source variant that passed the internal screen
- Variant B appears to overfit the single validation date and fails on the pre-forward test block
- C and D improve versus B on test but remain materially weaker than A
- disabling side-aware context did not change C vs D on this feature-source slice

## Artifacts

- Variant A:
  - [action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06.pkl)
  - [training metrics](/home/jacobw/trading/repos/quantstack/alpha/output/ml_training_reports/action_ranker_xgb_variant_a_full_features_labelfix_2026-04-06/training_metrics.json)
- Variant B:
  - [action_ranker_xgb_variant_b_stable_features_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_b_stable_features_labelfix_2026-04-06.pkl)
  - [training metrics](/home/jacobw/trading/repos/quantstack/alpha/output/ml_training_reports/action_ranker_xgb_variant_b_stable_features_labelfix_2026-04-06/training_metrics.json)
- Variant C:
  - [action_ranker_xgb_variant_c_stable_causal_features_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_c_stable_causal_features_labelfix_2026-04-06.pkl)
  - [training metrics](/home/jacobw/trading/repos/quantstack/alpha/output/ml_training_reports/action_ranker_xgb_variant_c_stable_causal_features_labelfix_2026-04-06/training_metrics.json)
- Variant D:
  - [action_ranker_xgb_variant_d_stable_causal_noside_features_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_d_stable_causal_noside_features_labelfix_2026-04-06.pkl)
  - [training metrics](/home/jacobw/trading/repos/quantstack/alpha/output/ml_training_reports/action_ranker_xgb_variant_d_stable_causal_noside_features_labelfix_2026-04-06/training_metrics.json)
- machine-readable matrix:
  - [2026-04-06_training_matrix.csv](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/2026-04-06_training_matrix.csv)

## Frozen Forward Replay

Policy:

- window: `2026-03-16` to `2026-03-20`
- `daily_top_k=4`
- `max_longs_per_day=2`
- `min_score=0.5`
- `bar_source=polygon`

| Artifact | Policy Gate | Trades | PnL | Profit Factor | Trades/Day | Trade Budget |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| repaired production baseline | none | 11 | 6.71 | 1.063 | 2.2 | fail |
| repaired production baseline | `gate_a` | 11 | 3.65 | 1.034 | 2.2 | fail |
| Variant A `labelfix` authoritative | none | 13 | -3.81 | 0.956 | 2.6 | fail |
| Variant A `labelfix` authoritative | `gate_a` | 12 | -101.59 | 0.109 | 2.4 | fail |

Variant A replay outputs:

- authoritative ungated: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_2026-04-06_authoritative/summary.json)
- authoritative `gate_a`: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_gate_a_2026-04-06_authoritative/summary.json)
- superseded fast-path ungated: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_fast_2026-04-06/summary.json)
- superseded fast-path `gate_a`: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_gate_a_fast_2026-04-06/summary.json)
- authoritative one-day performance sanity check: [summary.json](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/variant_a_full_features_labelfix_ungated_2026-04-06_probe_2026-03-19_authoritative/summary.json)

Interpretation:

- the fresh authoritative Variant A ungated replay does not beat the repaired production baseline on frozen OOS PnL or PF
- Variant A also lands below the original `3-5` trades/day target with `2.6` trades/day
- revised promotion view: lower activity is acceptable if PnL/PF materially improve, but this candidate does not meet that higher-priority PnL/PF condition
- `gate_a` is harmful for Variant A on this block and should not be promoted
- because the training matrix used the narrower `features` source subset, Variant A should be treated as a candidate, not a promotion-ready replacement

## Broader Any-Source Matrix

Setup:

- compact cache: [ml_compact_cache_action_2026-04-06_any_windowed_labelfix](/home/jacobw/trading/repos/quantstack/alpha/output/ml_compact_cache_action_2026-04-06_any_windowed_labelfix)
- cache source type: `any`
- rows after live alignment/filtering: `22203`
- cache entries: `98`
- compact cached rows before training sampling/alignment: `254289`
- coverage: `31` dates, `54` symbols
- source mix after alignment/filtering:
  - `features`: `9671` rows
  - `raw`: `12532` rows
- split:
  - train: `2025-12-19` to `2026-02-23`
  - validation: `2026-02-25` to `2026-03-09`
  - pre-forward test: `2026-03-10` to `2026-03-13`

| Variant | Feature Profile | Causal Bars | Side-Aware Context | Val Selected | Val Precision | Val Mean Edge Bps | Test Selected | Test Precision | Test Mean Edge Bps | Gate |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A | `full` | `false` | `true` | 20 | 0.650 | 42.69 | 16 | 0.375 | -55.01 | fail |
| B | `stable` | `false` | `true` | 20 | 0.450 | -35.79 | 16 | 0.562 | -8.75 | fail |
| C | `stable_causal` | `true` | `true` | 20 | 0.550 | 26.72 | 16 | 0.438 | -27.09 | fail |
| D | `stable_causal` | `true` | `false` | 20 | 0.550 | 26.72 | 16 | 0.438 | -27.09 | fail |

Any-source artifacts:

- Variant A: [action_ranker_xgb_variant_a_full_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_a_full_any_labelfix_2026-04-06.pkl)
- Variant B: [action_ranker_xgb_variant_b_stable_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_b_stable_any_labelfix_2026-04-06.pkl)
- Variant C: [action_ranker_xgb_variant_c_stable_causal_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_c_stable_causal_any_labelfix_2026-04-06.pkl)
- Variant D: [action_ranker_xgb_variant_d_stable_causal_noside_any_labelfix_2026-04-06.pkl](/home/jacobw/trading/repos/quantstack/alpha/models/action_ranker_xgb_variant_d_stable_causal_noside_any_labelfix_2026-04-06.pkl)
- machine-readable matrix: [2026-04-06_any_source_training_matrix.csv](/home/jacobw/trading/repos/quantstack/alpha/output/ml_action_ranker_matrix/2026-04-06_any_source_training_matrix.csv)

Interpretation:

- the broader `any` source matrix materially expanded data versus the `features`-only matrix, but every variant failed the pre-forward test edge screen
- Variant A and C had positive validation edge but negative test edge, consistent with validation overfit rather than generalization
- Variant B had higher test precision than A/C/D but still negative test edge, so it is not a promotion candidate
- Variant C and D were identical on this slice, so side-aware context did not add value
- no broader `any` artifact should be frozen-forward replayed yet; that would be tuning around a failed internal screen

## Recommendation

- do not use the earlier non-`labelfix` artifacts or cache for any conclusion
- treat Variant A as the only compact feature-source candidate that passed the internal screen, but reject it for promotion on the authoritative frozen replay
- reject all four broader `any`-source artifacts for promotion because each failed the pre-forward test edge screen
- do not promote Variant A because it missed the frozen OOS PnL/PF gate versus the repaired production baseline
- do not promote `gate_a` for Variant A
- next step:
  - keep the repaired production artifact as the comparison baseline
  - investigate why raw-source expansion makes pre-forward edge negative before adding model complexity
  - only revisit gating after a broader artifact passes the frozen OOS PnL/PF gate; lower trade frequency can be acceptable when PnL/PF improves
