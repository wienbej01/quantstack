#!/usr/bin/env python3
"""
Direct VWAP test without SIP complexity to validate timestamp fix
"""

import sys

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


def run_direct_vwap_test():
    """Run direct VWAP test without SIP filtering"""
    print("=" * 80)
    print("DIRECT VWAP BACKTEST TEST (NO SIP)")
    print("=" * 80)

    # Load a few symbols with recent data
    print("\nLoading real data...")
    symbols = ["AAPL", "MSFT", "GOOGL"]
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

    # Fix data structure - convert milliseconds to nanoseconds
    print("Converting timestamps to nanoseconds...")
    bars_df["ts"] = bars_df["ts"] * 1_000_000  # Convert ms to ns
    print(f"  Sample new ts: {bars_df['ts'].iloc[0]}")
    print(f"  New ts > 1e15: {bars_df['ts'].iloc[0] > 1e15}")
    print("  ✓ Converted milliseconds to nanoseconds")

    # Sort for backtest engine
    bars_df = bars_df.sort_values("ts").reset_index(drop=True)
    print("  ✓ Sorted by timestamp")

    # Apply features
    print("Applying features...")
    start_time = pd.Timestamp.now()
    bars_df = core_basics.compute_all_core_features(bars_df)
    elapsed = (pd.Timestamp.now() - start_time).total_seconds()
    print(f"✓ Features applied in {elapsed:.1f}s")

    # Test timestamp conversion manually
    print("\nTesting timestamp conversion...")
    sample_ts = bars_df["ts"].iloc[0]
    print(f"Sample timestamp: {sample_ts}")
    print(f"Raw timestamp type: {type(sample_ts)}")
    print(f"NANOSECOND_THRESHOLD: {1e15}")
    print(f"Timestamp > threshold: {sample_ts > 1e15}")

    # Test conversion
    try:
        if sample_ts > 1e15:
            dt = pd.to_datetime(sample_ts, unit="ns")
            print("  Using nanosecond conversion")
        else:
            dt = pd.to_datetime(sample_ts, unit="ms")
            print("  Using millisecond conversion")
        print(f"  ✓ Converted to: {dt}")
        date = dt.date()
        print(f"  ✓ Date: {date}")
    except Exception as e:
        print(f"  ✗ Conversion failed: {e}")
        return

    # Setup backtest WITHOUT SIP
    print("\nSetting up backtest (NO SIP)...")
    config = BacktestConfig(initial_cash=100000)

    # IMPORTANT: No SIP config to bypass SIP logic
    engine = BacktestEngine(config, sip_config=None)

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
    print(f"  SIP config: {engine.sip_config}")

    # Simple strategy function
    def vwap_strategy(engine, bar):
        policy.process_bar(bar)

    policy.engine = engine

    # Run backtest
    print("\nRunning backtest...")
    try:
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
            print("✅ System is working properly!")
        else:
            print("\n⚠️  No trades generated - may need parameter tuning")

    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)
    print("DIRECT VWAP TEST COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    run_direct_vwap_test()
