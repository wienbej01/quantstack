# Sprint 3 – Robust CV & PnL-Guided Tuning

Sprint 3 hardens cross-validation, pipes every fold through the trading evaluator, and exposes a reproducible tuning CLI so we can optimise for Sharpe/Sortino subject to drawdown/trade-rate constraints.

## 1. Purged CV with Trading Logs

`configs/extensions/intraday_ml/cv/phaseA.yaml` now specifies:

- Strict purged CV (`n_folds=3`, `purge_days=5`, `embargo_days=5`).
- Explicit primary/economic/trade-density metrics.
- `trading_evaluation` block that declares the evaluation horizon, transaction costs, context columns, and the fold-level policies (`cv_threshold`, `cv_top2`).

`TimeSeriesCVRunner` consumes OHLC context (pass via `context_data=`) and, for each fold:

1. Generates calibrated probabilities.
2. Feeds them into `extensions.intraday_ml.eval.evaluate_trading_performance`.
3. Logs per-policy metrics (total trades, avg_return, Sharpe, Sortino, drawdown, win_rate) inside `CVMetrics.trading_metrics`.

Aggregated results now include keys such as `trading_cv_threshold_sharpe_mean`, so CI can flag regressions on risk-adjusted PnL, not just logloss.

### Usage inside the pipeline

`run_phaseA_pipeline.py` already saves OHLC columns in `training_data.parquet` and passes them to CV:

```python
context_cols = [c for c in ["open","high","low","close","volume"] if c in training_df.columns]
context_data = training_df[context_cols] if context_cols else None
cv_runner.run_cv(..., context_data=context_data)
```

No extra wiring required when running `python run_phaseA_pipeline.py --config ...`.

## 2. Bayesian Tuner with Trade-Rate Shaping

- `configs/extensions/intraday_ml/tuning/objective_pnl.yaml` weights expectancy/Sharpe higher than pure ML metrics and penalises trade rates above ~1.5% of minutes.
- `extensions/intraday_ml/cli/tune_lgbm.py` loads the master config, dataset (defaults to `artefacts/.../training_data.parquet`), and the CV/objective configs, then runs `BayesianLightGBMTuner.optimize(...)` with context data so every trial respects the new trading evaluator.
- Results (best params, history, CV artifacts) are written to `artefacts/extensions/intraday_ml/tuning/`.

Example:

```bash
python -m extensions.intraday_ml.cli.tune_lgbm \
  --config configs/extensions/intraday_ml/phaseA_master_bigmove.yaml \
  --objective-config configs/extensions/intraday_ml/tuning/objective_pnl.yaml \
  --output-dir artefacts/extensions/intraday_ml/tuning/bigmove
```

## 3. Checklist Before Hand-Off

1. Run SIP + instrumentation (Sprint 1) to confirm label coverage.
2. Train big-move model (Sprint 2) with `run_phaseA_pipeline.py --config ...`.
3. Inspect CV report (now includes trading metrics) under `artefacts/.../cv_report.json`.
4. Run the tuner CLI for a compact grid/Bayesian search; review `*_metrics.json` for Sharpe/Sortino improvements.
5. Re-evaluate OOS predictions via `cli.evaluate_trading` to ensure daily trade counts stay in the 3–5 range with controlled drawdowns.
