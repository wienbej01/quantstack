#!/bin/bash
# Fix bugs and re-run policy sweep with correct parameters

set -e

echo "=== Fixing Intraday ML System Bugs ==="
echo ""

# 1. Verify Sharpe fix was applied
echo "1. Checking Sharpe calculation fix..."
if grep -q "daily_equity = equity_series.resample" qx-backtest/src/qx_backtest/engine.py; then
    echo "   ✅ Sharpe fix applied"
else
    echo "   ❌ Sharpe fix NOT applied - check engine.py"
    exit 1
fi

# 2. Verify new sweep grid exists
echo "2. Checking sweep grid..."
if [ -f "configs/extensions/intraday_ml/policy_sweep_grid_v2.yaml" ]; then
    echo "   ✅ New sweep grid created"
    cat configs/extensions/intraday_ml/policy_sweep_grid_v2.yaml
else
    echo "   ❌ New sweep grid NOT found"
    exit 1
fi

# 3. Re-run policy sweep with corrected parameters
echo ""
echo "3. Running corrected policy sweep..."
echo "   This will test 4x4x3x3 = 144 configurations"
echo "   Estimated time: ~5 minutes"
echo ""

python -m extensions.intraday_ml.experiments.policy_sweep \
  --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json \
  --grid configs/extensions/intraday_ml/policy_sweep_grid_v2.yaml \
  --backtest-config configs/extensions/intraday_ml/backtest_smoke.yaml \
  --output artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_v2.csv

echo ""
echo "=== Sweep Complete ==="
echo ""

# 4. Analyze results
echo "4. Analyzing results..."
python -c "
import pandas as pd

df = pd.read_csv('artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_v2.csv')

print('=== Results Summary ===\n')
print(f'Total configs: {len(df)}')
print(f'Unique win rates: {df[\"metric_win_rate\"].nunique()}')
print(f'Unique trade counts: {df[\"metric_total_trades\"].nunique()}')
print(f'\nSharpe range: {df[\"metric_sharpe_ratio\"].min():.2f} to {df[\"metric_sharpe_ratio\"].max():.2f}')
print(f'Win rate range: {df[\"metric_win_rate\"].min():.1%} to {df[\"metric_win_rate\"].max():.1%}')
print(f'Trade count range: {int(df[\"metric_total_trades\"].min())} to {int(df[\"metric_total_trades\"].max())}')

print('\n=== Top 5 by Sharpe ===\n')
top = df.nlargest(5, 'metric_sharpe_ratio')
for idx, row in top.iterrows():
    print(f'Config {idx}:')
    print(f'  Sharpe: {row[\"metric_sharpe_ratio\"]:.2f} | Win Rate: {row[\"metric_win_rate\"]:.1%} | Trades: {int(row[\"metric_total_trades\"])}')
    print(f'  Thresholds: S1={row[\"param_bigmove_policy.probability_threshold\"]:.2f}, Long={row[\"param_prob_threshold_long\"]:.2f}, Short={row[\"param_prob_threshold_short\"]:.2f}')
    print(f'  PnL: \${row[\"metric_total_pnl\"]:.2f} | Max DD: {row[\"metric_max_drawdown\"]:.2%}')
    print()

# Check if thresholds are actually varying
if df['metric_total_trades'].nunique() > 5:
    print('✅ Thresholds are working - trade counts vary across configs')
else:
    print('⚠️ Thresholds may not be working - limited trade count variation')
"

echo ""
echo "=== Next Steps ==="
echo "1. Review results in: artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_v2.csv"
echo "2. If Sharpe > 1.5 and win rate > 45%, proceed to paper trading"
echo "3. If results still poor, check rejection reasons and policy logic"
