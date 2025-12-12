#!/usr/bin/env python3
"""Monitor fixed pipeline progress."""

import time
from pathlib import Path
import subprocess

def check_pipeline_status():
    """Check if pipeline is running and show progress."""
    
    # Check if processes are running
    try:
        result = subprocess.run(['pgrep', '-f', 'build_intraday_features_fixed'], 
                              capture_output=True, text=True)
        building_features = len(result.stdout.strip()) > 0
        
        result = subprocess.run(['pgrep', '-f', 'rolling_train_fixed'], 
                              capture_output=True, text=True)
        training = len(result.stdout.strip()) > 0
        
        result = subprocess.run(['pgrep', '-f', 'run_fixed_pipeline'], 
                              capture_output=True, text=True)
        pipeline_running = len(result.stdout.strip()) > 0
        
    except:
        building_features = training = pipeline_running = False
    
    # Check output files
    features_path = Path("run/intraday_features_fixed/features.parquet")
    metrics_path = Path("run/rolling_results_fixed/metrics.csv")
    trades_path = Path("run/rolling_results_fixed/trades.csv")
    
    features_exist = features_path.exists()
    results_exist = metrics_path.exists() and trades_path.exists()
    
    # Show status
    print(f"Pipeline Status: {'🟢 RUNNING' if pipeline_running else '🔴 STOPPED'}")
    print(f"Feature Building: {'🟡 IN PROGRESS' if building_features else ('✅ DONE' if features_exist else '⏳ PENDING')}")
    print(f"Model Training: {'🟡 IN PROGRESS' if training else ('✅ DONE' if results_exist else '⏳ PENDING')}")
    
    if features_exist:
        try:
            import polars as pl
            df = pl.read_parquet(features_path)
            print(f"Features: {len(df):,} rows, {df['symbol'].n_unique()} symbols")
        except:
            print("Features: File exists but couldn't read")
    
    if results_exist:
        try:
            import pandas as pd
            metrics = pd.read_csv(metrics_path)
            trades = pd.read_csv(trades_path)
            print(f"Results: {len(metrics)} months, {len(trades)} trades")
            if len(trades) > 0:
                win_rate = (trades['net_pnl'] > 0).mean()
                total_pnl = trades['net_pnl'].sum()
                print(f"Performance: {win_rate:.1%} win rate, ${total_pnl:,.0f} total PnL")
        except:
            print("Results: Files exist but couldn't read")
    
    # Show recent log
    log_path = Path("/tmp/fixed_pipeline.log")
    if log_path.exists():
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()
                recent = lines[-5:] if len(lines) >= 5 else lines
                print("\nRecent log:")
                for line in recent:
                    print(f"  {line.strip()}")
        except:
            pass
    
    return pipeline_running

if __name__ == "__main__":
    print("=" * 60)
    print("FIXED PIPELINE MONITOR")
    print("=" * 60)
    
    running = check_pipeline_status()
    
    if running:
        print(f"\n⏰ Pipeline is running. Check again with:")
        print(f"   python scripts/monitor_fixed_pipeline.py")
        print(f"\n📋 Full log: tail -f /tmp/fixed_pipeline.log")
    else:
        print(f"\n🏁 Pipeline completed or stopped.")
