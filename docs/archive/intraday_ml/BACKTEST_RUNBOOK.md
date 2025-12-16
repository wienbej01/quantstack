# Backtest Runbook for Intraday ML Model

This document provides the commands to run the OOS backtest, perform metrics reconciliation, and run the validation tests.

## Current Status

**The `backtest_runner.py` script is currently in a "dummy" state and does not use a real backtesting engine.**

The script uses a placeholder `BacktestAdapter` that returns a single hardcoded trade, and a dummy `decision_policy` function. This is not a valid backtest and is only used for basic integration testing.

## 1) Inference + Policy + Orders + Execution (OOS)

This command runs the main backtest runner. **(Note: This is currently a dummy runner, see "Current Status" above).**

```bash
python -m extensions.intraday_ml_models.wrappers.backtest_runner \
--policy configs/extensions/intraday_ml_models/policy_overrides.yaml \
--backtest configs/extensions/intraday_ml_models/backtest.yaml
```

## 2) Metrics reconciliation & Sharpe sanity

This command runs the metrics consistency checks on the output of the backtest. It verifies that PnL reconciles with equity, Sharpe ratios are consistent, and other rules are followed.

```bash
python -m extensions.intraday_ml_models.wrappers.metrics_consistency \
--backtest configs/extensions/intraday_ml_models/backtest.yaml
```

## 3) Tests

This command runs the suite of unit and integration tests for the backtesting wrappers. It is essential to run this to ensure that the execution rules, returns math, and reconciliation logic are all correct.

```bash
pytest tests/extensions/intraday_ml_models -q --maxfail=1
```
