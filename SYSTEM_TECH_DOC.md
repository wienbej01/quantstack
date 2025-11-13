# System Technical Documentation

## Overview
This document describes the QuantStack trading system's technical architecture, data flows, and operational procedures.

## Version History
- 2025-10-28: Policy and Performance Fixes & Reporting Enhancement
    - Corrected a critical bug in `AVWAPMomentumPolicy`, `AVWAPPullbackPolicy`, and `ValueRotationPolicy` to enforce "1 share per trade" and "1 trade per day" rules, preventing runaway trade generation.
    - Improved backtesting performance by disabling excessive file-based logging in the backtest engine.
    - Added a new `trades` command to the `qx-report` CLI for detailed trade analysis, reading from `trades.parquet` artifact.
    - Added debug prints to policies for fine-grained trade lifecycle tracing.
- 2025-10-12: Implemented qx-cli integration wiring for A/B experiments. Full orchestration flow from config loading to backtest artifacts. Includes deterministic hashing, fairness checks, and CLI UX. Updated entry_ab.py, engine.py, and related modules.
- 2025-10-12: Added JSON schema validators in qx-core/schemas.py, gold_loader.py in qx-data for read-only normalized bar loading, and hashers.py in qx-core for stable dataframe hashing. Sprint 1.9 and 1.10 implementation.
- 2025-10-11: Initial creation. Updated check_gold_and_make_smoke_sample.py to handle actual gold data structure for bars_1m family.

## Architecture

### Data Ingestion
- **Gold Data**: Reference market data stored in GCS-mounted directories
  - Path: `/home/jacobw/gcs-mount/gold/`
  - Structure:
    - Stocks 1m bars: `stocks/1m/{symbol}/{year}/{year}-{month}.parquet`
    - Features: `features/`
    - Metadata: `metadata/`

### Data Processing Scripts
- `tools/check_gold_and_make_smoke_sample.py`: Validates gold data integrity and creates smoke test samples
  - Supports family "bars_1m" with actual structure `stocks/1m/{symbol}/{year}/{year}-{month}.parquet`
  - Adds missing "symbol" column if not present in parquet files
  - Outputs normalized data summaries and optional parquet samples

### Features
- Feature registry in qx-features/registry.py applies packs like 'core_basics' with VWAP, relative volume, ATR
- Warmup gating ensures features are calculated after sufficient bars

### Risk Management
- ATR-based stop sizing in qx-risk/atr_stop.py
- Orders sized to risk fraction of equity, with ATR multiplier for stop distance

### A/B Experiment Flow
- CLI command: `qx exp entry-ab --cfg base.yaml --variants 'overlays/*.yaml' --name exp_id`
- Orchestration:
  1. Load base config + merge overlays with deep merge
  2. Load bars from gold data, normalize, hash for bars_norm_hash
  3. Apply features, hash feature columns for features_hash
  4. SIP screen for universe, hash universe map for sip_hash
  5. Generate signals with policy (vwap_revert), includes decision_trace for first 200 rows
  6. Size orders with risk (ATR stops), create orders_df
  7. Run backtest with slippage and costs, emit artifacts (signals, orders, fills, positions, equity, trades, risk_rejects, allocation_log, metrics.json). The `trades.parquet` file contains a detailed log of each trade.
  8. Write manifest.json and inputs_checksum.json, run compare for fairness check
- Determinism: seed set, stable sorts, UTC ns timestamps
- Fairness: variants must have identical inputs_checksum.json (bars/features/SIP/config hashes)
- CLI UX: run summary with trades, pnl, R stats; first differences in signals if counts equal

### Testing
- Smoke samples created under `/tmp/e2e_smoke_from_gold/` for testing pipelines

### Operations
- Data validation: Run `check_gold_and_make_smoke_sample.py` with appropriate parameters
- Environment: Requires Python 3, pandas, GCS mount access

### Plug-and-Play Guidelines
- Core modules (`qx_data`, `qx_features`, `qx_backtest` engine/fill, `qx_risk`, `qx_core`, `qx_report`, CLI metrics) remain **frozen infrastructure**; any changes require documented review.
- Strategies should plug in via config overlays (`policy_params`, `risk_params`), policy classes under `qx_backtest/policies/`, and SIP/feature pack registration. Extend rather than modify the core.
- Reproducibility is mandatory: `bars_norm_hash`, `features_hash`, `sip_hash`, and `config_hash` must stay stable unless maintainers sign off on the change.

### Strategy Portfolio
- **VWAP Revert** – mean-reversion baseline with risk controls; the default `entry-ab` config continues to reference this policy.
- **VWAP Momentum** – breakout variant now sharing the same risk hooks (ATR sizing, warm-up gating). Command-line usage mirrors the revert flow but with `policy: vwap_momentum`. **Note:** Policies now enforce a hardcoded "1 share per trade" and "1 trade per day" rule.
- Use `tools/grid_search_apr2024.py` for quick parameter sweeps across 5/15/30/60 minute aggregations (SIP and risk settings are adjustable).

### Reporting (`qx-report`)
- The `qx-report` CLI provides tools for analyzing backtest results.
- `summarize`: Generates a summary table for an experiment.
- `compare`: Generates A/B comparison tables between variants.
- `leaderboard`: Creates a ranked leaderboard for an experiment.
- `inspect`: Inspects a single run in detail, with an option to show sample trades.
- `trades`: **(New)** Generates a detailed list of all trades for a single run, including entry/exit timestamps, prices, direction, and P&L. This command is useful for in-depth trade analysis and debugging.

## Feature Catalog & Parameters
### Core feature pack
- VWAP, relative volume, ATR, and warm-up gating live inside `qx-features/src/qx_features/core_basics.py` where `compute_all_core_features` defaults to a 30-minute VWAP and RVOL lookback and a 30- or 14-bar ATR window (`vwap_window`, `rvol_window`, `atr_window`). Each feature is group-wise computed per symbol, and the warm-up mask (`f__warmup_ok`) only turns true once the largest lookback has been accumulated.
- Relative volume normalizes against a time-of-day mean, ATR uses a rolling max-true range, and VWAP leverages price*volume / volume windows with zero-division guards. Feature names follow the `f__{group}__{name}_{window}` convention owned by the registry in `qx-features/src/qx_features/registry.py`, so downstream policies can look up `f__ta__vwap_{vwap_window}` without hardcoding column order.
### Advanced feature engineering
- Intraday ML experiments feed additional engineered terms from `configs/extensions/intraday_ml/features/advanced_features.yaml`: lagged snapshots, rolling mean/std extrema, difference features, interaction candidates, optional technical indicators (RSI/MACD/Bollinger/Stochastic/Williams R), volatility estimators (`realized`, `garch`, `parkinson`), volume/microstructure signals, and optional cross-asset statistics. The config toggles binning, scaling (robust/quantile), dimensionality reduction, recursive feature selection, and time-of-day markers, letting experiments grade the impact of each block without touching strategy logic.
- Feature validation/monitoring blocks ensure missing or infinite columns are removed, drift is tracked, and coverage/importance thresholds are enforced before saving the feature matrix. Feature metadata is persisted alongside the main parquet output (`save_feature_matrix`, `save_feature_metadata`, `save_feature_importance`).

## Entry / Exit / Position Logic
### VWAP revert policy
- `VwapRevertPolicy` (and the enhanced variant) in `qx-backtest/src/qx_backtest/policies/vwap_revert.py` enforces a single-direction mean-reversion trigger: `close < VWAP` for longs or `close > VWAP` for shorts while `relative volume >= min_rvol` and deviation from VWAP crosses `min_deviation_pct`. Each entry respects `max_positions`, avoids duplicate pending orders, sizes positions with `position_size_pct` of the current equity, and can optionally call `qx-risk/src/qx_risk/atr_stop.py`'s `size_order`/`set_stops` helpers so `atr_mult`, `max_risk_frac`, and regime-aware adjustments get factored into quantity and stop/target levels.
- Exit signals fire on VWAP crossovers, timeouts (`max_position_bars`), ATR-based stop hits, or profit targets. Bars held are tracked via nanosecond timestamps translated into minutes, with pending exits deduplicated to prevent runaway orders. The enhanced policy introduces volatility-aware entry filters, ATR-backed targets, and dynamic stop tightening.
### VWAP momentum policy
- `VwapMomentumPolicy` under `qx-backtest/src/qx_backtest/policies/vwap_momentum.py` flips the logic to favor breakouts: entries require `breakout_pct` above `min_breakout_strength`, sufficient RVOL, warm-up completion, and a daily “one trade per symbol” guard (`trades_today`). Position sizing reuses the same risk parameters and caps.
- Winner-protection includes VWAP retests, timeout exits, and the same ATR/risk scaffolding as the revert policy. The enhanced momentum subclass adds explicit ATR stop/profit-target layers and filters out volatile bars where `atr/close` exceeds 10%.
### ML + VPA hybrid policy
- `MLVpaPolicy` in `qx-backtest/src/qx_backtest/policies/ml_vpa.py` combines a trained ML score with pattern-driven VPA confidence. Predictions only fire when the model and `p__vpa__*` flags exist for a bar, missing values are rejected, and `feature_names` from the stored manifest are honored.
- Entry occurs when the `combined_score = (1 - vpa_weight) * model_score + vpa_weight * vpa_score` clears `prediction_threshold`, the engine has capacity, and `_validate_entry_conditions` prevents extreme volatility. Exits happen if the model score halves the threshold, the combined score decays >30% from entry, or `max_position_bars` expires. All trades carry rich tags (`entry_score`, `exit_model_score`, `active_vpa_patterns`) to trace label drift.
### Position & risk orchestration
- Portfolio updates flow through `qx-backtest/src/qx_backtest/portfolio.py`, which tracks `Position`, realized/unrealized P&L, commissions, and market-value updates. Filled orders recompute avg cost while preventing cross-side accumulation, and positions leverage the `OrderFactory`/`DefaultFiller` plumbing to enforce fill slippage, fees, and `RegimeDetector` gating (`BacktestConfig.strategy_map`).
- Regime-aware risk lives in `qx-risk/src/qx_risk/atr_stop.py`: `size_order` applies `max_risk_frac`, `atr_mult`, and adjustments (`BULL`, `BEAR`, `SIDEWAYS`, `STRESS`) before returning a quantity. `set_stops` derives stop/target prices from ATR multiples plus optional hints, while regime context calls `reject_order_for_regime` to block new entries in stress and `get_regime_risk_context` to expose recommended actions.
- The policy base class consults `engine.is_strategy_allowed` during `process_bar`, and regimes propagate through `_apply_regime_risk_adjustments` so exposures shrink when volatility spikes.

## Model Design & Training Pipeline
### Dataset construction
- `DatasetBuilder` in `qx-features/src/qx_features/dataset_builder.py` enforces deterministic train/validation/test splits using symbol-aware time ordering, configurable ratios (0.7/0.15/0.15 by default), and minimum sample filtering. Each split hashes the symbol/ts/feature/target columns via `qx_core.hashers.hash_dataframe`, records statistics (counts, start/end ts, feature means/stds, target moments), and emits manifests for reproducibility.
- Saved splits live alongside `manifest.json`, ensuring the same `feature_cols`, `target_col`, and hash values can be reloaded via `load_splits` for validation or deployment.
### Model training scaffolds
- `ModelTrainer` (`qx-features/src/qx_features/ml_trainer.py`) is a lightweight sklearn wrapper that selects between `RandomForestClassifier` and `LogisticRegression` (configurable via `model_type`), standardizes features before training, logs ROC-AUC/accuracy, and writes assets (`model.pkl`, `scaler.pkl`, `features.json`, `manifest.json`) with hashes computed from training metadata.
- `MLModelTrainer` (`extensions/intraday_ml_models/trainers.py`) builds on this with a registry (`extensions/intraday_ml_models/registry.py`), time-series splits (`train_test_split`, `train_val_split`), optional hyperparameter tuning (grid search with `TimeSeriesSplit`), scaling, and feature importance extraction (tree/linear coefficients). Metadata objects (`extensions/intraday_ml_models/schemas.py::ModelMetadata`) capture feature lists, stats, hashes, and hyperparameters.
- Experiments point to configs such as `configs/extensions/intraday_ml/experiments/default_experiment.yaml`, which defines the symbol set, feature pack, prediction horizons, and multiple model variants (classification and regression, each with different feature selection and hyperparameter blocks). Training metadata persists under `runs/intraday_ml_experiments`, enabling comparisons via evaluation metrics (MSE/MAE/accuracy/F1/ROC-AUC) and recorded predictions/feature importance.

## Labeling & Class Mapping
- Target signals are defined in `configs/extensions/intraday_ml/targets.yaml`: `label_type: triclass_atr_threshold` means each labeled bar becomes {-1, 0, +1} based on forward-looking ATR-adjusted moves. `horizons` (e.g., 30m, 60m, 90m) slide over minute bars, while `atr_multiplier`/`atr_multiplier_long`/`atr_multiplier_short` set the absolute thresholds that long/short legs must hit. `first_hit_logic` ensures the label captures the first time a threshold is crossed, and `stop_at_hit` freezes the outcome once triggered.
- `volatility_scaling` and `directional_balance` automatically adapt thresholds to keep both sides represented: volatility scaling mixes price/ATR quantiles before clamping each multiplier between `min` and `max`, and directional balance nudges the long/short ratio toward `target_ratio` (with tolerance, step size, and max iterations) while respecting minimum observations per direction.
- Classification configs (e.g., `configs/extensions/intraday_ml/models/classification_model.yaml`) overlay `target_threshold`/`neutral_zone` parameters, converting returns into binary or ternary buckets before training. Candidate features include VWAP/RVOL/ATR derivatives and engineered ratios (distance to VWAP, price position), along with `feature_selection` toggles (univariate, LASSO, recursive, etc.).
- Model metadata captures class mapping through `ModelMetadata` (features, `target_column`, `model_type`, `hyperparameters`, `feature_importance`) and consistent `model_hash` values, letting downstream consumers match predictions to the same label semantics and strategy weights.

## Assumptions
- Gold data is mounted at `/home/jacobw/gcs-mount/gold/`
- Virtual environment activated for dependencies
- Timezones handled as UTC in data processing

## CFS Score
- Current: 9/10 (Stable data validation, needs expansion for full system coverage)
