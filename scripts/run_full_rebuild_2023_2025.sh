#!/bin/bash
# Full rebuild: 2023-01-01 to 2025-09-30 with daily SIP selection

set -e

echo "=========================================="
echo "FULL REBUILD: 2023-01 to 2025-12"
echo "=========================================="
echo "Date range: 2023-01-01 to 2025-12-15"
echo "Training periods: 26 months (2023-08 to 2025-12)"
echo "Daily SIP selection: Top 50 stocks per day"
echo ""

# Clean previous runs
echo "Cleaning previous runs..."
rm -rf run/daily_features_rolling/
rm -rf run/sip_membership_rolling/
rm -rf run/intraday_features_rolling/
rm -rf run/rolling_results/
echo "Done."
echo ""

# Step 1: Build daily features
echo "=========================================="
echo "STEP 1: Building Daily Features"
echo "=========================================="
echo "This will take 2-3 hours..."
echo ""

nohup python scripts/build_daily_features_rolling.py \
  > /tmp/build_daily_features.log 2>&1 &

DAILY_PID=$!
echo "Started daily features build (PID: $DAILY_PID)"
echo "Monitor: tail -f /tmp/build_daily_features.log"
echo ""

# Wait for completion
wait $DAILY_PID

if [ $? -ne 0 ]; then
    echo "ERROR: Daily features build failed"
    exit 1
fi

echo "✓ Daily features complete"
echo ""

# Step 2: Generate SIP membership
echo "=========================================="
echo "STEP 2: Generating SIP Membership"
echo "=========================================="
echo "Selecting top 50 stocks per day..."
echo ""

python scripts/generate_sip_rolling.py

if [ $? -ne 0 ]; then
    echo "ERROR: SIP generation failed"
    exit 1
fi

echo "✓ SIP membership complete"
echo ""

# Step 3: Build intraday features
echo "=========================================="
echo "STEP 3: Building Intraday Features"
echo "=========================================="
echo "This will take 4-6 hours..."
echo ""

nohup python scripts/build_intraday_features_rolling.py \
  > /tmp/build_intraday_features.log 2>&1 &

INTRADAY_PID=$!
echo "Started intraday features build (PID: $INTRADAY_PID)"
echo "Monitor: tail -f /tmp/build_intraday_features.log"
echo ""

# Wait for completion
wait $INTRADAY_PID

if [ $? -ne 0 ]; then
    echo "ERROR: Intraday features build failed"
    exit 1
fi

echo "✓ Intraday features complete"
echo ""

# Step 4: Validate
echo "=========================================="
echo "STEP 4: Validating Features"
echo "=========================================="
echo ""

python scripts/validate_no_leakage.py

if [ $? -ne 0 ]; then
    echo "WARNING: Validation found issues"
fi

echo ""

# Step 5: Rolling training and backtest
echo "=========================================="
echo "STEP 5: Rolling Training and Backtest"
echo "=========================================="
echo "26 training iterations (2023-08 to 2025-09)"
echo "This will take 3-4 hours..."
echo ""

python scripts/rolling_train_and_backtest.py

if [ $? -ne 0 ]; then
    echo "ERROR: Rolling backtest failed"
    exit 1
fi

echo "✓ Rolling backtest complete"
echo ""

# Step 6: Generate report
echo "=========================================="
echo "STEP 6: Generating Trade Report"
echo "=========================================="
echo ""

python scripts/generate_trade_report.py

echo ""
echo "=========================================="
echo "PIPELINE COMPLETE"
echo "=========================================="
echo ""
echo "Results:"
echo "  - Daily features: run/daily_features_rolling/features.parquet"
echo "  - SIP membership: run/sip_membership_rolling/sip_membership.parquet"
echo "  - Intraday features: run/intraday_features_rolling/features.parquet"
echo "  - Metrics: run/rolling_results/metrics.csv"
echo "  - Trades: run/rolling_results/trades.csv"
echo "  - Models: run/rolling_results/models/"
echo ""
echo "Total time: ~10-12 hours"
echo ""
