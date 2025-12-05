#!/bin/bash
# Run improved sweep with caching, fixed TOD, and parallel analysis

set -e

echo "=== Improved Intraday ML Sweep ==="
echo "Date: $(date)"
echo ""

# Configuration
WORKERS=4
OUTPUT_DIR="artefacts/extensions/intraday_ml/policy_sweeps_v3"
mkdir -p "$OUTPUT_DIR"

echo "1. Using cached predictions and features..."
echo "   Signals: artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet"
echo "   Features: artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet"
echo ""

echo "2. Running parallel sweep with simplified policy (no TOD overrides)..."
echo "   Workers: $WORKERS"
echo "   Config: policy_config_bigmove_simple.json"
echo "   Grid: policy_sweep_grid_v2.yaml (576 configs)"
echo ""

python -m extensions.intraday_ml.experiments.parallel_sweep \
  --signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet \
  --bars artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove_simple.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_v2.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output "$OUTPUT_DIR/results.csv" \
  --workers $WORKERS

echo ""
echo "3. Analyzing results..."

python -c "
import pandas as pd
import numpy as np

df = pd.read_csv('$OUTPUT_DIR/results.csv')

print('=== Sweep Results Summary ===\n')
print(f'Total configs: {len(df)}')
print(f'Successful configs: {(df[\"entries\"] > 0).sum()}')
print(f'Failed configs: {(df.get(\"error\", pd.Series()).notna()).sum()}')

# Filter successful configs
df_success = df[df['entries'] > 0].copy()

if len(df_success) > 0:
    print(f'\n=== Performance Metrics ===')
    print(f'Unique win rates: {df_success[\"metric_win_rate\"].nunique()}')
    print(f'Unique trade counts: {df_success[\"metric_total_trades\"].nunique()}')
    print(f'Win rate range: {df_success[\"metric_win_rate\"].min():.1%} to {df_success[\"metric_win_rate\"].max():.1%}')
    print(f'Trade count range: {int(df_success[\"metric_total_trades\"].min())} to {int(df_success[\"metric_total_trades\"].max())}')
    print(f'Sharpe range: {df_success[\"metric_sharpe_ratio\"].min():.2f} to {df_success[\"metric_sharpe_ratio\"].max():.2f}')
    print(f'Avg R range: {df_success[\"metric_avg_R\"].min():.2f} to {df_success[\"metric_avg_R\"].max():.2f}')
    
    print(f'\n=== Top 5 by Sharpe ===')
    top = df_success.nlargest(5, 'metric_sharpe_ratio')
    for idx, row in top.iterrows():
        print(f\"Config {int(row['sweep_id'])}: Sharpe={row['metric_sharpe_ratio']:.2f}, WR={row['metric_win_rate']:.1%}, Trades={int(row['metric_total_trades'])}, AvgR={row['metric_avg_R']:.2f}\")
        print(f\"  Thresholds: S1={row['param_bigmove_policy.probability_threshold']:.2f}, Long={row['param_prob_threshold_long']:.2f}, Short={row['param_prob_threshold_short']:.2f}\")
    
    print(f'\n=== Configs with 3-5 Trades/Day ===')
    target = df_success[(df_success['trades_per_day'] >= 3) & (df_success['trades_per_day'] <= 5)]
    print(f'Found: {len(target)} configs')
    if len(target) > 0:
        for idx, row in target.nlargest(3, 'metric_sharpe_ratio').iterrows():
            print(f\"Config {int(row['sweep_id'])}: Sharpe={row['metric_sharpe_ratio']:.2f}, Trades/Day={row['trades_per_day']:.1f}\")
    
    # Check if thresholds are working
    if df_success['metric_total_trades'].nunique() > 20:
        print(f'\n✅ Thresholds are working - {df_success[\"metric_total_trades\"].nunique()} unique trade counts')
    else:
        print(f'\n⚠️ Limited variation - only {df_success[\"metric_total_trades\"].nunique()} unique trade counts')
else:
    print('\n❌ No successful configs')
"

echo ""
echo "4. Trade-level analyses saved to: $OUTPUT_DIR/trade_analyses/"
echo ""
echo "=== Next Steps ==="
echo "1. Review results: $OUTPUT_DIR/results.csv"
echo "2. Check trade analyses: $OUTPUT_DIR/trade_analyses/analysis_config_*.json"
echo "3. If Sharpe > 1.0 and variance improved, proceed to paper trading"
