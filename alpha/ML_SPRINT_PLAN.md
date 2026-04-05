# ML/RL Scalping Sprint Plan

**Project:** L2 Order Book ML Scalping System  
**Start Date:** 2026-03-10  
**Duration:** 5 sprints (5 weeks)  
**Goal:** Train and validate ML models on L2 data for scalping signal generation; explore RL if data permits  
**Prerequisite:** All 6 original sprints complete (92 tests passing), multi-location L2 support live

---

## Data Reality

Before planning, the actual data inventory:

| Source | Type | Dates | Symbol-Days | Notes |
|--------|------|------:|------------:|-------|
| quantstack-v2 features | Pre-computed | 13 | 31 | OBI, depth, pressure, spread, mid |
| quantstack raw | Raw book | 22 | 93 | 10-level bid/ask, needs feature computation |
| **Combined** | | **~31 unique dates** | **124** | Dec 2025 – Mar 2026 |

Feature schema (pre-computed): `ts_utc, mid, spread, obi_1, obi_5, depth_bid, depth_ask, pressure, bid, ask, bid_size, ask_size`

Estimated snapshot count: ~2-3M total (sub-second resolution across all symbol-days).

**Critical constraint:** 124 symbol-days is small. Every design decision must prioritize avoiding overfit.

---

## Sprint Overview

| Sprint | Duration | Focus | Depends On |
|--------|----------|-------|------------|
| S1 | 5 days | Unified ML Dataset Pipeline | Existing L2Loader |
| S2 | 5 days | Feature Engineering & Label Generation | S1 |
| S3 | 5 days | XGBoost Model Training & Walk-Forward CV | S2 |
| S4 | 5 days | Signal Integration & Backtest Comparison | S3 + existing engine |
| S5 | 5 days | RL Environment & Baseline Agent | S2 + S3 |

---

## Sprint 1: Unified ML Dataset Pipeline (Days 1–5)

### Objective
Build a single pipeline that loads L2 data from all sources, computes features on raw data to match the pre-computed schema, and outputs a unified parquet dataset ready for ML.

### Why This First
The 93 raw symbol-days are 3× the pre-computed data. Without unifying them, the ML model trains on only 31 symbol-days — too few for any credible validation.

### Tasks

**Day 1–2: Raw → Feature Computation**
- [ ] Reuse `AlphaL2Features` to compute the same 12-column feature schema from raw 10-level book snapshots
- [ ] Validate computed features match pre-computed features on overlapping dates/symbols (if any overlap exists)
- [ ] Handle edge cases: missing levels, NaN depth, zero spread

**Day 3: Unified Dataset Builder**
- [ ] `src/data/ml_dataset.py` — loads all dates from both sources via `L2Loader`, applies feature computation to raw, concatenates into one DataFrame
- [ ] Add `symbol` and `date` columns for downstream grouping
- [ ] Output: single parquet file per run (or date-partitioned parquet directory)

**Day 4: Data Quality & Coverage Report**
- [ ] Log per-date, per-symbol snapshot counts
- [ ] Flag dates/symbols with <500 snapshots (unusable for ML)
- [ ] Report time gaps >5s within a symbol-day
- [ ] Summary stats: total rows, date range, symbol count, feature distributions

**Day 5: Tests & Validation**
- [ ] Test: raw-computed features are within tolerance of pre-computed features
- [ ] Test: no future data leakage in dataset construction
- [ ] Test: dataset builder handles missing dates/symbols gracefully
- [ ] Test: output schema is consistent regardless of source type

### Acceptance Criteria
- Unified dataset covers all 124 symbol-days
- Feature schema identical across raw-computed and pre-computed sources
- Data quality report generated with no critical issues
- Dataset saved as parquet, loadable in <30s

### Files
- `src/data/ml_dataset.py`
- `tests/test_ml_dataset.py`
- `output/ml_data_quality_report.md`

---

## Sprint 2: Feature Engineering & Label Generation (Days 6–10)

### Objective
Extend the base L2 features with temporal aggregations and interaction features. Generate forward-return labels at multiple horizons. Produce train/val/test splits with strict temporal separation.

### Tasks

**Day 6–7: Temporal Feature Engineering**
- [ ] Rolling statistics over 10s, 30s, 60s, 300s windows:
  - Mean, std, min, max of: `obi_1`, `obi_5`, `spread`, `pressure`, `mid`
  - Delta (current − rolling mean) for each
- [ ] Rate-of-change features:
  - `d_mid_10s`, `d_mid_30s`, `d_mid_60s` (microprice velocity)
  - `d_obi_1_10s`, `d_obi_5_30s` (imbalance momentum)
  - `d_spread_30s` (spread widening/tightening)
- [ ] Cross-features:
  - `obi_1 × pressure` (imbalance confirmed by depth)
  - `spread × d_mid_30s` (volatility-adjusted momentum)
  - `depth_bid / depth_ask` ratio and its 30s delta
- [ ] Time-of-day encoding: minutes since 09:30 ET, session bucket (open/mid/close)
- [ ] All features computed per-symbol, no cross-symbol leakage

**Day 8: Label Generation**
- [ ] Forward mid-price returns at 60s, 180s, 300s horizons
- [ ] Classification labels (3-class):
  - Down: return < −threshold
  - Flat: |return| ≤ threshold
  - Up: return > +threshold
- [ ] Threshold selection: use per-symbol return distribution (e.g., 33rd/67th percentile) to balance classes
- [ ] Drop labels within last N seconds of each session (no forward data available)
- [ ] Add `ret_realized` column for later backtest PnL calculation

**Day 9: Train/Val/Test Split**
- [ ] Temporal split by date (no random shuffling):
  - Train: first ~65% of dates (Dec 2025 – mid-Feb 2026)
  - Validation: next ~20% of dates (mid-Feb – late Feb 2026)
  - Test: last ~15% of dates (Mar 2026)
- [ ] Walk-forward folds: 5 expanding-window folds for CV
  - Fold 1: train on dates 1–5, validate on 6–7
  - Fold 2: train on dates 1–7, validate on 8–9
  - ... etc.
- [ ] Symbol holdout set: reserve ~20% of symbols for out-of-sample symbol testing
- [ ] Save split metadata (which dates/symbols in each fold)

**Day 10: Feature Analysis & Tests**
- [ ] Feature correlation matrix — drop features with >0.95 correlation
- [ ] Feature distribution plots per split (detect drift between train/val/test)
- [ ] Test: no NaN/inf in final feature matrix
- [ ] Test: label distribution is balanced (no >60% single class)
- [ ] Test: no temporal leakage (val/test dates strictly after train dates)
- [ ] Test: walk-forward folds are non-overlapping

### Acceptance Criteria
- Feature matrix: ~50-80 columns (base + temporal + cross)
- Labels generated at 3 horizons with balanced classes
- Train/val/test split with zero temporal leakage
- Walk-forward CV folds defined and saved
- Feature analysis report with correlation and drift checks

### Files
- `src/features/ml_features.py` — temporal and cross-feature computation
- `src/data/ml_labels.py` — label generation and split logic
- `tests/test_ml_features.py`
- `output/feature_analysis_report.md`

### Config Additions (`config/backtest_config.yaml`)
```yaml
ml:
  horizons_seconds: [60, 180, 300]
  label_threshold_method: "quantile"  # or "fixed_bps"
  label_fixed_bps: 10
  rolling_windows: [10, 30, 60, 300]
  train_pct: 0.65
  val_pct: 0.20
  test_pct: 0.15
  symbol_holdout_pct: 0.20
  walk_forward_folds: 5
  max_feature_correlation: 0.95
```

---

## Sprint 3: XGBoost Model Training & Walk-Forward CV (Days 11–15)

### Objective
Train XGBoost classifiers using walk-forward cross-validation. Evaluate directional accuracy, calibration, and feature importance. Establish baseline performance numbers.

### Tasks

**Day 11: Training Pipeline**
- [ ] `scripts/train_ml_model.py` — end-to-end training script:
  1. Load unified dataset from S1
  2. Compute ML features from S2
  3. Generate labels
  4. Run walk-forward CV
  5. Save model artifacts + metrics
- [ ] XGBoost hyperparameter defaults (conservative to avoid overfit):
  - `max_depth: 4`, `n_estimators: 200`, `learning_rate: 0.05`
  - `subsample: 0.8`, `colsample_bytree: 0.7`
  - `min_child_weight: 50`, `reg_alpha: 0.1`, `reg_lambda: 1.0`
  - `early_stopping_rounds: 20` on validation fold
- [ ] Train one model per walk-forward fold
- [ ] Save: model pickle, feature names, training metadata (dates, symbols, row counts)

**Day 12: Hyperparameter Search**
- [ ] Grid search over key parameters (keep grid small — overfit risk):
  - `max_depth: [3, 4, 5]`
  - `n_estimators: [100, 200, 400]`
  - `learning_rate: [0.03, 0.05, 0.1]`
- [ ] Evaluate on walk-forward validation folds (not test)
- [ ] Select best config by average validation accuracy across folds
- [ ] Log all grid results for analysis

**Day 13: Multi-Horizon Models**
- [ ] Train separate models for 60s, 180s, 300s horizons
- [ ] Compare: which horizon has best directional accuracy?
- [ ] Compare: which horizon has best risk-adjusted PnL potential?
- [ ] Decide primary horizon for signal generation

**Day 14: Model Diagnostics**
- [ ] Feature importance (gain-based and SHAP if feasible):
  - Top 20 features per horizon
  - Are temporal features more important than base features?
  - Any single feature dominating? (overfit signal)
- [ ] Calibration analysis:
  - Predicted probability vs actual win rate (reliability diagram)
  - Are high-confidence predictions actually more accurate?
- [ ] Performance breakdown:
  - By date (is accuracy stable across time?)
  - By symbol (is it driven by 1-2 tickers?)
  - By time-of-day (open vs midday vs close)
  - By volatility regime

**Day 15: Overfitting Assessment & Tests**
- [ ] Train vs validation accuracy gap — flag if >5% gap
- [ ] Permutation test: shuffle labels, retrain, compare accuracy (should drop to ~33%)
- [ ] Symbol holdout test: evaluate on held-out symbols
- [ ] Test: model loads and predicts correctly from saved artifact
- [ ] Test: predictions are valid probabilities (sum to 1, in [0,1])
- [ ] Test: walk-forward models produce consistent feature importance rankings

### Acceptance Criteria
- Walk-forward CV accuracy >55% on best horizon (vs 33% random for 3-class)
- Train-val accuracy gap <5%
- No single feature contributes >30% of total gain
- Permutation test confirms signal is real (accuracy drops to ~33%)
- Symbol holdout accuracy within 3% of in-sample accuracy
- Model artifacts saved and reproducible

### Files
- `scripts/train_ml_model.py`
- `src/models/xgb_trainer.py` — training logic, CV, hyperparameter search
- `models/` — saved model artifacts (gitignored)
- `output/ml_training_report.md`
- `tests/test_ml_training.py`

### Config Additions
```yaml
ml:
  model:
    type: "xgboost"
    max_depth: 4
    n_estimators: 200
    learning_rate: 0.05
    subsample: 0.8
    colsample_bytree: 0.7
    min_child_weight: 50
    reg_alpha: 0.1
    reg_lambda: 1.0
    early_stopping_rounds: 20
  grid_search:
    max_depth: [3, 4, 5]
    n_estimators: [100, 200, 400]
    learning_rate: [0.03, 0.05, 0.1]
```

---

## Sprint 4: Signal Integration & Backtest Comparison (Days 16–20)

### Objective
Wrap the trained ML model as a `Signal` subclass, run it through the existing backtest engine, and compare head-to-head against the rule-based signals (micro-offset exhaustion, OBI pullback).

### Tasks

**Day 16: MLSignal Class**
- [ ] `src/signals/ml_signal.py` — implements `Signal` base interface:
  - `check_entry()`: run model inference, generate `SignalEvent` if predicted probability exceeds confidence threshold
  - `check_exit()`: target/stop/time-limit exits (configurable), plus optional model-based exit (predict reversal)
  - Direction: long if P(up) > threshold, short if P(down) > threshold
  - Confidence: use max class probability as signal strength
- [ ] Position sizing: scale size by prediction confidence (higher confidence → larger position, capped by risk limits)
- [ ] Cooldown: no re-entry on same symbol within N seconds of exit

**Day 17: Backtest Runs**
- [ ] Run ML signal through `AlphaBacktestEngine` on test dates (Mar 2026)
- [ ] Run existing rule-based signals on same test dates for comparison
- [ ] Run ensemble: ML + rule-based combined (take signal if either fires, or require both to agree)
- [ ] All runs use `L2ExecutionSimulator` with 75ms latency and book-walk slippage

**Day 18: Performance Comparison**
- [ ] Head-to-head metrics table:
  - Sharpe, win rate, profit factor, max drawdown, trade count, avg PnL per trade
  - Net of commissions ($0.005/share) and L2-simulated slippage
- [ ] ML-specific analysis:
  - PnL by confidence bucket (does higher confidence = higher PnL?)
  - PnL by predicted class (are longs better than shorts or vice versa?)
  - Trade frequency: is ML generating enough trades?
- [ ] Ensemble analysis:
  - Does combining ML + rules improve Sharpe?
  - Does ML catch trades that rules miss (and vice versa)?

**Day 19: Threshold Optimization**
- [ ] Sweep confidence thresholds: 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70
- [ ] Sweep exit parameters: TP 30-75 bps, SL 25-60 bps, max hold 3-10 min
- [ ] Optimize on validation dates only, evaluate on test dates
- [ ] Select final operating point (threshold + exits)

**Day 20: Final Report & Tests**
- [ ] Consolidated comparison report: ML vs rules vs ensemble
- [ ] Go/no-go recommendation for each approach
- [ ] Test: MLSignal implements Signal interface correctly
- [ ] Test: backtest results are reproducible (same data → same PnL)
- [ ] Test: ensemble signal logic is correct (no double-counting)

### Acceptance Criteria
- ML signal generates ≥50 trades on test period
- ML Sharpe ≥1.0 after costs on test dates (or clear explanation why not)
- Comparison report with actionable recommendation
- Ensemble tested and evaluated
- All signals pass through existing backtest engine without modification

### Files
- `src/signals/ml_signal.py`
- `scripts/run_ml_backtest.py`
- `scripts/run_comparison.py`
- `output/ml_vs_rules_comparison.md`
- `tests/test_ml_signal.py`

### Config Additions
```yaml
signals:
  ml:
    model_path: "models/xgb_180s_best.pkl"
    confidence_threshold: 0.55
    target_pct: 0.60
    stop_pct: 0.50
    time_limit_minutes: 5
    cooldown_seconds: 60
    position_size_method: "confidence_scaled"  # or "fixed"
```

---

## Sprint 5: RL Environment & Baseline Agent (Days 21–25)

### Objective
Build a Gym-compatible L2 scalping environment using the existing execution simulator. Train a baseline DQN agent. Determine whether RL adds value over supervised ML given current data constraints.

### Gate Check (Before Starting)
- [ ] **Proceed only if** Sprint 3 achieved >55% directional accuracy
- [ ] **Proceed only if** Sprint 4 showed ML signal is viable (Sharpe >0.5 after costs)
- [ ] If gates fail: spend this sprint on acquiring more L2 data or improving the supervised model instead

### Tasks

**Day 21: Gym Environment**
- [ ] `src/rl/l2_env.py` — OpenAI Gym environment:
  - **State space:** ML feature vector (from S2) + position state (flat/long/short, unrealized PnL, hold time)
  - **Action space:** Discrete(3) — {hold/flat, go long, go short}. If already in position, action becomes {hold, exit}
  - **Step:** advance one snapshot, execute action via `L2ExecutionSimulator`
  - **Episode:** one symbol-day (reset at session boundaries)
  - **Reward:** realized PnL on exit − commissions − slippage. Small negative reward per step while in position (holding cost to discourage idle positions)
- [ ] Episode termination: end of session, max drawdown hit, or daily loss limit
- [ ] Observation normalization: z-score features using training set statistics

**Day 22: Reward Shaping & Baselines**
- [ ] Implement 3 reward variants:
  1. **Sparse:** reward only on trade exit (realized PnL − costs)
  2. **Dense:** per-step unrealized PnL change − holding penalty
  3. **Shaped:** sparse + bonus for exiting at profit, penalty for holding through drawdown
- [ ] Random agent baseline: measure average reward per episode
- [ ] Rule-based agent baseline: wrap existing `OrderFlowSignal` as a policy, measure reward
- [ ] ML agent baseline: wrap XGBoost predictions as a policy, measure reward

**Day 23–24: DQN Training**
- [ ] `src/rl/dqn_agent.py` — standard DQN with:
  - Experience replay buffer (100K transitions)
  - Target network (update every 1000 steps)
  - Epsilon-greedy exploration (1.0 → 0.05 over 50K steps)
  - Network: 2-layer MLP (128, 64) with ReLU
- [ ] Train on training dates, evaluate on validation dates
- [ ] Track: episode reward, trade count, win rate, Sharpe per evaluation epoch
- [ ] Try imitation learning warmstart: pre-fill replay buffer with XGBoost policy transitions
- [ ] Compare: DQN from scratch vs DQN with imitation warmstart

**Day 25: Evaluation & Decision**
- [ ] Compare all approaches on test dates:

  | Agent | Sharpe | Win Rate | Trades | Avg PnL/Trade |
  |-------|--------|----------|--------|----------------|
  | Random | — | — | — | — |
  | Rule-based | — | — | — | — |
  | XGBoost (S4) | — | — | — | — |
  | DQN (scratch) | — | — | — | — |
  | DQN (warmstart) | — | — | — | — |

- [ ] Decision matrix:
  - If RL > ML by >0.3 Sharpe → invest in RL pipeline
  - If RL ≈ ML → stick with ML (simpler, more interpretable)
  - If RL < ML → abandon RL, focus on ML improvements
- [ ] Document data requirements for production-grade RL (how many more symbol-days needed)
- [ ] Test: environment step/reset work correctly
- [ ] Test: agent produces valid actions
- [ ] Test: reward calculation matches manual PnL computation

### Acceptance Criteria
- Gym environment runs episodes without errors
- All 5 agents evaluated on identical test data
- Clear recommendation: RL worth pursuing or not
- If RL viable: roadmap for scaling with more data
- If RL not viable: documented reasons and data requirements

### Files
- `src/rl/l2_env.py`
- `src/rl/dqn_agent.py`
- `src/rl/baselines.py` — random, rule-based, ML policy wrappers
- `scripts/train_rl_agent.py`
- `scripts/run_rl_comparison.py`
- `output/rl_evaluation_report.md`
- `tests/test_rl_env.py`

### Config Additions
```yaml
rl:
  env:
    reward_type: "shaped"  # sparse, dense, shaped
    holding_penalty_per_step: 0.0001
    max_episode_steps: 10000
    observation_norm: "zscore"
  dqn:
    replay_buffer_size: 100000
    target_update_freq: 1000
    epsilon_start: 1.0
    epsilon_end: 0.05
    epsilon_decay_steps: 50000
    hidden_dims: [128, 64]
    learning_rate: 0.0003
    batch_size: 64
    gamma: 0.99
  imitation:
    warmstart_episodes: 500
    policy: "xgboost"  # use trained XGBoost as expert
```

### Dependencies (New)
```
gymnasium>=0.29
torch>=2.0        # for DQN
xgboost>=2.0
shap>=0.43        # optional, for feature importance
joblib>=1.3
```

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 124 symbol-days insufficient for ML | Model overfits, no real edge | Medium | Aggressive regularization, symbol holdout, permutation tests |
| Raw → feature computation introduces errors | Corrupted training data | Low | Validate against pre-computed features on overlapping data |
| XGBoost accuracy <55% | No viable ML signal | Medium | Try LightGBM, add more features, relax threshold, fall back to rule-based |
| RL training unstable with small data | Wasted sprint | High | Gate check before S5, imitation warmstart, keep S5 exploratory |
| Feature drift between train and test periods | Poor test performance | Medium | Monitor feature distributions, walk-forward retraining |
| Execution costs eat all alpha | Positive gross, negative net | Medium | Use L2 book-walk slippage, require >15 bps gross edge |
| Temporal leakage in features | Inflated accuracy | High | Strict per-symbol computation, no cross-date features, automated leak tests |

---

## Success Metrics

### Minimum Viable (at least one must pass)
- [ ] ML directional accuracy >55% on held-out test dates
- [ ] ML signal Sharpe >1.0 after costs on test dates
- [ ] Ensemble (ML + rules) outperforms either alone

### Stretch Goals
- [ ] ML Sharpe >1.5 after costs
- [ ] RL agent outperforms ML by >0.3 Sharpe
- [ ] Model generalizes to held-out symbols (accuracy within 3% of in-sample)

### Kill Criteria (stop and reassess)
- ML accuracy <50% after hyperparameter search → data insufficient, acquire more
- Train-val gap >10% → severe overfit, simplify model
- <20 trades on test period → signal too rare, relax thresholds or add horizons

---

## Timeline Summary

```
Week 1 (S1):  Unified dataset pipeline          → parquet dataset ready
Week 2 (S2):  Features + labels + splits         → ML-ready feature matrix
Week 3 (S3):  XGBoost training + validation       → trained model + diagnostics
Week 4 (S4):  Signal integration + backtest       → ML vs rules comparison
Week 5 (S5):  RL environment + baseline agent     → RL viability decision
```

**Total estimated effort:** 5 weeks  
**Critical path:** S1 → S2 → S3 → S4 (S5 is parallel-eligible after S2)  
**First decision point:** End of S3 (is ML accuracy sufficient?)  
**Final decision point:** End of S5 (is RL worth scaling?)
