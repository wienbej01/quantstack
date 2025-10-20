#!/usr/bin/env python3
"""Focused test with limited data for daily HMM_SIP."""

import os
import sys
from pathlib import Path

import pandas as pd
import yaml

# Add all qx modules to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "qx-core" / "src"))
sys.path.insert(0, str(project_root / "qx-data" / "src"))
sys.path.insert(0, str(project_root / "qx-features" / "src"))
sys.path.insert(0, str(project_root / "qx-screener" / "src"))
sys.path.insert(0, str(project_root / "qx-backtest" / "src"))

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.policies.vwap_revert import VwapRevertPolicy
from qx_core.validators import validate_bars_dataframe
from qx_data.gold_loader import load_bars
from qx_features.core_basics import compute_all_core_features
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


def main():
    print("Focused Daily HMM_SIP VWAP Test")
    print("=" * 50)

    # Load configuration
    config_path = (
        Path(__file__).parent / "experiments" / "vwap_revert" / "strategy.yaml"
    )
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Use smaller dataset for testing
    test_symbols = ["AAPL", "MSFT", "GOOGL"]  # Just 3 symbols
    test_dates = ["2024-01-03", "2024-01-04", "2024-01-05"]  # Just 3 days

    print(f"Testing with {len(test_symbols)} symbols: {test_symbols}")
    print(f"Date range: {test_dates[0]} to {test_dates[-1]}")

    # Load data
    print("\nLoading data...")
    bars = load_bars(
        root=config["gold_root"],
        family=config["family"],
        symbols=test_symbols,
        dates=test_dates,
        validate=False,
    )

    print(f"✓ Loaded {len(bars):,} bars")

    # Fix timestamps - they appear to be in milliseconds, not seconds
    print(f"Original timestamp range: {bars['ts'].min()} to {bars['ts'].max()}")

    # Check if timestamps are in milliseconds (typical for financial data)
    if bars["ts"].max() < 1e15:  # Less than nanoseconds
        if bars["ts"].max() > 1e12:  # More than seconds
            # Likely milliseconds, convert to nanoseconds
            bars["ts"] = bars["ts"] * 1_000_000
            print("Converted milliseconds to nanoseconds")
        else:
            # Likely seconds, convert to nanoseconds
            bars["ts"] = bars["ts"] * 1_000_000_000
            print("Converted seconds to nanoseconds")

    # Convert timestamps for display
    bars["dt"] = pd.to_datetime(bars["ts"], unit="ns")
    print(f"Date range: {bars['dt'].min()} to {bars['dt'].max()}")

    # Remove duplicates
    before = len(bars)
    bars = bars.drop_duplicates(subset=["symbol", "ts"], keep="last")
    after = len(bars)
    if before != after:
        print(f"Removed {before - after} duplicates")

    print(f"Final dataset: {len(bars):,} bars")

    # Validate data
    try:
        validate_bars_dataframe(bars)
        print("✓ Data validation passed")
    except Exception as e:
        print(f"✗ Data validation failed: {e}")
        return

    # Sort data by timestamp (required for backtest engine)
    print("Sorting data by timestamp...")
    bars = bars.sort_values("ts").reset_index(drop=True)

    # Apply features
    print("\nApplying features...")
    feature_params = config["features"][0]["params"]
    feature_df = compute_all_core_features(
        bars,
        vwap_window=feature_params["vwap_window_m"],
        rvol_window=feature_params["rel_vol_window_m"],
        atr_window=feature_params["atr_window"],
    )
    print(f"✓ Features applied, shape: {feature_df.shape}")

    # Test HMM SIP
    print("\nTesting Daily HMM SIP...")
    sip_config = HMMSIPConfig(
        mode="daily",
        score_floor=0.0,
        top_k=min(3, len(test_symbols)),  # Don't exceed available symbols
        enable_gold_fallback=True,
    )

    sip_selector = HMMSIPUniverseSelector(sip_config)
    ref_context = {"target_date": test_dates[0]}

    try:
        universe_map = sip_selector.select(feature_df, ref_context)
        print(f"✓ HMM SIP completed, universe for {len(universe_map)} timestamps")

        if universe_map:
            avg_size = sum(len(s) for s in universe_map.values()) / len(universe_map)
            print(f"Average universe size: {avg_size:.1f}")

            first_ts = min(universe_map.keys())
            first_universe = sorted(list(universe_map[first_ts]))
            print(
                f"Example universe at {pd.to_datetime(first_ts, unit='ns')}: {first_universe}"
            )
    except Exception as e:
        print(f"✗ HMM SIP failed: {e}")
        import traceback

        traceback.print_exc()
        return

    # Test backtest engine
    print("\nTesting Backtest Engine...")
    backtest_config = BacktestConfig(initial_cash=100000, show_progress=True)

    # Create SIP config for engine
    sip_config_dict = {
        "sip_method": "hmm",
        "sip_config": {
            "mode": "daily",
            "top_k": min(3, len(test_symbols)),
            "score_floor": 0.0,
        },
    }

    # Monkey patch the engine to provide proper reference context
    original_update_universe = BacktestEngine._update_universe_if_needed

    def patched_update_universe(self, bar: dict, bars_df: pd.DataFrame) -> None:
        """Patched version that provides target_date in reference context."""
        # Call original method but intercept the SIP selector call
        if not self._check_universe_update_needed(bar):
            return original_update_universe(self, bar, bars_df)

        # Handle nanosecond timestamps (we already converted to ns)
        ts = bar["ts"]
        bar_date = pd.to_datetime(ts, unit="ns").date()
        self._last_processed_date = bar_date

        # If we already have universe for this day, use it
        if bar_date in self._daily_universes:
            self._current_universe = self._daily_universes[bar_date]
            return

        # Otherwise, compute new universe using SIP selector with proper context
        if hasattr(self, "_sip_selector") and self._sip_selector:
            # Get all bars for this trading day
            bars_df["date"] = pd.to_datetime(bars_df["ts"], unit="ns").dt.date
            day_bars = bars_df[bars_df["date"] == bar_date]

            if not day_bars.empty:
                # Remove the date column for processing
                day_bars_clean = day_bars.drop(columns=["date"])
                # Provide proper reference context with target_date
                ref_context = {"target_date": bar_date.strftime("%Y-%m-%d")}
                universe_map = self._sip_selector.select(day_bars_clean, ref_context)
                if universe_map:
                    first_ts = min(universe_map.keys())
                    new_universe = universe_map[first_ts]
                    self._update_daily_universe(bar_date, new_universe)

    # Apply monkey patch
    BacktestEngine._update_universe_if_needed = patched_update_universe

    engine = BacktestEngine(backtest_config, sip_config_dict)
    engine._sip_selector = sip_selector

    # Create VWAP policy
    policy_params = config["policy_params"]
    policy = VwapRevertPolicy(
        vwap_window=policy_params["vwap_window_m"],
        min_rvol=0.5,  # Lower threshold for testing
        max_position_bars=policy_params["max_position_bars"],
    )

    def vwap_strategy(engine, bar):
        """VWAP reversion strategy."""
        # Attach engine to policy if not already attached
        if not hasattr(policy, "engine") or policy.engine != engine:
            policy.engine = engine

        policy.process_bar(bar)

    print("Running backtest...")
    try:
        result = engine.run(feature_df, vwap_strategy)
        print("✓ Backtest completed successfully!")

        # Display results
        print(f"\nBacktest Results:")
        print(f"  Total Return: {result.total_return:.2%}")
        print(f"  Total Trades: {result.total_trades}")
        print(f"  Win Rate: {result.win_rate:.2%}")
        print(f"  Final Equity: ${result.equity_curve['total_equity'].iloc[-1]:,.2f}")

        if result.trades_history:
            trades_df = pd.DataFrame(result.trades_history)
            print(f"  Trade Count by Symbol:")
            symbol_counts = trades_df.groupby("symbol").size()
            for symbol, count in symbol_counts.items():
                print(f"    {symbol}: {count} trades")

    except Exception as e:
        print(f"✗ Backtest failed: {e}")
        import traceback

        traceback.print_exc()
        return

    print("\n✓ Focused test completed successfully!")
    print("\nSUMMARY:")
    print(f"- Daily HMM SIP mode: {'✓ WORKING' if universe_map else '✗ FAILED'}")
    print(
        f"- VWAP Strategy: {'✓ WORKING' if result.total_trades > 0 else '✗ NO TRADES'}"
    )
    print(
        f"- Universe Selection: {'✓ WORKING' if len(universe_map) > 0 else '✗ FAILED'}"
    )


if __name__ == "__main__":
    main()
