#!/bin/bash
# Monitor the full rebuild pipeline

echo "=========================================="
echo "PIPELINE MONITORING"
echo "=========================================="
echo ""

# Check if pipeline is running
PIPELINE_PID=$(pgrep -f "run_full_rebuild_2023_2025.sh")
if [ -z "$PIPELINE_PID" ]; then
    echo "Pipeline: NOT RUNNING"
else
    echo "Pipeline: RUNNING (PID: $PIPELINE_PID)"
fi

# Check daily features
DAILY_PID=$(pgrep -f "build_daily_features_rolling.py")
if [ -z "$DAILY_PID" ]; then
    echo "Daily features: NOT RUNNING"
else
    echo "Daily features: RUNNING (PID: $DAILY_PID)"
fi

# Check intraday features
INTRADAY_PID=$(pgrep -f "build_intraday_features_rolling.py")
if [ -z "$INTRADAY_PID" ]; then
    echo "Intraday features: NOT RUNNING"
else
    echo "Intraday features: RUNNING (PID: $INTRADAY_PID)"
fi

# Check rolling backtest
BACKTEST_PID=$(pgrep -f "rolling_train_and_backtest.py")
if [ -z "$BACKTEST_PID" ]; then
    echo "Rolling backtest: NOT RUNNING"
else
    echo "Rolling backtest: RUNNING (PID: $BACKTEST_PID)"
fi

echo ""
echo "=========================================="
echo "PROGRESS"
echo "=========================================="
echo ""

# Daily features progress
if [ -f "/tmp/build_daily_features.log" ]; then
    echo "Daily Features (last 5 lines):"
    tail -5 /tmp/build_daily_features.log | sed 's/^/  /'
    echo ""
fi

# Intraday features progress
if [ -f "/tmp/build_intraday_features.log" ]; then
    echo "Intraday Features (last 5 lines):"
    tail -5 /tmp/build_intraday_features.log | sed 's/^/  /'
    echo ""
fi

# Pipeline progress
if [ -f "/tmp/full_rebuild_pipeline.log" ]; then
    echo "Pipeline (last 10 lines):"
    tail -10 /tmp/full_rebuild_pipeline.log | sed 's/^/  /'
    echo ""
fi

echo "=========================================="
echo "OUTPUT FILES"
echo "=========================================="
echo ""

# Check output files
if [ -f "run/daily_features_rolling/features.parquet" ]; then
    SIZE=$(du -h run/daily_features_rolling/features.parquet | cut -f1)
    echo "✓ Daily features: $SIZE"
else
    echo "⏳ Daily features: pending"
fi

if [ -f "run/sip_membership_rolling/sip_membership.parquet" ]; then
    SIZE=$(du -h run/sip_membership_rolling/sip_membership.parquet | cut -f1)
    echo "✓ SIP membership: $SIZE"
else
    echo "⏳ SIP membership: pending"
fi

if [ -f "run/intraday_features_rolling/features.parquet" ]; then
    SIZE=$(du -h run/intraday_features_rolling/features.parquet | cut -f1)
    echo "✓ Intraday features: $SIZE"
else
    echo "⏳ Intraday features: pending"
fi

if [ -f "run/rolling_results/trades.csv" ]; then
    LINES=$(wc -l < run/rolling_results/trades.csv)
    echo "✓ Trades: $LINES rows"
else
    echo "⏳ Trades: pending"
fi

echo ""
echo "=========================================="
echo "COMMANDS"
echo "=========================================="
echo ""
echo "Watch daily features:    tail -f /tmp/build_daily_features.log"
echo "Watch intraday features: tail -f /tmp/build_intraday_features.log"
echo "Watch pipeline:          tail -f /tmp/full_rebuild_pipeline.log"
echo "Re-run monitor:          ./scripts/monitor_rebuild.sh"
echo ""
