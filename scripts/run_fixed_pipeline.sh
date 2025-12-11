#!/bin/bash
# Run the fixed rolling pipeline with proper entry delay and stops

set -e

echo "=========================================="
echo "FIXED ROLLING PIPELINE"
echo "=========================================="
echo ""

# Step 1: Build intraday features (with leakage fix)
echo "Step 1: Building intraday features..."
echo "  - 1m granularity"
echo "  - Entry on bar AFTER signal"
echo "  - Same-day exits only"
echo "  - ATR calculation included"
echo ""

nohup python scripts/build_intraday_features_rolling.py \
  > /tmp/build_intraday_fixed.log 2>&1 &

BUILD_PID=$!
echo "Started feature build (PID: $BUILD_PID)"
echo "Monitor: tail -f /tmp/build_intraday_fixed.log"
echo ""
echo "Waiting for feature build to complete..."
echo "(This will take 4-6 hours)"
echo ""

# Wait for build to complete
wait $BUILD_PID

echo "Feature build complete!"
echo ""

# Step 2: Validate no leakage
echo "Step 2: Validating no data leakage..."
python scripts/validate_no_leakage.py
echo ""

# Step 3: Run rolling training and backtest
echo "Step 3: Running rolling training and backtest..."
echo "  - Entry delay: 1 bar"
echo "  - ATR-based stops: 1.5x ATR"
echo "  - Take profit: 2R"
echo "  - Max hold: 390 bars (6.5 hours)"
echo ""

python scripts/rolling_train_and_backtest.py

echo ""
echo "Step 4: Generating trade report..."
python scripts/generate_trade_report.py

echo ""
echo "=========================================="
echo "PIPELINE COMPLETE"
echo "=========================================="
echo ""
echo "Results:"
echo "  - Metrics: run/rolling_results/metrics.csv"
echo "  - Trades: run/rolling_results/trades.csv"
echo "  - Models: run/rolling_results/models/"
echo ""
