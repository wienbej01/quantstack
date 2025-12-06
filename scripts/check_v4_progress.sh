#!/bin/bash
# Monitor v4 training data generation progress

echo "=== v4 Training Data Generation Status ==="
echo ""

# Check if process is running
if pgrep -f "generate_training_data_subset.py" > /dev/null; then
    echo "✓ Data generation RUNNING"
    echo ""
    echo "Last 10 log lines:"
    tail -10 /tmp/v4_data_gen.log
else
    echo "✗ Data generation NOT running"
    
    # Check if completed
    if [ -f "artefacts/extensions/intraday_ml/v4_subset_100/training_data.parquet" ]; then
        echo "✓ Training data EXISTS"
        
        # Check size
        python -c "
import pandas as pd
df = pd.read_parquet('artefacts/extensions/intraday_ml/v4_subset_100/training_data.parquet')
print(f'  Rows: {len(df):,}')
print(f'  Symbols: {df[\"symbol\"].nunique()}')
print(f'  Date range: {df[\"ts\"].min()} to {df[\"ts\"].max()}')
"
        echo ""
        echo "✓ Ready for training!"
        echo "Run: python scripts/train_v4_subset.py"
    else
        echo "✗ Training data NOT found"
        echo ""
        echo "Check logs: tail -50 /tmp/v4_data_gen.log"
    fi
fi

echo ""
echo "=== End Status ==="
