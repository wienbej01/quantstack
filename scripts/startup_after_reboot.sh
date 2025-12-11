#!/bin/bash
# Quick startup script after reboot to resume rolling training pipeline

set -e

echo "=========================================="
echo "POST-REBOOT STARTUP"
echo "=========================================="
echo ""

# 1. Mount GCS
echo "Step 1: Mounting GCS..."
mkdir -p /home/jacobw/gcs-mount
gcsfuse --implicit-dirs jwss_data_store /home/jacobw/gcs-mount

# Verify mount
if ls /home/jacobw/gcs-mount/gold/stocks/1m/ > /dev/null 2>&1; then
    echo "✓ GCS mounted successfully"
    echo "  Symbols available: $(ls /home/jacobw/gcs-mount/gold/stocks/1m/ | wc -l)"
else
    echo "✗ GCS mount failed!"
    exit 1
fi

echo ""

# 2. Check checkpoint
echo "Step 2: Checking checkpoint..."
if [ -f "run/daily_features_rolling/features_temp.parquet" ]; then
    echo "✓ Checkpoint found"
    ls -lh run/daily_features_rolling/features_temp.parquet
else
    echo "✗ No checkpoint found - will start from beginning"
fi

echo ""

# 3. Start pipeline
echo "Step 3: Starting rolling training pipeline..."
cd /home/jacobw/quantstack
nohup python scripts/build_daily_features_rolling.py > /tmp/build_daily_rolling.log 2>&1 &
PID=$!
echo "✓ Pipeline started with PID: $PID"

echo ""
echo "=========================================="
echo "MONITORING"
echo "=========================================="
echo "Log file: /tmp/build_daily_rolling.log"
echo ""
echo "Monitor with:"
echo "  tail -f /tmp/build_daily_rolling.log"
echo ""
echo "Check progress:"
echo "  tail -20 /tmp/build_daily_rolling.log"
echo ""

# Wait a moment and show initial output
sleep 3
echo "Initial output:"
tail -15 /tmp/build_daily_rolling.log
