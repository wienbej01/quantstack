#!/usr/bin/env python3
"""Monitor enhanced pipeline progress."""

import subprocess
from pathlib import Path


def check_enhanced_pipeline_status():
    """Check enhanced pipeline status."""

    # Check processes
    try:
        result = subprocess.run(
            ["pgrep", "-f", "build_enhanced_features"],
            capture_output=True,
            text=True,
            check=False,
        )
        building_features = len(result.stdout.strip()) > 0

        result = subprocess.run(
            ["pgrep", "-f", "train_enhanced_model"],
            capture_output=True,
            text=True,
            check=False,
        )
        training = len(result.stdout.strip()) > 0

        result = subprocess.run(
            ["pgrep", "-f", "run_enhanced_pipeline"],
            capture_output=True,
            text=True,
            check=False,
        )
        pipeline_running = len(result.stdout.strip()) > 0

    except:
        building_features = training = pipeline_running = False

    # Check files
    features_path = Path("run/enhanced_features/features.parquet")
    metrics_path = Path("run/enhanced_results/metrics.csv")
    trades_path = Path("run/enhanced_results/trades.csv")

    features_exist = features_path.exists()
    results_exist = metrics_path.exists() and trades_path.exists()

    print("=" * 60)
    print("ENHANCED PIPELINE MONITOR")
    print("=" * 60)
    print(f"Pipeline Status: {'🟢 RUNNING' if pipeline_running else '🔴 STOPPED'}")
    print(
        f"Feature Building: {'🟡 IN PROGRESS' if building_features else ('✅ DONE' if features_exist else '⏳ PENDING')}"
    )
    print(
        f"Model Training: {'🟡 IN PROGRESS' if training else ('✅ DONE' if results_exist else '⏳ PENDING')}"
    )

    if features_exist:
        try:
            import polars as pl

            df = pl.read_parquet(features_path)
            print(
                f"Enhanced Features: {len(df):,} rows, {len(df.columns)} columns, {df['symbol'].n_unique()} symbols"
            )
        except:
            print("Enhanced Features: File exists but couldn't read")

    if results_exist:
        try:
            import pandas as pd

            metrics = pd.read_csv(metrics_path)
            trades = pd.read_csv(trades_path)
            win_rate = (trades["net_pnl"] > 0).mean()
            total_pnl = trades["net_pnl"].sum()
            avg_auc = metrics["auc_long"].mean()
            print(f"Enhanced Results: {len(metrics)} months, {len(trades)} trades")
            print(
                f"Performance: {win_rate:.1%} win rate, ${total_pnl:,.0f} PnL, {avg_auc:.3f} avg AUC"
            )
        except:
            print("Enhanced Results: Files exist but couldn't read")

    # Show recent log
    log_path = Path("/tmp/enhanced_pipeline.log")
    if log_path.exists():
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()
                recent = [
                    line.strip() for line in lines[-3:] if "FutureWarning" not in line
                ]
                if recent:
                    print("\nRecent progress:")
                    for line in recent:
                        print(f"  {line}")
        except:
            pass

    return pipeline_running


if __name__ == "__main__":
    running = check_enhanced_pipeline_status()

    if running:
        print(f"\n⏰ Enhanced pipeline is running.")
        print(f"📋 Full log: tail -f /tmp/enhanced_pipeline.log")
        print(f"🔍 Monitor: python scripts/monitor_enhanced_pipeline.py")
    else:
        print(f"\n🏁 Enhanced pipeline completed or stopped.")
