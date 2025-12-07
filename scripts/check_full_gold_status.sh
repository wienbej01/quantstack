#!/bin/bash
# Check status of full gold universe workflow

echo "================================================================================"
echo "FULL GOLD UNIVERSE WORKFLOW STATUS"
echo "================================================================================"
echo ""

# Step 1: Feature Store
echo "STEP 1: Feature Store Build"
echo "----------------------------"
if [ -f "/tmp/build_features_full_gold.log" ]; then
    echo "Status: RUNNING"
    echo ""
    echo "Latest batch:"
    grep 'Processing batch' /tmp/build_features_full_gold.log | tail -1
    echo ""
    echo "Latest heartbeat:"
    grep 'HEARTBEAT' /tmp/build_features_full_gold.log | tail -1
    echo ""
    
    if grep -q 'Feature Store Build Complete' /tmp/build_features_full_gold.log; then
        echo "✅ COMPLETE"
        echo ""
        grep 'Total rows:' /tmp/build_features_full_gold.log | tail -1
        grep 'Unique symbols:' /tmp/build_features_full_gold.log | tail -1
        grep 'Unique dates:' /tmp/build_features_full_gold.log | tail -1
    else
        echo "⏳ IN PROGRESS"
    fi
else
    echo "❌ NOT STARTED"
fi

echo ""
echo "================================================================================"
echo ""

# Check output file
if [ -f "run/daily_features_full_gold_6months/features.parquet" ]; then
    echo "Output file exists:"
    ls -lh run/daily_features_full_gold_6months/features.parquet
    echo ""
    echo "Quick stats:"
    python3 -c "
import pandas as pd
try:
    df = pd.read_parquet('run/daily_features_full_gold_6months/features.parquet')
    print(f'  Rows: {len(df):,}')
    print(f'  Symbols: {df[\"symbol\"].nunique()}')
    print(f'  Dates: {df[\"date\"].nunique()}')
except Exception as e:
    print(f'  Error reading file: {e}')
" 2>/dev/null || echo "  (pandas not available)"
fi

echo ""
echo "================================================================================"
echo "NEXT STEPS"
echo "================================================================================"
echo ""
echo "When Step 1 completes:"
echo "  python scripts/generate_smb_sip_full_gold_6months.py"
echo ""
echo "Monitor progress:"
echo "  tail -f /tmp/build_features_full_gold.log"
echo ""
echo "================================================================================"
