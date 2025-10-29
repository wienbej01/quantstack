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

## Assumptions
- Gold data is mounted at `/home/jacobw/gcs-mount/gold/`
- Virtual environment activated for dependencies
- Timezones handled as UTC in data processing

## CFS Score
- Current: 9/10 (Stable data validation, needs expansion for full system coverage)
