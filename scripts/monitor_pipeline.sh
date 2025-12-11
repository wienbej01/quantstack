#!/bin/bash
# Monitor the fixed pipeline progress

echo "=========================================="
echo "PIPELINE PROGRESS MONITOR"
echo "Time: $(date)"
echo "=========================================="
echo ""

# Check if pipeline is running
PIPELINE_PID=$(pgrep -f "run_full_fixed_pipeline.sh")
if [ -z "$PIPELINE_PID" ]; then
    echo "⚠️  Pipeline not running"
else
    echo "✓ Pipeline running (PID: $PIPELINE_PID)"
fi
echo ""

# Check current step
echo "Current Step:"
echo "-------------"
if [ -f /tmp/build_daily_features.log ]; then
    if [ -f run/daily_features_rolling/features.parquet ]; then
        echo "✓ Step 1: Daily features COMPLETE"
    else
        LAST_LINE=$(tail -1 /tmp/build_daily_features.log)
        echo "🟡 Step 1: Daily features IN PROGRESS"
        echo "   $LAST_LINE"
    fi
fi

if [ -f /tmp/generate_sip.log ]; then
    if [ -f run/sip_membership_rolling/sip_membership.parquet ]; then
        echo "✓ Step 2: SIP membership COMPLETE"
    else
        echo "🟡 Step 2: SIP membership IN PROGRESS"
    fi
fi

if [ -f /tmp/build_intraday_fixed.log ]; then
    if [ -f run/intraday_features_rolling/features.parquet ]; then
        echo "✓ Step 3: Intraday features COMPLETE"
    else
        LAST_LINE=$(tail -1 /tmp/build_intraday_fixed.log)
        echo "🟡 Step 3: Intraday features IN PROGRESS"
        echo "   $LAST_LINE"
    fi
fi

if [ -f /tmp/rolling_train.log ]; then
    if [ -f run/rolling_results/trades.csv ]; then
        echo "✓ Step 5: Training and backtest COMPLETE"
    else
        LAST_LINE=$(tail -1 /tmp/rolling_train.log)
        echo "🟡 Step 5: Training and backtest IN PROGRESS"
        echo "   $LAST_LINE"
    fi
fi

if [ -f run/rolling_results/trade_report.txt ]; then
    echo "✓ Step 6: Report COMPLETE"
fi

echo ""
echo "Output Files:"
echo "-------------"
if [ -f run/daily_features_rolling/features.parquet ]; then
    SIZE=$(du -h run/daily_features_rolling/features.parquet | cut -f1)
    echo "✓ Daily features: $SIZE"
fi

if [ -f run/sip_membership_rolling/sip_membership.parquet ]; then
    SIZE=$(du -h run/sip_membership_rolling/sip_membership.parquet | cut -f1)
    echo "✓ SIP membership: $SIZE"
fi

if [ -f run/intraday_features_rolling/features.parquet ]; then
    SIZE=$(du -h run/intraday_features_rolling/features.parquet | cut -f1)
    ROWS=$(python3 -c "import polars as pl; print(f'{len(pl.read_parquet(\"run/intraday_features_rolling/features.parquet\")):,}')" 2>/dev/null || echo "?")
    echo "✓ Intraday features: $SIZE ($ROWS rows)"
fi

if [ -f run/rolling_results/trades.csv ]; then
    ROWS=$(wc -l < run/rolling_results/trades.csv)
    echo "✓ Trades: $((ROWS-1)) trades"
fi

echo ""
echo "Recent Logs:"
echo "------------"
if [ -f /tmp/full_pipeline.log ]; then
    echo "Main pipeline:"
    tail -3 /tmp/full_pipeline.log | sed 's/^/  /'
fi

if [ -f /tmp/build_daily_features.log ]; then
    echo "Daily features:"
    tail -3 /tmp/build_daily_features.log | sed 's/^/  /'
fi

if [ -f /tmp/build_intraday_fixed.log ]; then
    echo "Intraday features:"
    tail -3 /tmp/build_intraday_fixed.log | sed 's/^/  /'
fi

echo ""
echo "Commands:"
echo "---------"
echo "  Watch main log:     tail -f /tmp/full_pipeline.log"
echo "  Watch daily build:  tail -f /tmp/build_daily_features.log"
echo "  Watch intraday:     tail -f /tmp/build_intraday_fixed.log"
echo "  Watch training:     tail -f /tmp/rolling_train.log"
echo ""
