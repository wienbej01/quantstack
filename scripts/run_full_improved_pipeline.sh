#!/bin/bash
# Full improved system pipeline

set -e  # Exit on error

LOG_DIR="/tmp"
START_TIME=$(date)

echo "=========================================="
echo "FULL IMPROVED SYSTEM PIPELINE"
echo "Started: $START_TIME"
echo "=========================================="

# Step 1: Build improved features (if not already running)
echo ""
echo "=== STEP 1: IMPROVED FEATURES ==="
if pgrep -f "build_intraday_features_improved" > /dev/null; then
    echo "✅ Feature build already running"
    echo "Monitoring progress..."
    
    # Wait for completion with progress updates
    while pgrep -f "build_intraday_features_improved" > /dev/null; do
        echo "$(date): Still building features..."
        tail -3 /tmp/build_improved_features.log 2>/dev/null || echo "Log not available yet"
        sleep 60
    done
    
    echo "Feature build completed. Checking results..."
else
    echo "Starting improved feature build..."
    nohup python scripts/build_intraday_features_improved.py > $LOG_DIR/build_improved_features.log 2>&1 &
    
    # Wait for completion
    while pgrep -f "build_intraday_features_improved" > /dev/null; do
        echo "$(date): Building features..."
        sleep 60
    done
fi

# Check if features were generated
if [ -f "run/intraday_features_improved/features.parquet" ]; then
    echo "✅ Improved features generated successfully"
    
    # Show summary
    python3 << 'EOF'
import pandas as pd
df = pd.read_parquet("run/intraday_features_improved/features.parquet")
print(f"Rows: {len(df):,}")
print(f"Symbols: {df['symbol'].nunique()}")
print(f"Date range: {df['date'].min()} to {df['date'].max()}")
print(f"ATR label rates: Long {df.get('label_long_atr', df['label_long']).mean()*100:.2f}%")
EOF
else
    echo "❌ Feature generation failed"
    echo "Last 20 lines of log:"
    tail -20 $LOG_DIR/build_improved_features.log
    exit 1
fi

# Step 2: Run improved training
echo ""
echo "=== STEP 2: IMPROVED TRAINING ==="
echo "Starting improved rolling training..."

python scripts/rolling_train_improved.py > $LOG_DIR/rolling_train_improved.log 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Improved training completed"
else
    echo "❌ Training failed"
    tail -20 $LOG_DIR/rolling_train_improved.log
    exit 1
fi

# Step 3: Generate comparison report
echo ""
echo "=== STEP 3: COMPARISON REPORT ==="

python3 << 'EOF'
import pandas as pd
import numpy as np
from pathlib import Path

print("IMPROVED SYSTEM vs ORIGINAL COMPARISON")
print("=" * 60)

# Load results
improved_path = Path("run/rolling_results_improved/trades.csv")
original_path = Path("run/rolling_hybrid_optimal/trades.csv")

if improved_path.exists() and original_path.exists():
    improved = pd.read_csv(improved_path)
    original = pd.read_csv(original_path)
    
    print(f"{'Metric':<25} {'Original':<15} {'Improved':<15} {'Change':<15}")
    print("-" * 70)
    
    # Basic metrics
    print(f"{'Total trades':<25} {len(original):<15} {len(improved):<15} {len(improved)-len(original):+d}")
    
    orig_win = (original['net_pnl'] > 0).mean() * 100
    imp_win = (improved['net_pnl'] > 0).mean() * 100
    print(f"{'Win rate':<25} {orig_win:<15.1f}% {imp_win:<15.1f}% {imp_win-orig_win:+.1f}%")
    
    orig_pnl = original['net_pnl'].sum()
    imp_pnl = improved['net_pnl'].sum()
    print(f"{'Total PnL':<25} ${orig_pnl:<14,.0f} ${imp_pnl:<14,.0f} ${imp_pnl-orig_pnl:+,.0f}")
    
    # Symbol diversity
    orig_symbols = original['symbol'].nunique()
    imp_symbols = improved['symbol'].nunique()
    print(f"{'Unique symbols':<25} {orig_symbols:<15} {imp_symbols:<15} {imp_symbols-orig_symbols:+d}")
    
    # Monthly consistency
    orig_monthly = original.groupby(pd.to_datetime(original['entry_timestamp']).dt.to_period('M'))['net_pnl'].sum()
    imp_monthly = improved.groupby(pd.to_datetime(improved['entry_timestamp']).dt.to_period('M'))['net_pnl'].sum()
    
    orig_profitable = (orig_monthly > 0).sum()
    imp_profitable = (imp_monthly > 0).sum()
    
    print(f"{'Profitable months':<25} {orig_profitable}/{len(orig_monthly):<14} {imp_profitable}/{len(imp_monthly):<14}")
    
    print("\n" + "=" * 60)
    print("CONSISTENCY ANALYSIS")
    print("-" * 60)
    
    print(f"Original monthly PnL std: ${orig_monthly.std():,.0f}")
    print(f"Improved monthly PnL std: ${imp_monthly.std():,.0f}")
    
    # Symbol concentration
    orig_top = original.groupby('symbol')['net_pnl'].sum().nlargest(3).sum()
    imp_top = improved.groupby('symbol')['net_pnl'].sum().nlargest(3).sum()
    
    print(f"Original top 3 symbols: ${orig_top:,.0f} ({orig_top/orig_pnl*100:.0f}% of total)")
    print(f"Improved top 3 symbols: ${imp_top:,.0f} ({imp_top/imp_pnl*100:.0f}% of total)")
    
else:
    print("Results files not found")
    if not improved_path.exists():
        print(f"Missing: {improved_path}")
    if not original_path.exists():
        print(f"Missing: {original_path}")
EOF

echo ""
echo "=========================================="
echo "PIPELINE COMPLETED"
echo "Started: $START_TIME"
echo "Ended: $(date)"
echo "=========================================="

# Show final file locations
echo ""
echo "=== OUTPUT FILES ==="
echo "Improved features: run/intraday_features_improved/features.parquet"
echo "Improved trades: run/rolling_results_improved/trades.csv"
echo "Improved metrics: run/rolling_results_improved/metrics.csv"
echo "Logs: $LOG_DIR/build_improved_features.log, $LOG_DIR/rolling_train_improved.log"
