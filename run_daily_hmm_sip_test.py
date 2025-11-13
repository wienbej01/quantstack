#!/usr/bin/env python3
"""Run VWAP strategy with daily HMM_SIP for January 2024."""

import sys
from datetime import datetime
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
sys.path.insert(0, str(project_root / "qx-risk" / "src"))

try:
    from qx_backtest.engine import BacktestConfig, BacktestEngine
    from qx_backtest.order import OrderFactory, OrderSide, OrderType
    from qx_backtest.policies.vwap_revert import VwapRevertPolicy
    from qx_core.validators import validate_bars_dataframe
    from qx_data.gold_loader import load_bars
    from qx_features.core_basics import compute_all_core_features
    from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure all qx modules are available in the Python path")
    sys.exit(1)


def load_config(config_path: Path) -> dict:
    """Load strategy configuration from YAML file."""
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config


def run_vwap_backtest_with_daily_hmm_sip():
    """Run VWAP strategy with daily HMM_SIP for January 2024."""
    print("=" * 60)
    print("VWAP Strategy with Daily HMM_SIP - January 2024")
    print("=" * 60)

    # Load configuration
    config_path = Path(__file__).parent / "experiments" / "vwap_revert" / "strategy.yaml"
    config = load_config(config_path)

    print(f"Loaded configuration from: {config_path}")
    print(f"Date range: {config['dates'][0]} to {config['dates'][-1]}")
    print(f"Symbols: {len(config['symbols'])} symbols")
    print(f"SIP mode: {config['sip']['mode']}")
    print(f"SIP method: {config['sip']['sip_method']}")
    print(f"Top K: {config['sip']['top_k']}")

    # Load and prepare data using gold_loader function
    all_bars = []
    for date_str in config["dates"]:
        print(f"\nLoading data for {date_str}...")
        try:
            bars = load_bars(
                root=config["gold_root"],
                family=config["family"],
                symbols=config["symbols"],
                dates=[date_str],
            )
            if not bars.empty:
                print(f"  Loaded {len(bars)} bars for {date_str}")
                all_bars.append(bars)
            else:
                print(f"  No data available for {date_str}")
        except Exception as e:
            print(f"  Error loading data for {date_str}: {e}")
            continue

    if not all_bars:
        print("ERROR: No data loaded!")
        return None

    # Combine all data
    df = pd.concat(all_bars, ignore_index=True)
    print(f"\nTotal bars loaded: {len(df):,}")

    # Convert timestamps properly for display
    if df["ts"].max() < 1e12:  # Likely seconds
        df["ts"] = df["ts"] * 1e9  # Convert to nanoseconds

    print(
        f"Date range: {pd.to_datetime(df['ts'], unit='ns').min()} to {pd.to_datetime(df['ts'], unit='ns').max()}"
    )
    print(f"Symbols in data: {sorted(df['symbol'].unique())}")

    # Remove duplicates (keep last)
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["symbol", "ts"], keep="last")
    after_dedup = len(df)
    if before_dedup != after_dedup:
        print(f"Removed {before_dedup - after_dedup} duplicate rows")

    # Validate data
    validate_bars_dataframe(df)

    # Apply features
    print("\nApplying features...")

    # Apply core features using function
    feature_params = config["features"][0]["params"]
    feature_df = compute_all_core_features(
        df,
        vwap_window=feature_params["vwap_window_m"],
        rvol_window=feature_params["rel_vol_window_m"],
        atr_window=feature_params["atr_window"],
    )

    print(f"Applied features, shape: {feature_df.shape}")
    print(f"Feature columns: {[col for col in feature_df.columns if col.startswith('f__')]}")

    # Setup SIP selector
    print("\nSetting up HMM SIP selector...")
    sip_config = HMMSIPConfig(
        mode=config["sip"]["mode"],
        score_floor=config["sip"]["score_floor"],
        top_k=config["sip"]["top_k"],
        enable_gold_fallback=config["sip"].get("enable_gold_fallback", True),
    )

    sip_selector = HMMSIPUniverseSelector(sip_config)

    # Select universe using daily HMM SIP
    print("Running daily HMM SIP selection...")
    ref_context = {"target_date": config["dates"][0]}  # Use first date as reference

    # Apply SIP filtering
    if config.get("sip_filter", False):
        universe_map = sip_selector.select(feature_df, ref_context)
        print(f"HMM SIP selected universe for {len(universe_map)} timestamps")

        # Calculate average universe size
        avg_universe_size = (
            sum(len(symbols) for symbols in universe_map.values()) / len(universe_map)
            if universe_map
            else 0
        )
        print(f"Average universe size: {avg_universe_size:.1f} symbols per timestamp")

        # Show universe for first timestamp as example
        if universe_map:
            first_ts = min(universe_map.keys())
            first_universe = sorted(universe_map[first_ts])
            print(
                f"Example universe at timestamp {pd.to_datetime(first_ts, unit='ns')}: {first_universe}"
            )
    else:
        print("SIP filtering disabled")
        universe_map = None

    # Create backtest configuration
    backtest_config = BacktestConfig(
        initial_cash=config["backtest"]["initial_equity"], show_progress=True
    )

    # Create engine with SIP configuration
    sip_config_dict = {
        "sip_method": config["sip"]["sip_method"],
        "sip_config": {
            "mode": config["sip"]["mode"],
            "top_k": config["sip"]["top_k"],
            "score_floor": config["sip"]["score_floor"],
        },
    }

    engine = BacktestEngine(backtest_config, sip_config_dict)

    # Attach SIP selector to engine
    engine._sip_selector = sip_selector

    # Create VWAP revert policy
    policy_params = config["policy_params"]
    policy = VwapRevertPolicy(
        vwap_window=policy_params["vwap_window_m"],
        min_rvol=policy_params["rvol_min"],
        max_position_bars=policy_params["max_position_bars"],
    )

    # Strategy function
    def vwap_strategy(engine, bar):
        """VWAP reversion strategy with daily HMM SIP universe."""
        # The policy will handle all trading logic
        policy.process_bar(engine, bar)

    print("\nRunning backtest...")
    print(f"Initial equity: ${backtest_config.initial_cash:,.2f}")

    # Run backtest
    result = engine.run(feature_df, vwap_strategy)

    return result, config


def analyze_results(result, config):
    """Analyze and display backtest results."""
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    # Basic stats
    print("Strategy: VWAP Reversion with Daily HMM_SIP")
    print(f"Date range: {result.start_date} to {result.end_date}")
    print(f"Initial equity: ${config['backtest']['initial_equity']:,.2f}")
    print(f"Final equity: ${result.equity_curve['total_equity'].iloc[-1]:,.2f}")

    # Performance metrics
    print("\nPerformance Metrics:")
    print(f"  Total Return: {result.total_return:.2%}")
    print(f"  Annualized Return: {result.annualized_return:.2%}")
    print(f"  Volatility: {result.volatility:.2%}")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"  Max Drawdown: {result.max_drawdown:.2%}")
    print(f"  Max Drawdown Duration: {result.max_drawdown_duration} bars")

    # Trading statistics
    print("\nTrading Statistics:")
    print(f"  Total Trades: {result.total_trades}")
    print(f"  Winning Trades: {result.winning_trades}")
    print(f"  Losing Trades: {result.losing_trades}")
    print(f"  Win Rate: {result.win_rate:.2%}")
    print(f"  Profit Factor: {result.profit_factor:.2f}")
    print(f"  Average Trade P&L: ${result.avg_trade_pnl:.2f}")
    if result.avg_win > 0:
        print(f"  Average Win: ${result.avg_win:.2f}")
    if result.avg_loss < 0:
        print(f"  Average Loss: ${result.avg_loss:.2f}")
    print(f"  Largest Win: ${result.largest_win:.2f}")
    print(f"  Largest Loss: ${result.largest_loss:.2f}")

    # Execution statistics
    print("\nExecution Statistics:")
    print(f"  Total Commissions: ${result.total_commissions:.2f}")
    print(f"  Total Slippage: ${result.total_slippage:.2f}")
    print(f"  Fill Rate: {result.fill_rate:.2%}")

    # Daily analysis
    if not result.equity_curve.empty:
        result.equity_curve["date"] = pd.to_datetime(
            result.equity_curve["timestamp"], unit="ns"
        ).dt.date

        daily_stats = (
            result.equity_curve.groupby("date")
            .agg(
                {
                    "total_equity": ["first", "last"],
                    "total_pnl": "sum",
                    "position_count": "max",
                }
            )
            .round(2)
        )

        daily_stats.columns = [
            "start_equity",
            "end_equity",
            "daily_pnl",
            "max_positions",
        ]
        daily_stats["daily_return"] = (daily_stats["end_equity"] / daily_stats["start_equity"]) - 1

        print("\nDaily Performance (first 10 days):")
        print(daily_stats.head(10).to_string())

        if len(daily_stats) > 10:
            print(f"... and {len(daily_stats) - 10} more days")

    # Trade analysis
    if result.trades_history:
        trades_df = pd.DataFrame(result.trades_history)
        trades_df["date"] = pd.to_datetime(trades_df["timestamp"], unit="ns").dt.date

        print("\nTrade Analysis by Symbol:")
        symbol_stats = (
            trades_df.groupby("symbol")
            .agg({"quantity": "sum", "total_cost": "sum", "commission": "sum"})
            .round(2)
        )
        symbol_stats["trade_count"] = trades_df.groupby("symbol").size()
        print(symbol_stats.to_string())

    return result


def main():
    """Main function to run the daily HMM SIP test."""
    print(f"Starting test at: {datetime.now()}")
    print(f"Working directory: {Path.cwd()}")

    try:
        # Run backtest
        result = run_vwap_backtest_with_daily_hmm_sip()

        if result is None:
            print("ERROR: Backtest failed to run")
            return 1

        backtest_result, config = result

        # Analyze results
        analyze_results(backtest_result, config)

        print(f"\nTest completed successfully at: {datetime.now()}")
        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
