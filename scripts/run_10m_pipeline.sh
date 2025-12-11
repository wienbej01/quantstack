#!/bin/bash
# Run 10m feature pipeline

set -e

echo "=========================================="
echo "10M FEATURE PIPELINE"
echo "Date: $(date)"
echo "=========================================="
echo ""

echo "Step 1: Building 10m intraday features..."
echo "  - Training on 10m bars"
echo "  - Execution on 1m bars (first bar after signal)"
echo "  - ETA: 4-6 hours"
echo ""

python scripts/build_intraday_features_10m.py > /tmp/build_10m_features.log 2>&1
echo "✓ 10m features complete"
echo ""

echo "Step 2: Running rolling training and backtest..."
echo "  - 26 OOS months"
echo "  - ETA: 3-4 hours"
echo ""

python scripts/rolling_train_10m.py > /tmp/rolling_train_10m.log 2>&1
echo "✓ Training complete"
echo ""

echo "=========================================="
echo "PIPELINE COMPLETE"
echo "=========================================="
echo ""
echo "Results:"
echo "  - 10m features: run/intraday_features_10m/features.parquet"
echo "  - Metrics: run/rolling_results_10m/metrics.csv"
echo "  - Trades: run/rolling_results_10m/trades.csv"
echo ""
echo "Compare with 1m results:"
echo "  diff <(head run/rolling_results/metrics.csv) <(head run/rolling_results_10m/metrics.csv)"
echo ""
