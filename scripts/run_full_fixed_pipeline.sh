#!/bin/bash
# Complete fixed pipeline: Daily features -> SIP -> Intraday features -> Training -> Report

set -e

echo "=========================================="
echo "COMPLETE FIXED PIPELINE"
echo "Date: $(date)"
echo "=========================================="
echo ""

# Step 1: Build daily features
echo "Step 1: Building daily features..."
echo "  - Date range: 2023-01-01 to 2025-09-30"
echo "  - Universe: Full gold (1,108 symbols)"
echo "  - ETA: 2-3 hours"
echo ""

python scripts/build_daily_features_rolling.py > /tmp/build_daily_features.log 2>&1
echo "✓ Daily features complete"
echo ""

# Step 2: Generate SIP membership
echo "Step 2: Generating SIP membership..."
echo "  - Top 50 stocks per day"
echo "  - Filters: gap≥2%, ATR≥$0.70, ADV≥1M"
echo "  - ETA: <1 minute"
echo ""

python scripts/generate_sip_rolling.py > /tmp/generate_sip.log 2>&1
echo "✓ SIP membership complete"
echo ""

# Step 3: Build intraday features
echo "Step 3: Building intraday features..."
echo "  - 1m granularity"
echo "  - Entry on bar AFTER signal (no leakage)"
echo "  - Same-day exits only"
echo "  - ATR calculation included"
echo "  - ETA: 4-6 hours"
echo ""

python scripts/build_intraday_features_rolling.py > /tmp/build_intraday_fixed.log 2>&1
echo "✓ Intraday features complete"
echo ""

# Step 4: Validate no leakage
echo "Step 4: Validating no data leakage..."
python scripts/validate_no_leakage.py
echo ""

# Step 5: Run rolling training and backtest
echo "Step 5: Running rolling training and backtest..."
echo "  - 26 OOS months (2023-08 to 2025-09)"
echo "  - Entry delay: 1 bar"
echo "  - ATR-based stops: 1.5x ATR"
echo "  - Take profit: 2R"
echo "  - Position sizing: 1% risk"
echo "  - ETA: 3-4 hours"
echo ""

python scripts/rolling_train_and_backtest.py > /tmp/rolling_train.log 2>&1
echo "✓ Training and backtest complete"
echo ""

# Step 6: Generate trade report
echo "Step 6: Generating trade report..."
python scripts/generate_trade_report.py > /tmp/trade_report.log 2>&1
echo "✓ Report complete"
echo ""

echo "=========================================="
echo "PIPELINE COMPLETE"
echo "Completed: $(date)"
echo "=========================================="
echo ""
echo "Results:"
echo "  - Daily features: run/daily_features_rolling/features.parquet"
echo "  - SIP membership: run/sip_membership_rolling/sip_membership.parquet"
echo "  - Intraday features: run/intraday_features_rolling/features.parquet"
echo "  - Metrics: run/rolling_results/metrics.csv"
echo "  - Trades: run/rolling_results/trades.csv"
echo "  - Models: run/rolling_results/models/"
echo "  - Report: run/rolling_results/trade_report.txt"
echo ""
echo "View report:"
echo "  cat run/rolling_results/trade_report.txt"
echo ""
