# ML Master Research And Development Plan

## Execution Status

Last updated: `2026-03-21`

Program state:

- status: `in_progress`
- active baseline: `models/h60_two_stage_logistic_v4_2026-03-15.pkl`
- active policy: `threshold 0.40`, `time_only / 5m`
- clean OOS control: `18` trades, `-$31.41` combined across the two current clean windows
- target trade budget: `3-5` trades/day` (secondary diagnostic, no longer primary gate)`
- current bottleneck: `robustness of the first profitable action-ranking candidate`, especially weak `w1`

### Workstream Status

- Phase 0. Research platform and measurement hardening: `partially_complete`
- Phase 1. Data coverage, labeling, and training-live alignment: `in_progress`
- Phase 2. Context analysis: `not_started`
- Phase 3. Entry analysis: `not_started`
- Phase 4. Direction analysis: `not_started`
- Phase 5. Duration analysis: `not_started`
- Phase 6. Exit analysis: `deferred`
- Phase 7. Model family roadmap: `in_progress`
- Phase 8. Promotion and productionization: `not_started`

### Current Deliverables

- control model report: `output/ml_training_reports/h60_two_stage_logistic_v4_2026-03-15/training_report.md`
- clean OOS w1: `output/ml_report_2026-03-06_to_2026-03-11_two_stage_logistic_v4_t040_tl05.json`
- clean OOS w2: `output/ml_report_2026-03-12_to_2026-03-13_two_stage_logistic_v4_t040_tl05.json`
- combined forensic: `output/ml_v4_combined_oos_forensic_2026-03-15/report.md`
- Phase 1 runner: `scripts/run_ml_side_threshold_matrix.py`
- Phase 2 runner: `scripts/run_ml_long_side_regime_report.py`
- action-edge replay report: `output/ml_action_edge_ranker_budget_matrix_2026-03-18/report.md`
- XGBoost action benchmark report: `output/ml_training_reports/action_ranker_xgb_2026-03-19/training_report.md`
- XGBoost action forensic report: `output/ml_action_ranker_xgb_forensic_2026-03-19/report.md`
- XGBoost gated replay report: `output/ml_action_ranker_xgb_budget_matrix_2026-03-20_weak_context_gate_a/report.md`
- XGBoost gate sensitivity report: `output/ml_action_ranker_xgb_gate_sensitivity_2026-03-20/report.md`
- XGBoost gated full-grid report: `output/ml_action_ranker_xgb_budget_matrix_2026-03-20_gate_a_full_grid/report.md`
- XGBoost promotion forensic report: `output/ml_action_ranker_xgb_promotion_forensic_2026-03-21/report.md`
- XGBoost adjacent OOS report: `output/ml_action_ranker_xgb_adjacent_oos_2026-03-16_gate_a_top4_long2/report.md`
- XGBoost forward block report: `output/ml_action_ranker_xgb_forward_block_2026-03-16_to_2026-03-20_gate_a_top4_long2/report.md`
- replay-quality overlay target artifact: `models/action_quality_logistic_2026-03-21_replay.pkl` (`in_progress`)
- replay-quality overlay target report: `output/ml_training_reports/action_quality_logistic_2026-03-21_replay/training_report.md` (`in_progress`)
- causal 8-hold action-ranker target artifact: `models/action_ranker_xgb_causal8_2026-03-21.pkl` (`queued`)
- causal 8-hold action-ranker target report: `output/ml_training_reports/action_ranker_xgb_causal8_2026-03-21/training_report.md` (`queued`)

### In-Flight Implementation Notes

- reusable Phase 1 and Phase 2 runners are implemented
- compact-cache training load now repairs `source_type` from numeric source flags when needed
- `v5` feature plumbing is implemented via side-aware context interaction features shared by training and live scoring
- the first linear action-edge replay is now complete and failed its exact OOS gate
- CatBoost and LightGBM are not installed in the local venv; the next executable tree benchmark branch is XGBoost
- tree-based action-model training support is now the active implementation branch
- best-config forensic export for the XGBoost leader is now implemented via `scripts/run_ml_action_ranker_forensic_report.py`
- the quality overlay now shares a compact causal OHLCV/VWAP subset across live scoring, replay-built rows, and forensic-fast rows
- the replay-quality branch was restarted after an interrupted run and remains the active execution branch until `models/action_quality_logistic_2026-03-21_replay.pkl` lands
- the causal action-ranker branch now has an explicit launch target: `xgb_logistic + causal-price-features + hold buckets 2,3,4,5,6,8,10,12`

### Verification

- `.venv/bin/python -m pytest tests/test_ml_training.py tests/test_ml_research_scripts.py -q`
- `.venv/bin/python -m py_compile scripts/run_ml_side_threshold_matrix.py scripts/run_ml_long_side_regime_report.py scripts/train_ml_model.py`
- `.venv/bin/python -m pytest tests/test_action_ranker.py tests/test_ml_research_scripts.py -q`
- `.venv/bin/python -m py_compile src/models/action_ranker.py scripts/train_ml_action_ranker.py scripts/run_ml_action_ranker_forensic_report.py`

### Latest Research Status

- Phase 1 side-threshold matrix: `completed`
- Phase 1 artifact root: `output/ml_v4_side_threshold_matrix_2026-03-15`
- Phase 1 best config: `long 0.45 / short 0.35 / time_only 5m`
- Phase 1 best result: `1` trade, `+$4.38`, `0.004%`
- Phase 1 conclusion:
  - tighter long thresholds can suppress the later-window loss
  - but they do so by collapsing frequency to `0.125` trades/day
  - this fails the trade-budget objective and should not be promoted as the operating policy
  - implication: side-thresholding alone is not sufficient; context-aware long filtering remains necessary
- Phase 2 long-side regime comparison: `completed`
- Phase 2 artifact root: `output/ml_v4_long_side_regime_2026-03-15`
- Phase 2 cohort counts:
  - all trades: `18`
  - all longs: `17`
  - `w1` winning longs: `5`
  - `w2` losing longs: `5`
- Phase 2 top differences:
  - `session_bucket`
  - `depth_imb_k_mean_60s`
  - `depth_imb_k_mean_10s`
- Phase 2 conclusion:
  - later-window losing longs differ primarily by timing within the session and weaker / different depth-imbalance context
  - the next model iteration should focus on context-conditioned long suppression rather than more threshold tuning
- `v5` implementation status:
  - side-aware context feature augmentation is now available in `src/features/ml_features.py`
  - training can opt into those features via `--side-aware-context-features`
  - first `v5` candidate trained and was rejected on clean OOS for over-suppressing activation
  - next execution step is a softer stage-scoped side-aware variant

### Latest Model Iteration Status

- `v5` artifact: `models/h60_two_stage_logistic_v5_2026-03-16.pkl`
- `v5` training report: `output/ml_training_reports/h60_two_stage_logistic_v5_2026-03-16/training_report.md`
- `v5` training summary:
  - mean val accuracy: `0.736`
  - train/val gap: `-0.013`
  - test accuracy: `0.480`
  - recommended threshold: `0.35`
- `v5` clean OOS:
  - `2026-03-06` to `2026-03-11`: `0` trades, `0.00%`
  - `2026-03-12` to `2026-03-13`: `1` trade, `-0.02%`
- `v5` conclusion:
  - later-window bad longs were suppressed
  - overall activation collapsed too far
  - this candidate fails the trade-budget objective and is rejected
- `v5b` artifact: `models/h60_two_stage_logistic_v5b_2026-03-16.pkl`
- `v5b` training report: `output/ml_training_reports/h60_two_stage_logistic_v5b_2026-03-16/training_report.md`
- `v5b` design:
  - same side-aware context features as `v5`
  - side-aware features restricted to stage 2 only
- `v5b` clean OOS:
  - `2026-03-06` to `2026-03-11`: `19` trades, `-0.05%`, PF `0.70`
  - `2026-03-12` to `2026-03-13`: `15` trades, `-0.07%`, PF `0.46`
- `v5b` conclusion:
  - stage-scoping restored activation
  - later-window economics degraded further
  - side-aware logistic refinements are no longer the primary branch
  - next branch should move toward explicit trade-budget allocation / ranking rather than more threshold-only tuning
- ranking / trade-budget branch:
  - durable runner added: `scripts/run_ml_topk_budget_backtest.py`
  - first design: exact ML scoring path + daily top-K allocation + long-cap control
  - initial comparison grid:
    - `top_k in {3,4,5}`
    - `max_longs_per_day in {1,2,3}`
    - fixed baseline management: `time_only / 5m`
  - matrix artifact: `output/ml_topk_budget_matrix_2026-03-16_v5b`
  - best config:
    - `top_k=3`
    - `max_longs_per_day=1`
    - `11` trades
    - `1.83` trades/day
    - `-0.016%`
    - PF `0.69`
  - best higher-budget variants:
    - `top_k=4, max_longs=1`: `12` trades, `2.00` trades/day, `-0.030%`, PF `0.54`
    - `top_k=5, max_longs=1`: `13` trades, `2.17` trades/day, `-0.033%`, PF `0.52`
  - conclusion:
    - explicit budgeting improved stability versus unrestricted thresholding
    - but the heuristic top-K allocator still fails the `3-5` trades/day objective
    - loosening the long cap worsens economics without materially improving frequency
    - heuristic top-K selection is not the final method and is rejected as the primary path
    - next branch should move to learned action scoring / ranking rather than confidence-only ranking
- learned action-scoring / ranking branch:
  - action model module added: `src/models/action_ranker.py`
  - training entry point added: `scripts/train_ml_action_ranker.py`
  - exact OOS budget runner added: `scripts/run_ml_action_ranker_budget_backtest.py`
  - first implementation:
    - per-action profitable-after-cost logistic scoring
    - actions over `(side, hold)` with hold buckets `3m, 5m, 8m, 12m`
    - exact daily top-K replay with hold-specific time-only exits
  - first `v1` result:
    - artifact: `models/action_ranker_logistic_2026-03-17.pkl`
    - best economic config: `top_k=3, max_longs=3`, `11` trades, `1.83` trades/day, `-0.013%`, PF `0.72`
    - best trade-budget config: `top_k=4, max_longs=1`, `18` trades, `3.0` trades/day, `-0.025%`, PF `0.67`
    - conclusion:
      - this is the first branch to hit the trade-budget objective with a learned allocator
      - still slightly negative, so not promotable
  - stricter `v2` quality variant:
    - artifact: `models/action_ranker_logistic_v2_2026-03-18.pkl`
    - training diagnostics worsened materially
    - exact OOS on prior best config: `0` trades, `0.00%`
    - conclusion:
      - hardening binary action labels further collapsed activation
      - variant rejected
- action-edge regression / ranking branch:
  - same `(side, hold)` action set
  - objective changed from binary profitable/not-profitable to continuous post-cost edge prediction
  - artifact: `models/action_edge_ranker_ridge_2026-03-18.pkl`
  - training report: `output/ml_training_reports/action_edge_ranker_ridge_2026-03-18/training_report.md`
    - training diagnostics:
      - validation precision: `0.185`
      - validation mean edge bps: `-23.47`
      - test precision: `0.250`
      - test mean edge bps: `-46.43`
    - exact OOS replay artifact: `output/ml_action_edge_ranker_budget_matrix_2026-03-18`
    - exact OOS best config:
      - `top_k=3`
      - `max_longs=3`
      - `17` trades
      - `2.83` trades/day
      - `-$59.91`
      - PF `0.48`
    - conclusion:
      - the first linear edge-regression scorer is too weak on exact OOS replay
      - it misses the `3-5` trades/day target even before economics
      - this branch is rejected as a promotable candidate
      - keep the artifact as a negative control, not as an active branch
- next active branch:
  - tree-based action-model benchmark on the same discrete `(side, hold)` action space
  - preferred roadmap order remains `CatBoost -> LightGBM -> XGBoost`
  - local environment status currently forces `XGBoost` as the executable benchmark
  - immediate objective:
    - add XGBoost profitable-after-cost action training to the existing action-ranker pipeline
    - run the first narrow benchmark before deciding whether to install additional tree libraries
  - first XGBoost benchmark status:
    - artifact: `models/action_ranker_xgb_2026-03-19.pkl`
    - training report: `output/ml_training_reports/action_ranker_xgb_2026-03-19/training_report.md`
    - validation top-k precision: `0.481`
    - validation mean edge bps: `+5.75`
    - test top-k precision: `0.375`
    - test mean edge bps: `-3.23`
  - first XGBoost exact OOS replay:
    - artifact root: `output/ml_action_ranker_xgb_budget_matrix_2026-03-19`
    - best config:
      - `top_k=5`
      - `max_longs_per_day=1`
      - `22` trades
      - `3.67` trades/day
      - `+$31.42`
      - PF `1.19`
      - `trade_budget_pass=true`
    - window split:
      - `w1`: `14` trades, `-$31.14`, PF `0.73`
      - `w2`: `8` trades, `+$62.56`, PF `2.34`
    - interpretation:
      - this is the first branch to clear combined OOS profitability, PF, and trade-budget gates
      - it is not yet promotable as the operating policy because performance is regime-imbalanced across windows
  - XGBoost forensic status:
    - artifact root: `output/ml_action_ranker_xgb_forensic_2026-03-19`
    - selected actions: `26`
    - completed trades: `22`
    - `w1` losing trades: `6`
    - `w2` winning trades: `3`
    - top cohort differences:
      - `pressure_k`
      - `spread`
      - `depth_imb_k`
    - cohort read:
      - weak `w1` losers cluster around strongly negative / zero `pressure_k`, negative `depth_imb_k`, and near-minimum spreads
      - strong `w2` winners occur in materially different pressure / spread / imbalance context
    - next execution step:
      - keep the XGBoost model fixed
      - add the smallest possible context gate on top of the existing best config using `pressure_k`, `spread`, and `depth_imb_k`
      - rerun the same exact OOS matrix before opening a new model family branch
  - first weak-context gate test:
    - artifact root: `output/ml_action_ranker_xgb_budget_matrix_2026-03-20_weak_context_gate_a`
    - gate:
      - reject only when `pressure_k <= 0.0`, `spread <= 0.03`, and `depth_imb_k <= -0.02`
    - replay config:
      - fixed winner only: `top_k=5`, `max_longs_per_day=1`, `min_score=0.5`
    - exact OOS result:
      - `20` trades
      - `3.33` trades/day
      - `+$83.74`
      - PF `1.95`
      - `trade_budget_pass=true`
    - window split:
      - `w1`: `12` trades, `+$25.20`, PF `1.54`
      - `w2`: `8` trades, `+$58.54`, PF `2.39`
    - interpretation:
      - the first minimal context gate materially improves robustness while staying inside the trade-budget target
      - the leader is now positive in both windows, which is the first convincing robustness improvement in this branch
    - next execution step:
      - keep the XGBoost model fixed
      - run gate-sensitivity around this candidate rather than changing model family
      - test nearby thresholds around the same weak-context rule before widening the config grid
  - gate-sensitivity status:
    - artifact root: `output/ml_action_ranker_xgb_gate_sensitivity_2026-03-20`
    - fixed replay config:
      - `top_k=5`
      - `max_longs_per_day=1`
      - `min_score=0.5`
    - tested variants:
      - `conservative`: `pressure_k <= -100.0`, `spread <= 0.02`, `depth_imb_k <= -0.10`
        - `22` trades, `+$31.42`, PF `1.19`, `3.67` trades/day
        - `w1`: `-$31.14`, PF `0.73`
        - `w2`: `+$62.56`, PF `2.34`
      - `permissive`: `pressure_k <= 0.0`, `spread <= 0.05`, `depth_imb_k <= 0.0`
        - `19` trades, `+$51.96`, PF `1.46`, `3.17` trades/day
        - `w1`: `+$2.05`, PF `1.03`
        - `w2`: `+$49.91`, PF `1.99`
    - interpretation:
      - the original anchor gate remains the best tested variant so far
      - tightening the gate too far collapses back toward the ungated weak `w1` profile
      - loosening the gate keeps both windows positive but gives back a meaningful amount of edge
    - current recommendation:
      - keep `gate_a` as the live research leader
      - if more sensitivity work is needed, search only in a narrow neighborhood around the anchor rather than making broader gate changes
  - gated full-grid status:
    - artifact root: `output/ml_action_ranker_xgb_budget_matrix_2026-03-20_gate_a_full_grid`
    - gate fixed at `gate_a`:
      - reject only when `pressure_k <= 0.0`, `spread <= 0.03`, and `depth_imb_k <= -0.02`
    - configs tested: `9/9`
    - best raw-economic config:
      - `top_k=3`, `max_longs_per_day=1`
      - `16` trades
      - `+$96.21`
      - PF `2.27`
      - `2.67` trades/day
      - fails the trade-budget gate
    - best trade-budget-passing config:
      - `top_k=4`, `max_longs_per_day=2`
      - `21` trades
      - `+$89.29`
      - PF `1.94`
      - `3.5` trades/day
      - `trade_budget_pass=true`
    - window split for the new best budget-passing config:
      - `w1`: `13` trades, `+$32.68`, PF `1.67`
      - `w2`: `8` trades, `+$56.61`, PF `2.23`
    - interpretation:
      - fixing the context gate and rerunning the full budget grid improved the promoted candidate further
      - the best promotable configuration now shifts from `5,1` to `4,2`
      - loosening long capacity beyond this point degrades economics materially
    - current recommendation:
      - promote `gate_a + top_k=4 + max_longs_per_day=2` as the new research leader
      - next step should be promotion-style validation and concentration checks rather than more immediate gate tuning
  - promotion validation status:
    - exact promotion forensic:
      - artifact root: `output/ml_action_ranker_xgb_promotion_forensic_2026-03-21`
      - fixed config:
        - `gate_a + top_k=4 + max_longs_per_day=2 + min_score=0.5`
      - counts:
        - `22` selected actions
        - `21` completed trades
        - `633` gate rejections
      - concentration read:
        - `AAOI` contributes `+$95.51`
        - `USO` contributes `-$47.42`
        - strongest positive day is `2026-03-12` at `+$83.15`
        - weakest days are `2026-03-11` at `-$26.89` and `2026-03-13` at `-$26.54`
      - interpretation:
        - the leader is not a one-trade fluke
        - symbol-level concentration in this sample is descriptive only
        - because the system is capped at `3` L2 tickers per day by subscription limits, the relevant risk is not repeated-ticker dependence
        - the relevant risk is whether the frozen setup keeps selecting and sizing well inside each daily SIP-selected 3-name set as those names rotate
    - adjacent OOS extension:
      - artifact root: `output/ml_action_ranker_xgb_adjacent_oos_2026-03-16_gate_a_top4_long2`
      - frozen config:
        - same model
        - same `gate_a`
        - same `top_k=4`
        - same `max_longs_per_day=2`
      - result on `2026-03-16`:
        - `3` trades
        - `+$85.53`
        - PF `999.0`
        - `3.0` trades/day
        - `trade_budget_pass=true`
      - interpretation:
        - the frozen leader generalized positively to the next available adjacent date
        - this is the strongest validation signal so far for the branch
    - broader forward block:
      - artifact root: `output/ml_action_ranker_xgb_forward_block_2026-03-16_to_2026-03-20_gate_a_top4_long2`
      - frozen config:
        - same model
        - same `gate_a`
        - same `top_k=4`
        - same `max_longs_per_day=2`
      - result on `2026-03-16` through `2026-03-20`:
        - `11` trades
        - `+$28.46`
        - PF `1.30`
        - `2.2` trades/day
        - `trade_budget_pass=false`
      - interpretation:
        - the frozen leader stayed positive across the available forward block
        - but trade frequency fell below the target on this block, so the promotion candidate is economically intact but not yet fully stable on the trade-budget objective
    - model-learning conclusion to preserve:
      - the post-hoc weak-context analysis is informative because it exposed a real failure regime in low-quality microstructure context
      - but the exact hard gate is at meaningful risk of overfit because it was tuned after inspecting the original OOS failures
      - descriptive ticker-level outcomes should not drive new rules in this system because the daily L2 universe is capped at `3` SIP-selected names and rotates day to day
      - the next model-improvement branch worth testing is a second accept/reject quality model on top of the naked action-ranker, compared directly against the naked model
    - accept/reject quality branch spec:
      - purpose:
        - test whether the weak-context failure mode can be learned by a second model instead of hand-coded as a fixed gate
        - compare `naked action-ranker` versus `action-ranker + accept/reject quality layer`
      - unit of prediction:
        - one row per top-ranked candidate action after the naked action-ranker and budget policy propose it
      - target:
        - binary accept/reject label based on realized post-cost trade quality for the proposed action
        - initial version should use a simple label such as `trade pnl > 0`
        - optional harder variant can require pnl to clear a small positive buffer after costs
      - training data:
        - build candidate rows from historical replays of the naked action-ranker under the fixed promoted budget policy
        - include both accepted winners and accepted losers from the rotating daily SIP-selected 3-name universe
        - do not use ticker identity as a feature
      - feature set:
        - candidate `rank_score`
        - action metadata: side and scheduled hold bucket
        - regime/context features already shown to matter: `pressure_k`, `spread`, `depth_imb_k`, `session_bucket`
        - optionally include a compact subset of rolling context features already present in live scoring
      - first model family:
        - start with a small calibrated logistic model or shallow tree model
        - keep complexity below the naked action-ranker to reduce overfit risk
      - evaluation protocol:
        - freeze the naked action-ranker, budget policy, and replay path
        - compare two systems only:
          - naked action-ranker
          - naked action-ranker plus accept/reject layer
        - judge on fresh forward dates, not on the March tuning window
        - primary gates remain combined pnl, profit factor, and `3-5` trades/day
      - success condition:
        - quality layer improves pnl and/or PF without collapsing trade frequency below the budget target
      - failure condition:
        - quality layer simply recreates the hand-tuned gate on the March window without holding up on fresh forward dates
    - current recommendation:
      - prioritize PF and net `$` pnl over the hard `3-5` trades/day guideline; frequency is now indicative, not the primary gate
      - keep `gate_a + top_k=4 + max_longs_per_day=2` as the active promotion candidate
      - first naked-vs-quality comparison is now complete on the `2026-03-16` to `2026-03-20` forward block
      - naked forward baseline artifact root: `output/ml_action_ranker_xgb_forward_block_2026-03-16_to_2026-03-20_naked_top4_long2`
        - `11` trades, `+$19.07`, PF `1.18`, `2.2` trades/day
      - first quality-layer forward comparison artifact root: `output/ml_action_ranker_xgb_forward_block_2026-03-16_to_2026-03-20_quality_forensic_fast_top4_long2`
        - quality artifact: `models/action_quality_logistic_2026-03-21.pkl`
        - quick-training report: `output/ml_training_reports/action_quality_logistic_2026-03-21_forensic_fast/training_report.md`
        - `11` trades, `+$57.02`, PF `1.69`, `2.2` trades/day
      - comparison read:
        - the first quality layer improved forward pnl and PF materially versus the naked model without further reducing trade count
        - the low `2.2` trades/day read is now secondary; by the updated objective hierarchy, this still qualifies as a major economic improvement
        - this first result is directionally positive, not final proof, because the quality artifact was trained from the March forensic export as a fast branch check rather than the slower replay-built candidate dataset
      - next comparison branch should extend this quality-layer test with replay-built training rows once the slower training path is stabilized
      - a new causal feature branch is now started:
        - add causal OHLCV/VWAP/trend-derived features to the shared live-aligned ML path
        - expand hold buckets from `4` to `8`: `2,3,4,5,6,8,10,12`
      - implementation update:
        - shared quality-layer plumbing now carries compact causal OHLCV/VWAP features including `dist_vwap_bps`, `hl_range_pct`, `oc_change_pct`, `volume_rel_20`, `atr_pct`, `position_in_range`, `rsi`, `bb_position`, `ret_3`, and `ret_10`
        - focused verification passed on the relevant helper and backtest paths via `.venv/bin/python -m pytest -q tests/test_action_ranker.py tests/test_ml_research_scripts.py tests/test_backtest.py`
      - current execution status:
        - replay-built quality training is the active run and should produce `models/action_quality_logistic_2026-03-21_replay.pkl`
        - once that artifact lands, rerun the forward comparison against the frozen naked leader on `2026-03-16` to `2026-03-20`
        - the next queued branch after that comparison is the causal XGBoost action-ranker with the full `2,3,4,5,6,8,10,12` hold grid
      - any quality layer should use regime/context features, not ticker identity, and must be judged on fresh forward dates rather than more threshold-fitting on the March window
    - compact summary to preserve:
      - promoted fixed setup is `action_ranker_xgb_2026-03-19.pkl + gate_a + top_k=4 + max_longs_per_day=2`
      - promoted in-sample replay: `21` trades, `+$89.29`, PF `1.94`, `3.5` trades/day
      - adjacent day `2026-03-16`: `3` trades, `+$85.53`, `3.0` trades/day
      - forward block `2026-03-16` to `2026-03-20`: `11` trades, `+$28.46`, PF `1.30`, `2.2` trades/day
      - naked forward baseline on the same dates: `11` trades, `+$19.07`, PF `1.18`, `2.2` trades/day
      - first quality-layer forward comparison on the same dates: `11` trades, `+$57.02`, PF `1.69`, `2.2` trades/day
      - conclusion: the first quality layer improved economics versus the naked model, and the next active branch is to stabilize that overlay while testing the causal OHLCV/VWAP feature family over an expanded `8`-duration action grid

## Purpose

Define the full research and development program from the current `v4` baseline to a
production-worthy, profitable ML trading method.

This plan is not limited to one model family. It covers:

- data and evaluation integrity
- context analysis
- entry analysis
- direction analysis
- duration analysis
- exit analysis
- model families from calibrated linear baselines through tree models, ranking models,
  action-selection models, and bandit / offline-RL style methods
- explicit success and rejection gates at each stage

## Operating Constraints

These are hard constraints unless changed deliberately:

- dynamic SIP-selected universe remains intact
- no ticker exclusions
- target frequency is `3-5` trades per day on clean OOS
- avoid broad TP/SL tuning until entry quality is demonstrably strong
- all strategy judgments must be based on clean OOS windows using the fresh daily runner
- evaluation must include realistic costs, slippage, integer sizing, and causal L2 access

## Current Baseline

Current primary candidate:

- model: `models/h60_two_stage_logistic_v4_2026-03-15.pkl`
- entry threshold: `0.40`
- exit family: `time_only`
- hold: `5m`

Current evidence:

- training rows: `36,620`
- dates: `33`
- symbols: `53`
- model family: `two_stage_logistic`
- mean validation accuracy: `0.728`
- test accuracy: `0.479`

Clean OOS:

- `2026-03-06` to `2026-03-11`: `8` trades, `+0.006%`, PF `1.14`
- `2026-03-12` to `2026-03-13`: `10` trades, `-0.037%`, PF `0.63`
- combined: `18` trades, `-$31.41`, avg `-$1.75/trade`, win rate `55.6%`

Interpretation:

- frequency is already near the target at `3.0` trades/day across the clean OOS days
- the blocker is not trade count
- the blocker is unstable trade quality, especially later-window long trades

## Core Diagnosis

The program has already moved past the original infrastructure failures.

What has been solved:

- symbol holdout leakage was fixed
- invalid tail-label evaluation was fixed
- DST/time conversion issues were fixed
- shared-engine state contamination in OOS backtesting was fixed
- live-path feature corruption and missing-feature silent suppression were fixed
- the model now trades on clean OOS under a trustworthy runner

What remains:

- later OOS regime is still economically weak
- long-side trade quality is unstable
- current long-heavy behavior is not yet proven to be a neutral structural edge
- current thresholding and action definition are too coarse
- current targets emphasize classification quality more than post-cost expected value
- training/live alignment still has meaningful gaps, including `source_type='unknown'`

## End-State Vision

The final profitable method should look like a layered decision stack, not a single threshold on a
single classifier.

Target end-state architecture:

1. `Context gate`
- decides whether the microstructure regime is tradable now

2. `Action scorer`
- scores all candidate actions:
  - `no trade`
  - `long 3m`
  - `long 5m`
  - `long 8m`
  - `long 12m`
  - `short 3m`
  - `short 5m`
  - `short 8m`
  - `short 12m`

3. `Trade budget allocator`
- enforces `3-5` trades/day by ranking actions and selecting only the best candidates above a floor

4. `Execution policy`
- baseline remains `time_only`
- optional market-based kill switch only after entry quality is proven

5. `Risk and diagnostics layer`
- tracks side stability, context drift, trade concentration, and performance decay

## Global Research Principles

1. Optimize for post-cost economics, not only classification accuracy.
2. Treat `3-5` trades/day as a design target, not as something to force with loose thresholds.
3. Prefer action ranking over unbounded threshold-triggering.
4. Separate context, entry, direction, duration, and exit logic.
5. Advance only one complexity layer at a time.
6. Reject approaches early if they fail clear gates.
7. Do not promote any approach until it is stable across multiple clean OOS windows.
8. Treat any observed long or short bias as unproven until it survives regime-conditioned testing.

## Program Structure

The program will progress through eight workstreams.

1. Data and integrity
2. Context and regime analysis
3. Entry and direction analysis
4. Duration and exit analysis
5. Baseline model family expansion
6. Ranking and action-selection models
7. Bandit / offline-RL methods
8. Promotion, monitoring, and productionization

## Common Evaluation Framework

Every candidate must be evaluated under the same framework.

### Core metrics

- total PnL
- total return pct
- profit factor
- win rate
- expectancy per trade
- max drawdown
- number of trades
- trades per day
- average hold time
- side attribution
- symbol concentration
- window-by-window attribution

### Required slices

- by date
- by symbol
- by side
- by session bucket
- by source type
- by volatility regime
- by spread regime
- by opening vs midday vs late session

### Trade budget metrics

- mean trades/day
- median trades/day
- pct of days within `3-5` trade target
- pct of days below `2` trades
- pct of days above `6` trades

### Economic quality metrics

- average PnL/trade
- expected net edge after costs
- ratio of gross edge to costs
- adverse excursion vs favorable excursion

### Side-neutrality metrics

- long trades/day
- short trades/day
- long PF
- short PF
- long expectancy
- short expectancy
- fraction of OOS PnL contributed by longs vs shorts
- regime-conditioned long and short activation

## Global Gates

These apply across the full program.

### Integrity gate

A candidate is invalid if any of the following are true:

- forward-look bias is present
- backtest path differs from live scoring path
- stale or missing L2 is silently converted into valid features
- fresh daily runner and exact-score audit disagree materially
- clean OOS artifacts cannot be reproduced

### Baseline-improvement gate

A candidate is only considered an improvement if:

- combined clean OOS PnL is better than the current control
- trade frequency stays within the target regime, or deliberately improves toward it
- the improvement is not concentrated in one symbol or one day only

### Production-readiness gate

No strategy is promotable unless all are true:

- combined clean OOS return is non-negative
- combined PF >= `1.10`
- max drawdown is acceptable relative to return
- mean trades/day is between `3` and `5`
- at least `60%` of OOS days are inside the target trade-count range
- no single side or symbol dominates losses
- no apparent directional bias remains unexplained by regime-conditioned evidence

## Rejection Rules

Reject a candidate or branch immediately if:

- it needs threshold loosening to the point that PF collapses
- it produces zero or near-zero activation on clean OOS
- it improves training metrics but not clean OOS economics
- it requires ticker filtering
- it depends on exit tuning to rescue clearly bad entries
- it materially increases complexity without clear OOS gain
- it appears profitable only because one direction dominates in drift-favorable windows

## Phase 0. Research Platform And Measurement Hardening

### Objective

Make sure all future research is comparable, reproducible, and traceable.

### Tasks

- finalize the authoritative evaluation runner
- standardize clean OOS windows and artifact locations
- standardize by-window, by-side, by-symbol outputs
- add trade-budget reporting to every run
- make all matrix and sweep runners reuse the exact same signal path as the daily runner

### Success gate

- any baseline rerun reproduces prior results within rounding tolerance
- matrix baseline equals authoritative single-config runner

### Rejection gate

- any new analysis path that cannot reproduce the baseline is not used for decisions

## Phase 1. Data Coverage, Labeling, And Training-Live Alignment

### Objective

Reduce train/live mismatch before broader model search.

### Known problems

- `source_type='unknown'` is too large a share of rows
- training objective still leans too heavily on classification labels
- not all candidate rows reflect true live eligibility and costs

### Tasks

1. Fix source completeness
- eliminate or explain `unknown` source rows
- make source type explicit and reliable for every aligned row

2. Rebuild live-aligned datasets
- keep only rows that could be `_ml_features_ready` in live scoring
- preserve side, session, regime, source, and cost context

3. Add action labels
- realized net PnL by hold bucket
- realized MFE / MAE
- profitable-after-cost indicator
- best action label per bar

4. Add day-level metadata
- session regime
- realized volatility regime
- spread regime
- opening stress regime

### Success gate

- no material missing source classification
- dataset supports action-based modeling cleanly
- train/live row contract is explicit and auditable

### Rejection gate

- if a proposed label cannot be scored consistently in live evaluation, do not use it

## Phase 2. Context Analysis

### Objective

Understand when the strategy should trade, independent of exact direction.

### Questions to answer

- which contexts produce positive net edge?
- which contexts admit bad longs in later OOS windows?
- which contexts support short entries more reliably?
- is any long or short bias structural, or only present in specific market regimes?

### Context features to analyze

- session bucket
- minutes since open
- spread level
- spread z-score
- spread volatility
- micro-off level
- micro-off volatility
- depth imbalance regime
- pressure regime
- snapshot freshness
- source type
- realized short-horizon volatility
- symbol liquidity proxy

### Methods

- context-conditioned win-rate tables
- context-conditioned net PnL/trade tables
- partial dependence style analysis for tabular models
- SHAP or equivalent local explanations for trees only after baseline quality is established

### Outputs

- context scorecard
- losing-context blacklist candidates
- positive-context whitelist candidates
- regime-conditioned long/short attribution table

### Success gate

- identify 2-5 context dimensions that explain later-window degradation
- determine whether current long bias is regime-conditioned or plausibly structural

### Rejection gate

- do not handcraft hard filters unless the context effect is strong and stable across windows
- do not accept a persistent long bias as neutral until it survives up, down, and mixed-regime checks

## Phase 3. Entry Analysis

### Objective

Replace pure confidence-threshold entry with expected-edge-aware entry.

### Research directions

1. `Trade / no-trade` probability
2. Expected net return regression
3. Profitable-after-cost classification
4. Ranking score for candidate bars

### Candidate targets

- binary profitable after costs at each hold bucket
- expected net return
- expected return minus estimated slippage / spread cost
- expected utility with downside penalty

### Entry-policy forms

- simple threshold
- top-K per day
- top-K per symbol-day
- top-K with minimum spacing / cooldown
- top-K after context gate

### Success gate

- entry layer alone gets close to `3-5` trades/day without needing loose thresholds
- post-cost expectancy improves over the current baseline

### Rejection gate

- if a method only works by drastically reducing trade count below `2/day`, reject it

## Phase 4. Direction Analysis

### Objective

Make the long/short decision explicitly asymmetric.

### Why

Current evidence points to long-side instability, especially in later OOS windows.
Current evidence does not justify assuming long bias is a general market property.

### Candidate approaches

1. Separate long and short thresholds on the same model
2. Side-specific calibration for stage 2
3. Separate long and short direction models
4. Side-specific loss weighting
5. Side-specific context gate

### Key analyses

- long vs short hit rate by regime
- long vs short expectancy by regime
- later-window long false positives
- short scarcity vs short quality
- up-drift vs down-drift vs flat-day long/short behavior
- open-driven vs midday-driven long/short behavior

### Success gate

- later-window long losses shrink materially
- short activation is preserved where clean
- any remaining directional bias is explained by regime evidence rather than assumed as universal

### Rejection gate

- reject any side-aware tweak that improves one window only by collapsing overall activation

## Phase 5. Duration Analysis

### Objective

Turn hold time into a learned decision instead of a fixed parameter.

### Candidate hold buckets

- `3m`
- `5m`
- `8m`
- `12m`

### Methods

1. fixed hold comparison
2. hold-bucket classifier
3. expected-value-per-hold regressor
4. action ranking across `(side, hold)`

### Target questions

- is there one dominant hold for all contexts?
- does hold depend on side?
- does hold depend on context or source type?

### Success gate

- hold-aware modeling improves net OOS economics without pushing trades/day outside target

### Rejection gate

- if hold choice adds complexity but no stable OOS gain, keep fixed `5m`

## Phase 6. Exit Analysis

### Objective

Improve exits only after entry and duration quality are strong.

### Exit families

1. `time_only`
2. `vol_scaled_tp_sl`
3. `market_based`

### Market-based exit candidates

- opposite-side edge overtakes current-side edge
- trade score falls below maintenance threshold
- micro-off flips materially against position
- spread blows out beyond regime-normalized threshold
- L2 freshness degrades

### Guidance

- `time_only` remains the control
- do not begin with broad TP/SL search
- market-based exits are preferred over static TP/SL if entry is already good

### Success gate

- exit override improves PnL and PF without reducing activation materially

### Rejection gate

- if an exit method only appears helpful because entries are bad, reject it

## Phase 7. Model Family Roadmap

This is the order in which model classes should be explored.

### Track A. Calibrated linear baselines

Purpose:

- maintain a transparent baseline
- sanity-check feature usefulness
- set a floor for more complex models

Models:

- logistic regression
- elastic-net logistic
- side-specific logistic
- profitable-after-cost logistic
- side-neutral logistic with explicit regime interactions

Gate:

- must beat current `v4` or provide materially cleaner diagnostics

### Track B. Tabular tree models

Purpose:

- capture non-linear context interactions
- support side-aware and action-aware targets

Models:

- CatBoost
- LightGBM
- XGBoost

Preferred order:

1. CatBoost
2. LightGBM
3. XGBoost as benchmark only

Why:

- CatBoost handles mixed regimes and missingness well
- LightGBM is efficient for ranking and regression
- XGBoost is already explored enough to know it is not the sole answer

Hyperparameter policy:

- narrow, disciplined grids only
- tune with validation gates, not wide brute force

Gate:

- must beat logistic baseline on clean OOS and maintain target trade frequency

Rejection:

- reject any tree model that only wins in training / validation but loses clean OOS

### Track C. Ranking and expected-value models

Purpose:

- directly support the `3-5` trades/day objective
- rank intraday candidates instead of thresholding all of them independently

Models:

- LightGBM ranker
- CatBoost ranker
- EV regression with daily top-K selection

Selection policy:

- choose the top `K` candidates/day above a minimum edge floor
- `K` initially in `[3, 4, 5]`

Why this matters:

- this is the most natural way to encode the trade-budget objective
- it also lets the system choose direction opportunistically rather than hardwiring a long bias

Gate:

- improves OOS economics while keeping median trades/day in target

Rejection:

- reject if ranking is unstable or dominated by one symbol/context

### Track D. Action-selection models

Purpose:

- unify entry, side, and hold into one decision problem

Actions:

- `no trade`
- `long 3m / 5m / 8m / 12m`
- `short 3m / 5m / 8m / 12m`

Models:

- multi-class action classifier
- action EV regressor
- top-action ranker

Preferred objective:

- expected net return with a no-trade option

Gate:

- must beat the best context+entry+fixed-hold stack

Rejection:

- reject if it becomes too sparse or unstable to calibrate

### Track E. Sequence models

Purpose:

- use temporal structure more directly if tabular methods plateau

Candidates:

- temporal CNN
- small LSTM / GRU
- transformer-lite sequence encoder

Inputs:

- recent feature trajectory, not raw book tensors initially

Warning:

- only start here after tabular ranking/action models are exhausted

Gate:

- must beat the best tabular model on the same clean OOS template

Rejection:

- reject if data volume is inadequate or if performance depends on fragile optimization

### Track F. Bandit and offline-RL methods

Purpose:

- optimize action selection under a trade budget with delayed rewards

Recommended first method:

- contextual bandit

Why:

- lower complexity than full RL
- more appropriate for discrete action choices and limited clean OOS data

Candidate actions:

- no trade
- long/short x hold bucket

Reward:

- realized net PnL after costs

Full RL:

- PPO, DQN, actor-critic, or similar should be deferred until:
  - simulator fidelity is higher
  - action dataset is broader
  - best tabular/action baselines have plateaued

Gate:

- contextual bandit must beat the best action-selection tabular model

Rejection:

- reject any RL branch that wins only in simulation but not on clean OOS

## Feature Roadmap

### Must-have feature improvements

1. Regime-normalized features
- spread z-scores
- micro-off z-scores
- volatility-normalized deltas

2. Freshness and coverage features
- time since first L2 snapshot
- snapshot density
- time since last snapshot
- source type
- readiness flags

3. Persistence features
- imbalance persistence
- pressure persistence
- micro-off persistence

4. Structural book features
- slope
- convexity
- top-level concentration

5. Cross-sectional features
- within-day rank of spread
- within-day rank of volatility
- within-day rank of imbalance

### Feature rejection rules

- remove absolute price-level features if they show clear symbol memorization
- remove features that are unstable across source types
- remove features that are not available causally in live scoring

## Hyperparameter Strategy

### Principles

- never run blind wide grids
- tune only after target definition is sound
- keep search narrow and hypothesis-driven
- tie every search to a validation gate and an OOS comparison

### Tuning order

1. label / action definition
2. feature set
3. context gating
4. model family
5. calibration
6. entry ranking / trade budget
7. hold / exit refinements

### Hyperparameter rejection rule

- if hyperparameter tuning changes trade frequency more than economics, the model objective is wrong

## OOS Evolution Plan

### Stage 1. Current clean windows

Use:

- `2026-03-06` to `2026-03-11`
- `2026-03-12` to `2026-03-13`

Purpose:

- fast iteration
- stable regression testing

### Stage 2. Expanded clean windows

As new backtestable OOS dates become available:

- lock the best current candidate
- rerun unchanged policy on new dates first
- only then decide whether adaptation is needed

### Stage 3. Rolling OOS regime bank

Maintain a bank of:

- positive window
- negative window
- low-activation window
- mixed-source window
- bullish drift window
- bearish drift window
- flat / choppy window

Candidates must survive the regime bank, not only one combined range.

## Success Ladder

This is the formal progression from research candidate to promotable strategy.

### Level 0. Mechanically valid

- causal
- reproducible
- trustworthy runner

### Level 1. Economically plausible

- clean OOS non-zero activation
- at least one positive clean OOS window

### Level 2. Stable candidate

- combined clean OOS return >= `0`
- combined PF >= `1.0`
- trades/day between `3` and `5`

### Level 3. Strong candidate

- combined clean OOS PF >= `1.10`
- no dominant single-symbol risk
- long and short behavior both explainable
- any directional skew is validated as regime-conditioned, not assumed structural

### Level 4. Promotion candidate

- survives expanded OOS coverage
- stable under small threshold or calibration perturbations
- management policy no longer carries the strategy

## Immediate Execution Plan

### Step 1. Finish the side-threshold test

Purpose:

- determine whether simple long tightening can fix later-window losses without killing frequency

Decision:

- if it works materially, keep as temporary policy improvement
- if it kills activation, do not spend more time there

### Step 2. Build context and long-side regime report

Compare:

- winning longs in window 1
- losing longs in window 2

Goal:

- identify the concrete contexts admitting bad later-window longs
- test whether current long-heavy behavior is regime artifact or robust directional structure

### Step 3. Build `v5` as a side-aware action baseline

Preferred first `v5`:

- keep two-stage structure
- make stage 2 side-aware
- add context-conditioned long suppression
- do not encode long bias as a prior; require evidence from regime-conditioned attribution
- keep `time_only / 5m` fixed

### Step 4. Expand beyond logistic

First branch:

- CatBoost profitable-after-cost and / or action model

Second branch:

- LightGBM ranking model with top-K daily selection

Third branch:

- contextual bandit over discrete actions if ranking models are promising

## Final Program Decision Rule

The program should converge toward the first method that satisfies all of the following:

- clean OOS profitability
- PF at or above `1.10`
- stable side behavior
- `3-5` trades/day on average
- no dependence on ticker exclusions
- no dependence on aggressive TP/SL rescue logic

If no model family satisfies those conditions, the next step is not endless tuning. The next step is
to revisit the prediction target and action definition again.
