#!/usr/bin/env python3
"""
Pilot test for HMM_SIP + VWAP system for April 1-5, 2024
Validates: daily ticker selection, VWAP execution, trade generation
"""

import os
import sys
from datetime import datetime

import pandas as pd

# Add src directories to path
sys.path.insert(0, "qx-screener/src")
sys.path.insert(0, "qx-backtest/src")
sys.path.insert(0, "qx-features/src")
sys.path.insert(0, "qx-data/src")
sys.path.insert(0, "qx-core/src")
sys.path.insert(0, "qx-risk/src")

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.policies.vwap_revert import VwapRevertPolicy
from qx_data import gold_loader
from qx_features import core_basics
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


def load_config() -> dict:
    """Load pilot configuration"""
    return {
        "gold_root": "/home/jacobw/gcs-mount",
        "data_family": "stocks",
        "dates": ["2024-06-03"],
        "symbols": ["AAPL"],
        "sip_enabled": False,
        "sip": {
            "method": "hmm",
            "config": {
                "mode": "legacy",
                "score_floor": 0.01,
                "top_k": 20,
                "enable_gold_fallback": True,
            },
        },
        "features": [
            {
                "name": "core_basics",
                "params": {
                    "vwap_window_m": 30,
                    "rel_vol_window_m": 30,
                    "atr_window": 14,
                },
            }
        ],
        "policy_params": {
            "vwap_window": 30,
            "min_rvol": 1.0,
            "max_position_bars": 50,
            "position_size_pct": 0.05,  # 5% position size
            "max_positions": 3,
            "min_deviation_pct": 0.2,
        },
        "backtest": {
            "initial_cash": 1000000  # Ensure position sizing clears board lot rounding
        },
    }


def run_pilot():
    """Run pilot test for April 1-5, 2024"""
    print("=" * 80)
    print("HMM_SIP + VWAP PILOT TEST - April 1-5, 2024")
    print("=" * 80)

    config = load_config()
    sip_enabled = config.get("sip_enabled", True)

    # Step 1: Test daily ticker selection
    print("\n" + "=" * 50)
    print("STEP 1: VALIDATING DAILY TICKER SELECTION")
    print("=" * 50)

    daily_universes = {}

    target_symbols = config.get("symbols")
    if target_symbols:
        print(f"\nLoading configured symbols: {target_symbols}")
        test_symbols = target_symbols
    else:
        # Discover symbols if not provided
        print("\nDiscovering symbols for testing...")
        stocks_path = os.path.join(config["gold_root"], "stocks")
        gold_symbols = []
        if os.path.exists(stocks_path):
            for item in os.listdir(stocks_path):
                symbol_path = os.path.join(stocks_path, item)
                if os.path.isdir(symbol_path) and item != "_errors":
                    gold_symbols.append(item)

        test_symbols = gold_symbols[:50] if len(gold_symbols) > 50 else gold_symbols
        print(
            f"  Found {len(gold_symbols):,} total Gold symbols, testing with {len(test_symbols):,} symbols"
        )

    # Load data for all dates upfront to avoid repeated loading
    full_bars_df = gold_loader.load_bars(
        root=config["gold_root"],
        family=config.get("data_family", "stocks"),
        symbols=test_symbols,
        dates=config["dates"],
        validate=False,
        sort=True,
    )
    print(f"✓ Loaded {len(full_bars_df):,} bars for {len(test_symbols):,} symbols across all dates")

    # Fix column mapping and data structure
    print("Standardizing data structure...")
    if "t" in full_bars_df.columns:
        # Convert milliseconds to nanoseconds and rename columns
        full_bars_df["ts"] = full_bars_df["t"] * 1_000_000  # ms to ns
        column_mapping = {
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
        full_bars_df.rename(columns=column_mapping, inplace=True)
        print("  ✓ Converted millisecond timestamps to nanoseconds")
        print("  ✓ Mapped price/volume columns to standard names")
    else:
        # Data already has correct column names, just convert ms to ns
        full_bars_df["ts"] = full_bars_df["ts"] * 1_000_000  # ms to ns
        print("  ✓ Converted millisecond timestamps to nanoseconds")

    # Ensure proper sorting by timestamp
    print("Sorting data...")
    full_bars_df = full_bars_df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    print("  ✓ Data sorted by [symbol, ts]")

    # Check for duplicates before processing
    print("Checking for duplicate (symbol, ts) pairs...")
    duplicates = full_bars_df.duplicated(subset=["symbol", "ts"])
    if duplicates.any():
        dup_count = duplicates.sum()
        print(f"  ⚠️ Found {dup_count:,} duplicate (symbol, ts) pairs")
        # Show sample duplicates
        dup_rows = full_bars_df[duplicates].head(10)
        print(f"  Sample duplicates:\n{dup_rows[['symbol', 'ts']].to_string()}")

        # Remove duplicates
        print("  Removing duplicates...")
        full_bars_df = full_bars_df.drop_duplicates(subset=["symbol", "ts"])
        print(f"  ✓ Removed duplicates, now have {len(full_bars_df):,} bars")
    else:
        print("  ✓ No duplicate (symbol, ts) pairs found")

    # Create date column for filtering
    full_bars_df["date_et"] = (
        pd.to_datetime(full_bars_df["ts"], unit="ns", utc=True)
        .dt.tz_convert("America/New_York")
        .dt.date
    )
    # Apply features once
    print("Applying features...")
    print("  (this processes all bars for all dates - may take time)")

    # Add progress tracking for features
    import time

    start_time = time.time()

    full_bars_df = core_basics.compute_all_core_features(full_bars_df)

    elapsed = time.time() - start_time
    print(f"✓ Features applied in {elapsed:.1f}s")

    # Check what dates are actually available in the data
    print("\nChecking available dates in loaded data...")
    if "date_et" in full_bars_df.columns:
        available_dates = sorted(full_bars_df["date_et"].unique())
        print(f"  Available dates: {available_dates[:10]}...")  # Show first 10 dates

        # Update config to use available dates if needed
        if not any(
            datetime.strptime(date, "%Y-%m-%d").date() in available_dates
            for date in config["dates"]
        ):
            print("  Updating config to use available dates...")
            config["dates"] = [
                d.strftime("%Y-%m-%d") for d in available_dates[:5]
            ]  # Use first 5 available dates
            print(f"  New test dates: {config['dates']}")

    if sip_enabled:
        for date in config["dates"]:
            print(f"\n{'=' * 20} Testing {date} {'=' * 20}")

            try:
                # Filter to just this date's data
                day_bars = full_bars_df.copy()
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
                day_bars = day_bars[day_bars["date_et"] == target_date]

                if day_bars.empty:
                    print(f"  No data available for {date}")
                    continue

                # Setup HMM_SIP selector
                sip_config = HMMSIPConfig(**config["sip"]["config"])
                sip_selector = HMMSIPUniverseSelector(sip_config)

                # Select universe for this day
                ref = {"target_date": date}
                universe_map = sip_selector.select(day_bars, ref)

                if universe_map:
                    # Get unique symbols for this day
                    all_symbols = set()
                    for symbols in universe_map.values():
                        all_symbols.update(symbols)

                    daily_universes[date] = sorted(all_symbols)
                    print(f"  ✓ Selected {len(all_symbols)} symbols: {all_symbols}")

                    # Show sample timestamps
                    sample_timestamps = list(universe_map.keys())[:3]
                    for ts in sample_timestamps:
                        dt = pd.to_datetime(ts, unit="ns", utc=True).tz_convert("America/New_York")
                        symbols = universe_map[ts]
                        print(f"    {dt}: {sorted(symbols)}")
                else:
                    print(f"  ✗ No universe generated for {date}")
                    daily_universes[date] = []

            except Exception as e:
                print(f"  ✗ Error for {date}: {e}")
                daily_universes[date] = []
    else:
        print("\nSIP gating disabled - using configured symbols for all dates.")
        for date in config["dates"]:
            daily_universes[date] = sorted(test_symbols)
            print(f"  {date}: {len(test_symbols)} symbols -> {sorted(test_symbols)}")

    # Step 2: Validate different tickers per day
    print("\n" + "=" * 50)
    print("STEP 2: VALIDATING DIFFERENT TICKERS PER DAY")
    print("=" * 50)

    print("\nDaily universe summary:")
    total_unique_symbols = set()
    for date, symbols in daily_universes.items():
        print(f"  {date}: {len(symbols)} symbols")
        total_unique_symbols.update(symbols)

    print(f"\nTotal unique symbols across all days: {len(total_unique_symbols)}")

    # Check if symbols differ between days
    symbol_sets = list(daily_universes.values())
    if len(symbol_sets) >= 2:
        overlaps = []
        for i in range(len(symbol_sets)):
            for j in range(i + 1, len(symbol_sets)):
                if symbol_sets[i] and symbol_sets[j]:
                    overlap = set(symbol_sets[i]).intersection(symbol_sets[j])
                    if overlap:
                        overlap_pct = (
                            len(overlap) / min(len(symbol_sets[i]), len(symbol_sets[j])) * 100
                        )
                    else:
                        overlap_pct = 0.0
                    overlaps.append(overlap_pct)
                    print(
                        f"  Day {i + 1} vs Day {j + 1}: {len(overlap)} overlapping symbols ({overlap_pct:.1f}%)"
                    )

        if overlaps:
            avg_overlap = sum(overlaps) / len(overlaps)
            print(f"  Average daily overlap: {avg_overlap:.1f}%")

            if avg_overlap < 80:
                print("  ✓ Good: Daily universes show variation (overlap < 80%)")
            else:
                print("  ⚠ Warning: High overlap between daily universes")
    selected_dates = {
        datetime.strptime(date, "%Y-%m-%d").date()
        for date, symbols in daily_universes.items()
        if symbols
    }
    if selected_dates:
        filtered_bars_df = full_bars_df[full_bars_df["date_et"].isin(selected_dates)].copy()
    else:
        filtered_bars_df = full_bars_df.copy()

    # Step 3: Test VWAP execution on shortlists
    print("\n" + "=" * 50)
    print("STEP 3: VALIDATING VWAP EXECUTION ON SHORTLISTS")
    print("=" * 50)

    try:
        # Use the already loaded data (full_bars_df from earlier)
        print(f"Using already loaded data: {len(filtered_bars_df):,} bars")

        # Final validation and sorting for backtest engine
        print("\nValidating data for backtest engine...")
        # Ensure data is properly sorted by timestamp globally (required by backtest engine)
        filtered_bars_df = filtered_bars_df.sort_values("ts").reset_index(drop=True)

        # Validate sorting
        is_sorted = filtered_bars_df["ts"].is_monotonic_increasing
        print(f"  ✓ Data is properly sorted by timestamp: {is_sorted}")

        # Validate required columns
        required_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in filtered_bars_df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")
        print("  ✓ All required columns present")

        # Setup backtest engine
        print("\nSetting up backtest engine...")
        backtest_config = BacktestConfig(initial_cash=config["backtest"]["initial_cash"])
        if sip_enabled:
            sip_config = {"sip_method": "hmm", "sip_config": config["sip"]["config"]}
        else:
            sip_config = {"sip_method": "none"}
        engine = BacktestEngine(backtest_config, sip_config)

        # Initialize SIP selector if enabled
        if sip_enabled:
            sip_config_full = HMMSIPConfig(**config["sip"]["config"])
            engine._sip_selector = HMMSIPUniverseSelector(sip_config_full)

        # Setup VWAP policy
        print("Setting up VWAP policy...")
        policy_params = config["policy_params"]
        policy = VwapRevertPolicy(**policy_params)
        engine.policy = policy

        print(f"  VWAP window: {policy.vwap_window}")
        print(f"  Min RVOL: {policy.min_rvol}")
        print(f"  Max positions: {policy.max_positions}")
        print(f"  Position size: {policy.position_size_pct:.1%}")

        # Step 4: Run backtest and validate trade generation
        print("\n" + "=" * 50)
        print("STEP 4: VALIDATING TRADE GENERATION")
        print("=" * 50)

        print("\nRunning backtest...")
        print("This will validate VWAP logic execution on daily HMM_SIP shortlists...")

        def vwap_strategy(engine, bar):
            policy.process_bar(bar)

        policy.engine = engine

        # Run backtest
        result = engine.run(filtered_bars_df, vwap_strategy)

        print("\n" + "=" * 60)
        print("BACKTEST RESULTS - TRADE GENERATION VALIDATION")
        print("=" * 60)

        print(f"Total trades: {result.total_trades}")
        print(f"Winning trades: {result.winning_trades}")
        print(f"Losing trades: {result.losing_trades}")

        if result.total_trades > 0:
            win_rate = result.win_rate
            print(f"Win rate: {win_rate:.1%}")
            print(f"Total return: {result.total_return:.1%}")
            print(f"Annualized return: {result.annualized_return:.1%}")
            print(f"Volatility: {result.volatility:.1%}")
            print(f"Sharpe ratio: {result.sharpe_ratio:.2f}")
            print(f"Max drawdown: {result.max_drawdown:.1%}")
            print(f"Profit factor: {result.profit_factor:.2f}")

            print("\nTrade statistics:")
            print(f"  Avg trade P&L: ${result.avg_trade_pnl:,.2f}")
            if result.avg_win > 0:
                print(f"  Avg win: ${result.avg_win:,.2f}")
            if result.avg_loss < 0:
                print(f"  Avg loss: ${result.avg_loss:,.2f}")
            print(f"  Largest win: ${result.largest_win:,.2f}")
            print(f"  Largest loss: ${result.largest_loss:,.2f}")

            # Validate trade generation
            print("\n✅ TRADE GENERATION VALIDATION:")
            print(f"  ✓ System generated {result.total_trades} trades")
            print(f"  ✓ Trades across {len(daily_universes)} trading days")
            print(f"  ✓ Average {result.total_trades / len(daily_universes):.1f} trades per day")

            if win_rate > 0:
                print(f"  ✓ Win rate: {win_rate:.1%}")
            else:
                print(f"  ⚠ Win rate: {win_rate:.1%}")

        else:
            print("❌ NO TRADES GENERATED")
            print("This indicates an issue with either:")
            print("  - Universe selection (no symbols meeting criteria)")
            print("  - VWAP signal generation (no entry conditions)")
            print("  - Risk filters (all trades filtered out)")

    except Exception as e:
        print(f"\n❌ Backtest failed: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)
    print("PILOT TEST COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    run_pilot()
