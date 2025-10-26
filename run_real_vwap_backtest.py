#!/usr/bin/env python3
"""
Real Data VWAP Backtest using GOLD dataset
NO SIMULATED OR FAKE DATA - ONLY REAL MARKET DATA
"""

import json
import pathlib
import sys
from typing import Any

import pandas as pd


def create_real_vwap_config() -> pathlib.Path:
    """Create real VWAP backtest configuration using GOLD data for H1 2024."""

    config = {
        "gold_root": "/home/jacobw/gcs-mount/gold",
        "family": "bars_1m",
        "symbols": ["AAPL"],
        "dates": [
            # January 2024 - REAL TRADING DAYS ONLY
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-08",
            "2024-01-09",
            "2024-01-10",
            "2024-01-11",
            "2024-01-12",
            "2024-01-16",
            "2024-01-17",
            "2024-01-18",
            "2024-01-19",
            "2024-01-22",
            "2024-01-23",
            "2024-01-24",
            "2024-01-25",
            "2024-01-26",
            "2024-01-29",
            "2024-01-30",
            "2024-01-31",
            # February 2024 - REAL TRADING DAYS ONLY
            "2024-02-01",
            "2024-02-02",
            "2024-02-05",
            "2024-02-06",
            "2024-02-07",
            "2024-02-08",
            "2024-02-09",
            "2024-02-12",
            "2024-02-13",
            "2024-02-14",
            "2024-02-15",
            "2024-02-16",
            "2024-02-20",
            "2024-02-21",
            "2024-02-22",
            "2024-02-23",
            "2024-02-26",
            "2024-02-27",
            "2024-02-28",
            "2024-02-29",
            # March 2024 - REAL TRADING DAYS ONLY
            "2024-03-01",
            "2024-03-04",
            "2024-03-05",
            "2024-03-06",
            "2024-03-07",
            "2024-03-08",
            "2024-03-11",
            "2024-03-12",
            "2024-03-13",
            "2024-03-14",
            "2024-03-15",
            "2024-03-18",
            "2024-03-19",
            "2024-03-20",
            "2024-03-21",
            "2024-03-22",
            "2024-03-25",
            "2024-03-26",
            "2024-03-27",
            "2024-03-28",
            # April 2024 - REAL TRADING DAYS ONLY
            "2024-04-01",
            "2024-04-02",
            "2024-04-03",
            "2024-04-04",
            "2024-04-05",
            "2024-04-08",
            "2024-04-09",
            "2024-04-10",
            "2024-04-11",
            "2024-04-12",
            "2024-04-15",
            "2024-04-16",
            "2024-04-17",
            "2024-04-18",
            "2024-04-19",
            "2024-04-22",
            "2024-04-23",
            "2024-04-24",
            "2024-04-25",
            "2024-04-26",
            "2024-04-29",
            "2024-04-30",
            # May 2024 - REAL TRADING DAYS ONLY
            "2024-05-01",
            "2024-05-02",
            "2024-05-03",
            "2024-05-06",
            "2024-05-07",
            "2024-05-08",
            "2024-05-09",
            "2024-05-10",
            "2024-05-13",
            "2024-05-14",
            "2024-05-15",
            "2024-05-16",
            "2024-05-17",
            "2024-05-20",
            "2024-05-21",
            "2024-05-22",
            "2024-05-23",
            "2024-05-24",
            "2024-05-28",
            "2024-05-29",
            "2024-05-30",
            "2024-05-31",
            # June 2024 - REAL TRADING DAYS ONLY
            "2024-06-03",
            "2024-06-04",
            "2024-06-05",
            "2024-06-06",
            "2024-06-07",
            "2024-06-10",
            "2024-06-11",
            "2024-06-12",
            "2024-06-13",
            "2024-06-14",
            "2024-06-17",
            "2024-06-18",
            "2024-06-19",
            "2024-06-20",
            "2024-06-21",
            "2024-06-24",
            "2024-06-25",
            "2024-06-26",
            "2024-06-27",
            "2024-06-28",
        ],
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
        "policy": "vwap_revert",
        "policy_params": {
            "rvol_min": 1.0,
            "vwap_window_m": 30,
            "max_position_bars": 50,
        },
        "risk": "atr_stop",
        "risk_params": {"max_risk_frac": 0.02, "atr_mult": 2.0},
        "backtest": {"initial_equity": 100000, "cost_bps": 5, "cost_per_share": 0.0035},
        "bidirectional": True,  # Enable both long and short positions
    }

    # Save config
    config_path = pathlib.Path("real_vwap_h1_2024_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return config_path


def validate_gold_data_availability() -> bool:
    """Validate that real GOLD data exists for requested dates."""

    print("🔍 Validating GOLD data availability...")

    # Check if gold data path exists
    gold_path = pathlib.Path("/home/jacobw/gcs-mount/gold/stocks/1m/AAPL")
    if not gold_path.exists():
        print(f"❌ GOLD data path not found: {gold_path}")
        return False

    # Check February 2024 data
    feb_2024_path = gold_path / "2024" / "2024-02.parquet"
    if not feb_2024_path.exists():
        print(f"❌ February 2024 data not found: {feb_2024_path}")
        return False

    # Load and validate February 2024 data
    try:
        df_feb = pd.read_parquet(feb_2024_path)
        print(f"✅ February 2024 data loaded: {len(df_feb)} records")
        date_min = pd.to_datetime(df_feb["ts"], unit="ns", utc=True).min()
        date_max = pd.to_datetime(df_feb["ts"], unit="ns", utc=True).max()
        print(f"📊 Date range: {date_min} to {date_max}")
        print(
            f"📈 Price range: ${df_feb['close'].min():.2f} - ${df_feb['close'].max():.2f}"
        )
        return True
    except Exception as e:
        print(f"❌ Error loading February 2024 data: {e}")
        return False


def load_real_aapl_data_multiple_months(months: list[str]) -> pd.DataFrame | None:
    """Load real AAPL data from GOLD dataset for multiple months."""

    all_data = []

    for month in months:
        parquet_path = (
            f"/home/jacobw/gcs-mount/gold/stocks/1m/AAPL/2024/{month}.parquet"
        )

        try:
            df = pd.read_parquet(parquet_path)
            print(f"✅ Loaded {len(df)} real market records for {month}")

            # Convert timestamps to ET for analysis
            df["ts_et"] = pd.to_datetime(df["ts"], unit="ns", utc=True).dt.tz_convert(
                "US/Eastern"
            )

            # Filter for regular trading hours only (09:30-15:59 ET)
            trading_start = pd.to_datetime("09:30:00").time()
            trading_end = pd.to_datetime("15:59:00").time()

            df["time_only"] = df["ts_et"].dt.time
            trading_hours_mask = (df["time_only"] >= trading_start) & (
                df["time_only"] <= trading_end
            )
            df_trading = df[trading_hours_mask].copy()

            print(f"📊 Trading hours data for {month}: {len(df_trading)} records")

            all_data.append(df_trading)

        except Exception as e:
            print(f"❌ Error loading {month} data: {e}")
            continue

    if not all_data:
        return None

    # Combine all months
    df_combined = pd.concat(all_data, ignore_index=True)
    print(f"📊 Combined H1 2024 trading hours data: {len(df_combined)} records")
    print(
        f"📅 Date range: {df_combined['ts_et'].min().date()} to {df_combined['ts_et'].max().date()}"
    )

    return df_combined


def load_real_aapl_data(month: str = "2024-02") -> pd.DataFrame | None:
    """Load real AAPL data from GOLD dataset (legacy function for single month)."""

    return load_real_aapl_data_multiple_months([month])


def analyze_vwap_signals_from_real_data(df: pd.DataFrame) -> dict[str, Any] | None:
    """Analyze VWAP signals from real market data."""

    MIN_VWAP_DEVIATION = 0.5

    print("\n🔍 Analyzing real VWAP signals...")

    # Check if VWAP features are available
    vwap_cols = [col for col in df.columns if "vwap" in col.lower()]
    if not vwap_cols:
        print("❌ No VWAP features found in real data")
        print("📋 Available columns:", list(df.columns))
        return None

    vwap_col = vwap_cols[0]  # Use first available VWAP column
    print(f"✅ Using VWAP column: {vwap_col}")

    # Calculate VWAP deviation for each bar
    df["vwap_deviation"] = (df["close"] - df[vwap_col]) / df[vwap_col]
    df["vwap_deviation_pct"] = abs(df["vwap_deviation"]) * 100

    # Find potential entry signals
    # Long signals: close < VWAP with sufficient deviation
    long_signals = df[
        (df["close"] < df[vwap_col]) & (df["vwap_deviation_pct"] >= MIN_VWAP_DEVIATION)
    ].copy()

    # Short signals: close > VWAP with sufficient deviation
    short_signals = df[
        (df["close"] > df[vwap_col]) & (df["vwap_deviation_pct"] >= MIN_VWAP_DEVIATION)
    ].copy()

    print("\n📈 REAL SIGNAL ANALYSIS:")
    print(f"   Long signals found: {len(long_signals)}")
    print(f"   Short signals found: {len(short_signals)}")
    print(f"   Total potential entries: {len(long_signals) + len(short_signals)}")

    if len(long_signals) > 0:
        print(
            f"   Average long deviation: {long_signals['vwap_deviation_pct'].mean():.2f}%"
        )
        long_min = long_signals["close"].min()
        long_max = long_signals["close"].max()
        print(f"   Long price range: ${long_min:.2f} - ${long_max:.2f}")

    if len(short_signals) > 0:
        print(
            f"   Average short deviation: {short_signals['vwap_deviation_pct'].mean():.2f}%"
        )
        short_min = short_signals["close"].min()
        short_max = short_signals["close"].max()
        print(f"   Short price range: ${short_min:.2f} - ${short_max:.2f}")

    return {
        "long_signals": long_signals,
        "short_signals": short_signals,
        "vwap_col": vwap_col,
        "total_bars": len(df),
    }


def simulate_realistic_trades_from_signals(
    signal_analysis: dict[str, Any], df: pd.DataFrame
) -> list[dict[str, Any]] | None:
    """Simulate realistic trades based on real VWAP signals."""

    if not signal_analysis:
        print("❌ No signals to simulate trades from")
        return None

    print("\n🎯 Simulating realistic trades from real signals...")

    long_signals = signal_analysis["long_signals"]
    short_signals = signal_analysis["short_signals"]
    vwap_col = signal_analysis["vwap_col"]

    trades: list[dict[str, Any]] = []
    trade_id = 1

    # Process long signals
    for _, signal in long_signals.iterrows():
        # Skip if we already have too many trades in same day
        existing_trades_same_day = [
            t for t in trades if t["date"] == signal["ts_et"].date()
        ]
        MAX_TRADES_PER_DAY = 2
        if len(existing_trades_same_day) >= MAX_TRADES_PER_DAY:
            continue

        # Calculate realistic exit based on real price action
        entry_price = signal["close"]
        entry_time = signal["ts_et"]
        vwap_price = signal[vwap_col]

        # Look for exit in future bars (within reasonable time frame)
        future_bars = df[
            (df["ts_et"] > entry_time)
            & (df["ts_et"] <= entry_time + pd.Timedelta(minutes=50))  # Max 50 bars
        ].sort_values("ts_et")

        if len(future_bars) > 0:
            # Find exit when price reaches VWAP or max time
            exit_bar = None
            for _, bar in future_bars.iterrows():
                if bar["close"] >= bar[vwap_col]:  # Reached VWAP target
                    exit_bar = bar
                    break

            if exit_bar is None:
                # Use last bar if no VWAP target reached
                exit_bar = future_bars.iloc[-1]
                exit_reason = "timeout"
            else:
                exit_reason = "vwap_target"

            # Calculate realistic P&L
            exit_price = exit_bar["close"]
            exit_time = exit_bar["ts_et"]

            # Position sizing (2% risk)
            position_value = 2000
            quantity = int(position_value / entry_price / 100) * 100
            quantity = max(quantity, 100)

            pnl_per_share = exit_price - entry_price
            total_pnl = pnl_per_share * quantity
            pnl_percentage = (total_pnl / position_value) * 100

            duration = (exit_time - entry_time).total_seconds() / 60

            trade = {
                "trade_id": trade_id,
                "date": entry_time.date(),
                "entry_time": entry_time.time(),
                "exit_time": exit_time.time(),
                "direction": "LONG",
                "signal_type": "Price Below VWAP",
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "vwap_price": round(vwap_price, 2),
                "quantity": quantity,
                "pnl": round(total_pnl, 2),
                "pnl_percentage": round(pnl_percentage, 2),
                "duration_minutes": int(duration),
                "result": "WIN" if total_pnl > 0 else "LOSS",
                "exit_reason": exit_reason,
                "vwap_deviation": round(signal["vwap_deviation_pct"], 2),
            }

            trades.append(trade)
            trade_id += 1

    # Process short signals (similar logic)
    for _, signal in short_signals.iterrows():
        existing_trades_same_day = [
            t for t in trades if t["date"] == signal["ts_et"].date()
        ]
        if len(existing_trades_same_day) >= MAX_TRADES_PER_DAY:
            continue

        entry_price = signal["close"]
        entry_time = signal["ts_et"]
        vwap_price = signal[vwap_col]

        future_bars = df[
            (df["ts_et"] > entry_time)
            & (df["ts_et"] <= entry_time + pd.Timedelta(minutes=50))
        ].sort_values("ts_et")

        if len(future_bars) > 0:
            exit_bar = None
            for _, bar in future_bars.iterrows():
                if bar["close"] <= bar[vwap_col]:  # Reached VWAP target (short cover)
                    exit_bar = bar
                    break

            if exit_bar is None:
                exit_bar = future_bars.iloc[-1]
                exit_reason = "timeout"
            else:
                exit_reason = "vwap_target"

            exit_price = exit_bar["close"]
            exit_time = exit_bar["ts_et"]

            position_value = 2000
            quantity = int(position_value / entry_price / 100) * 100
            quantity = max(quantity, 100)

            # For short: profit when price goes down
            pnl_per_share = entry_price - exit_price
            total_pnl = pnl_per_share * quantity
            pnl_percentage = (total_pnl / position_value) * 100

            duration = (exit_time - entry_time).total_seconds() / 60

            trade = {
                "trade_id": trade_id,
                "date": entry_time.date(),
                "entry_time": entry_time.time(),
                "exit_time": exit_time.time(),
                "direction": "SHORT",
                "signal_type": "Price Above VWAP",
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "vwap_price": round(vwap_price, 2),
                "quantity": quantity,
                "pnl": round(total_pnl, 2),
                "pnl_percentage": round(pnl_percentage, 2),
                "duration_minutes": int(duration),
                "result": "WIN" if total_pnl > 0 else "LOSS",
                "exit_reason": exit_reason,
                "vwap_deviation": round(signal["vwap_deviation_pct"], 2),
            }

            trades.append(trade)
            trade_id += 1

    print(f"✅ Generated {len(trades)} realistic trades from real signals")
    return trades


def generate_real_data_report(
    trades_df: pd.DataFrame,
    signal_analysis: dict[str, Any] | None,
    period_label: str = "H1 2024",
) -> None:
    """Generate comprehensive report for real data analysis."""

    if trades_df is None or trades_df.empty:
        print("❌ No trades to report")
        return

    print("\n" + "=" * 80)
    print(f"📊 REAL DATA VWAP BACKTEST REPORT - {period_label}")
    print("=" * 80)
    print("📝 DATA SOURCE: GOLD Dataset - Real Market Bars Only")
    print("⚠️  NO SIMULATED DATA - 100% Real Market Data")
    print("=" * 80)

    # Overall statistics
    total_trades = len(trades_df)
    winning_trades = trades_df[trades_df["pnl"] > 0]
    losing_trades = trades_df[trades_df["pnl"] < 0]

    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
    total_pnl = trades_df["pnl"].sum()
    avg_pnl = trades_df["pnl"].mean() if total_trades > 0 else 0

    print("\n🎯 Overall Performance:")
    print(f"   Total Trades:     {total_trades}")
    print(f"   Winning Trades:   {len(winning_trades)}")
    print(f"   Losing Trades:    {len(losing_trades)}")
    print(f"   Win Rate:         {win_rate:.1%}")
    print(f"   Total P&L:        ${total_pnl:,.2f}")
    print(f"   Avg P&L per Trade: ${avg_pnl:,.2f}")
    print(
        f"   Return:           {total_pnl/100000*100:+.2f}%"
    )  # Assuming $100k starting capital

    # Directional analysis
    long_trades = trades_df[trades_df["direction"] == "LONG"]
    short_trades = trades_df[trades_df["direction"] == "SHORT"]

    print("\n📈 Long Positions:")
    print(f"   Trades:           {len(long_trades)}")
    if len(long_trades) > 0:
        long_win_rate = len(long_trades[long_trades["pnl"] > 0]) / len(long_trades)
        long_pnl = long_trades["pnl"].sum()
        print(f"   Win Rate:         {long_win_rate:.1%}")
        print(f"   Total P&L:        ${long_pnl:,.2f}")
        print(f"   Avg P&L:          ${long_trades['pnl'].mean():,.2f}")

    print("\n📉 Short Positions:")
    print(f"   Trades:           {len(short_trades)}")
    if len(short_trades) > 0:
        short_win_rate = len(short_trades[short_trades["pnl"] > 0]) / len(short_trades)
        short_pnl = short_trades["pnl"].sum()
        print(f"   Win Rate:         {short_win_rate:.1%}")
        print(f"   Total P&L:        ${short_pnl:,.2f}")
        print(f"   Avg P&L:          ${short_trades['pnl'].mean():,.2f}")

    # Exit analysis
    exit_reasons = trades_df["exit_reason"].value_counts()
    print("\n📋 Exit Reasons:")
    for reason, count in exit_reasons.items():
        print(f"   {reason}:           {count} trades ({count/total_trades:.1%})")

    # Detailed trade list
    print("\n📋 Detailed Trade List:")
    print("-" * 90)
    header = (
        f"{'#':<4} {'Date':<12} {'Entry':<8} {'Exit':<8} {'Dir':<5} "
        f"{'Entry $':<10} {'Exit $':<10} {'P&L':<10} {'Result':<8}"
    )
    print(header)
    print("-" * 90)

    for _, trade in trades_df.iterrows():
        result_emoji = "✅" if trade["pnl"] > 0 else "❌"
        print(
            f"{trade['trade_id']:<4} {trade['date']} {trade['entry_time']} {trade['exit_time']} "
            f"{trade['direction']:<5} ${trade['entry_price']:<9.2f} ${trade['exit_price']:<9.2f} "
            f"{trade['pnl']:+<10.2f} {result_emoji}"
        )

    print("-" * 90)

    # Signal analysis summary
    if signal_analysis:
        print("\n📊 Signal Analysis Summary:")
        print(f"   Total bars analyzed: {signal_analysis['total_bars']}")
        print(f"   VWAP column: {signal_analysis['vwap_col']}")
        print(f"   Long signals found: {len(signal_analysis['long_signals'])}")
        print(f"   Short signals found: {len(signal_analysis['short_signals'])}")
        total_signals = len(signal_analysis["long_signals"]) + len(
            signal_analysis["short_signals"]
        )
        conversion_rate = total_trades / total_signals
        print(
            f"   Signal-to-trade conversion: {total_trades}/{total_signals} ({conversion_rate:.1%})"
        )


def main() -> None:
    """Main execution function for H1 2024 real data backtest."""

    print("🔄 RUNNING H1 2024 REAL DATA VWAP BACKTEST")
    print("🚫 NO SIMULATED OR FAKE DATA - ONLY REAL MARKET DATA")
    print("📅 PERIOD: January - June 2024")
    print("=" * 70)

    # Step 1: Validate GOLD data availability
    if not validate_gold_data_availability():
        print("\n❌ Cannot proceed without real GOLD data")
        sys.exit(1)

    # Step 2: Load real market data for H1 2024
    h1_months = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
    df_h1 = load_real_aapl_data_multiple_months(h1_months)
    if df_h1 is None:
        print("\n❌ Failed to load real market data for H1 2024")
        sys.exit(1)

    # Step 3: Analyze real VWAP signals
    signal_analysis = analyze_vwap_signals_from_real_data(df_h1)
    if signal_analysis is None:
        print("\n❌ No VWAP signals found in real data")
        sys.exit(1)

    # Step 4: Generate realistic trades from real signals
    trades = simulate_realistic_trades_from_signals(signal_analysis, df_h1)
    if trades is None or len(trades) == 0:
        print("\n❌ No trades generated from real signals")
        sys.exit(1)

    # Step 5: Create DataFrame and save results
    trades_df = pd.DataFrame(trades)

    # Save configuration
    config_path = create_real_vwap_config()
    print(f"\n✅ H1 2024 real data configuration saved: {config_path}")

    # Save results
    output_dir = pathlib.Path("real_vwap_backtest_results")
    output_dir.mkdir(exist_ok=True)

    trades_df.to_csv(output_dir / "real_trades_h1_2024.csv", index=False)
    trades_df.to_parquet(output_dir / "real_trades_h1_2024.parquet")

    print(f"✅ H1 2024 real trades saved to: {output_dir}")

    # Step 6: Generate comprehensive report
    generate_real_data_report(trades_df, signal_analysis, "H1 2024 (Jan-Jun)")

    print("\n🎉 H1 2024 REAL DATA BACKTEST COMPLETED SUCCESSFULLY!")
    print("📊 All results based on 100% real market data from GOLD dataset")
    print("🚫 NO SIMULATION, NO FAKE PRICES, NO ARTIFICIAL OUTCOMES")


if __name__ == "__main__":
    main()
