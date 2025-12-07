#!/bin/bash
# Master script to run rolling training pipeline

set -e

echo "================================================================================"
echo "ROLLING TRAINING PIPELINE"
echo "================================================================================"
echo ""

# Step 1: Build daily features
echo "Step 1/5: Building daily features (2023-07 to 2025-09)..."
python scripts/build_daily_features_rolling.py
echo "✓ Daily features complete"
echo ""

# Step 2: Generate SIP membership
echo "Step 2/5: Generating SIP membership..."
python scripts/generate_sip_rolling.py
echo "✓ SIP membership complete"
echo ""

# Step 3: Build intraday features
echo "Step 3/5: Building intraday features with 30 ICT..."
python scripts/build_intraday_features_rolling.py
echo "✓ Intraday features complete"
echo ""

# Step 4: Run rolling training and backtest
echo "Step 4/5: Running rolling training (20 iterations)..."
python scripts/rolling_train_and_backtest.py
echo "✓ Rolling training complete"
echo ""

# Step 5: Analyze results
echo "Step 5/5: Analyzing results..."
python scripts/analyze_rolling_results.py
echo "✓ Analysis complete"
echo ""

echo "================================================================================"
echo "PIPELINE COMPLETE"
echo "================================================================================"
echo "Results: run/rolling_results/"
echo "Metrics: run/rolling_results/metrics.csv"
echo "Report: run/rolling_results/analysis_report.txt"
