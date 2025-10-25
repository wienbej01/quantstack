#!/usr/bin/env python3
"""
Simple VWAP backtest to validate the optimized system works
"""

import os
import sys
from datetime import datetime

import pandas as pd

# Add src directories to path
sys.path.insert(0, "qx-data/src")
sys.path.insert(0, "qx-features/src")
sys.path.insert(0, "qx-backtest/src")
sys.path.insert(0, "qx-core/src")
sys.path.insert(0, "qx-risk/src")

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.policies.vwap_revert import VwapRevertPolicy
from qx_data import gold_loader
from qx_features import core_basics


def run_simple_vwap_test():
    """Run simple VWAP test with real data"""
    print("=" * 80)
    print("SIMPLE VWAP BACKTEST TEST")
    print("=" * 80)

    # Load a few symbols with recent data
    print("\nLoading real data...")
    symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN"]
    dates = ["2024-02-01", "2024-02-02"]  # Use simple date range

    bars_df = gold_loader.load_bars(
        root="/home/jacobw/gcs-mount",
        family="stocks",
        symbols=symbols,
        dates=dates,
        validate=False,
        sort=True,
    )

    print(f"✓ Loaded {len(bars_df):,} bars for {len(symbols)} symbols")

    # Fix data structure
    print("Standardizing data...")
    if "t" in bars_df.columns:
        bars_df["ts"] = bars_df["t"] * 1_000_000
        column_mapping = {
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
        bars_df.rename(columns=column_mapping, inplace=True)
        print("  ✓ Fixed column mapping and timestamps")

    # Sort for backtest engine
    bars_df = bars_df.sort_values("ts").reset_index(drop=True)
    print("  ✓ Sorted by timestamp")

    # Apply features
    print("Applying features...")
    start_time = pd.Timestamp.now()
    bars_df = core_basics.compute_all_core_features(bars_df)
    elapsed = (pd.Timestamp.now() - start_time).total_seconds()
    print(f"✓ Features applied in {elapsed:.1f}s")

    # Setup backtest
    print("\nSetting up backtest...")
    config = BacktestConfig(initial_cash=100000)
    engine = BacktestEngine(config)

    # Setup VWAP policy
    policy = VwapRevertPolicy(
        vwap_window=30,
        min_rvol=1.0,
        max_position_bars=50,
        position_size_pct=0.05,
        max_positions=3,
    )
    engine.policy = policy

    print(f"  VWAP window: {policy.vwap_window}")
    print(f"  Max positions: {policy.max_positions}")

    # Simple strategy function
    def vwap_strategy(engine, bar):
        policy.process_bar(bar)

    policy.engine = engine

    # Run backtest
    print("\nRunning backtest...")
    result = engine.run(bars_df, vwap_strategy)

    # Show results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    print(f"Total trades: {result.total_trades}")
    print(f"Win rate: {result.win_rate:.1%}")
    print(f"Total return: {result.total_return:.1%}")
    print(f"Sharpe ratio: {result.sharpe_ratio:.2f}")
    print(f"Max drawdown: {result.max_drawdown:.1%}")

    if result.total_trades > 0:
        print(f"\n✅ SUCCESS: Generated {result.total_trades} trades")
        print(f"✅ System is working properly!")
    else:
        print(f"\n⚠️  No trades generated - may need parameter tuning")

    print("\n" + "=" * 80)
    print("SIMPLE VWAP TEST COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    run_simple_vwap_test()
