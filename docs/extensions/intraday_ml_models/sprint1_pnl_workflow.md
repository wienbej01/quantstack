# Sprint 1 PnL Instrumentation & Evaluation

This guide documents the Sprint 1 deliverables described in `quantstack_intraday_execution_plan.md` and shows how to run them without touching strategy logic.

## 1. Dataset Instrumentation (label distributions)

Purpose: rebuild each split (train/test/oos) with the sliding-window data prep, applying the SIP-filtered universe, then emit label counts per day and per symbol so we can quantify ±1 sparsity before training.

Run:

```bash
python -m extensions.intraday_ml.cli.instrument_datasets \
  --config configs/extensions/intraday_ml/phaseA_master_sip.yaml \
  --splits train val test oos \
  --artifact-dir artefacts/extensions/intraday_ml/phaseA
```

Outputs land under `artefacts/extensions/intraday_ml/phaseA/instrumentation/`:

- `{split}_dataset.parquet` – SIP-filtered dataset for the split.
- `{split}_label_distribution.csv` – daily counts of {-1,0,+1}.
- `{split}_symbol_label_distribution.csv` – per-symbol label counts per day.
- `instrumentation_summary.json` – quick overview (symbol counts, rows, label totals).

Use these artefacts to confirm we still have sufficient positive/negative samples after enabling SIP and before triggering expensive training/backtests.

## 2. Prediction Scoring

The helper `extensions.intraday_ml.eval.prediction_loader.score_predictions` standardises:

- `trade_prob = max(p_long, p_short)`
- `trade_direction ∈ {-1, 0, +1}`
- `edge_margin = trade_prob - p_flat`
- `trade_score = trade_prob * edge_margin`

It automatically infers probability column names (supports `prob_long/prob_short/prob_neutral` or `prob_c2/prob_c0/prob_c1`) so any downstream tooling receives consistent confidence metrics.

## 3. Trading Performance Evaluation

Purpose: transform predictions into realised PnL diagnostics (per-trade, daily, Sharpe/Sortino/drawdown) across multiple policies without changing the main pipeline.

Run on a pipeline artifact folder (requires the OOS features/parquet with OHLCV and predictions parquet):

```bash
python -m extensions.intraday_ml.cli.evaluate_trading \
  --bars artefacts/extensions/intraday_ml/phaseA/oos_features.parquet \
  --predictions artefacts/extensions/intraday_ml/phaseA/oos_predictions.parquet \
  --horizon-minutes 30 \
  --transaction-cost-bps 12 \
  --output-dir artefacts/extensions/intraday_ml/phaseA/eval
```

By default two policies are evaluated:

1. `threshold_55`: probability ≥ 0.55, min edge 2%, min score 1%.
2. `topk_3`: top 3 signals per day ranked by `trade_score`, probability ≥ 0.5.

Provide a custom YAML to explore alternative gates:

```yaml
# policy_custom.yaml
policies:
  - name: threshold_60
    kind: threshold
    prob_threshold: 0.60
    min_edge: 0.03
    min_score: 0.015
  - name: topk_5
    kind: topk
    prob_threshold: 0.52
    top_k: 5
    score_column: trade_score
```

```bash
python -m extensions.intraday_ml.cli.evaluate_trading \
  --bars .../oos_features.parquet \
  --predictions .../oos_predictions.parquet \
  --policy-config policy_custom.yaml
```

Outputs per policy:

- `{policy}_trades.csv` – trade-level details with gross/net returns, ranks, SIP metadata.
- `{policy}_daily_pnl.csv` – cumulative PnL per trade date.
- `{policy}_metrics.json` – total trades, win-rate, avg/median return, Sharpe, Sortino, max drawdown.
- `summary_metrics.json` – combined table for quick comparison.

## 4. No Forward-Look & SIP Guardrails

- Instrumentation and evaluation keep SIP logic in config. Pass `sip_filter.enabled=false` in the master config to fall back to legacy universes; the tooling automatically reuses the provided config.
- Realised returns use next-`horizon_minutes` prices within the same symbol time series to prevent leakage; we only join predictions to bars when both share exact timestamps.
- Transaction costs default to 10 bps round-trip; adjust per experiment for risk-adjusted benchmarking.

## 5. Suggested Workflow

1. Run the SIP CLI to build membership for the target dates.
2. Instrument datasets via `instrument_datasets` to inspect label coverage.
3. Execute `run_phaseA_pipeline.py` (or another training script) using the same master config.
4. Evaluate generated predictions with `evaluate_trading` to check daily trade counts, PnL, Sharpe/Sortino, and drawdown.
5. Iterate on policy YAML or model configs until the daily trade frequency and risk-adjusted metrics meet the “3–5 profitable trades/day” objective.
