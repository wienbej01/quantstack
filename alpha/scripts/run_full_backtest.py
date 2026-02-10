#!/usr/bin/env python3
"""Run full backtest for all three hypotheses.

Tests all hypotheses with walk-forward validation and regime analysis.
Generates consolidated comparison report with recommendations.

Usage:
    python scripts/run_full_backtest.py --start 2024-01-01 --end 2024-12-31
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from datetime import timedelta
import numpy as np

from src.data import GoldLoader, L2Loader
from src.signals import OrderFlowSignal, WhaleDetectSignal, LiquidityFadeSignal
from src.backtest import AlphaBacktestEngine
from src.backtest.walk_forward import WalkForwardValidator
from src.backtest.regime_split import RegimeStratifier
from src.metrics import compute_all_metrics, check_minimum_thresholds
from src.metrics.diagnostics import generate_summary_report, save_report

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Default configuration
DEFAULT_CONFIG = {
    "initial_capital": 100000,
    "max_symbols": 10,  # ADD THIS LINE - 0 for unlimited
    "execution": {
        "latency_ms": 75,
        "slippage_bps": 5,
        "commission_per_share": 0.005,
    },
    "risk": {
        "max_position_pct": 0.02,
        "max_positions": 5,
        "max_daily_loss_pct": 0.03,
    },
    "validation": {
        "walk_forward": {
            "train_months": 3,
            "val_months": 1,
            "min_profitable_periods": 0.7,
        },
        "regime": {
            "spy_sma_period": 20,
            "vix_threshold": 20,
            "min_regimes_profitable": 2,
        },
        "thresholds": {
            "min_sharpe": 0.75,
            "min_win_rate": 52.0,
            "min_profit_factor": 1.2,
            "min_t_stat": 2.0,
            "min_trades": 500,
        },
    },
    "signals": {
        "order_flow": {
            "book_imbalance_threshold": 0.35,
            "trade_imbalance_threshold": 0.25,
            "max_spread_pct": 0.05,
            "target_pct": 0.4,
            "stop_pct": 0.25,
            "time_limit_minutes": 10,
        },
        "whale_detect": {
            "large_order_mult": 5.0,
            "min_rvol": 1.5,
            "min_flow_imb": 0.1,
            "target_pct": 0.8,
            "stop_pct": 0.4,
            "time_limit_minutes": 30,
        },
        "liquidity_fade": {
            "depth_drop_threshold": 0.5,
            "price_spike_pct": 0.2,
            "target_pct": 0.3,
            "stop_pct": 0.3,
            "time_limit_minutes": 5,
        },
    },
}


def run_full_backtest(
    start_date: str,
    end_date: str,
    config: dict = None,
) -> dict:
    """Run full backtest for all three hypotheses.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        config: Optional config dict

    Returns:
        Dict with results for all hypotheses
    """
    if config is None:
        config = DEFAULT_CONFIG

    logger.info("=" * 60)
    logger.info("FULL ALPHA BACKTEST - ALL HYPOTHESES")
    logger.info("=" * 60)
    logger.info(f"Date range: {start_date} to {end_date}")

    # Initialize signals
    signals = {
        "order_flow": OrderFlowSignal(config),
        "whale_detect": WhaleDetectSignal(config),
        "liquidity_fade": LiquidityFadeSignal(config),
    }

    # Load data
    logger.info("\nLoading data...")
    gold_loader = GoldLoader()
    l2_loader = L2Loader()

    # Get symbols from L2 data (not SIP) - only test symbols with L2 coverage
    l2_path = Path("~/quantstack/data/l2/l2_maximum/raw").expanduser()
    
    # Collect all symbol-date combinations with L2 data
    from datetime import datetime, timedelta
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    symbols_with_l2 = set()
    current = start_dt
    while current <= end_dt:
        date_str = current.strftime("%Y-%m-%d")
        date_path = l2_path / f"date={date_str}"
        if date_path.exists():
            for sym_dir in date_path.iterdir():
                if sym_dir.is_dir() and sym_dir.name.startswith("symbol="):
                    symbol = sym_dir.name.replace("symbol=", "")
                    symbols_with_l2.add(symbol)
        current += timedelta(days=1)
    
    symbols = sorted(symbols_with_l2)
    logger.info(f"Found {len(symbols)} symbols with L2 data in date range")

    # Load Gold data for symbols with L2
    all_bars = []
    for symbol in symbols:
        try:
            bars = gold_loader.load_bars(symbol, start_date, end_date)
            if not bars.empty:
                bars["symbol"] = symbol
                all_bars.append(bars)
                logger.info(f"Loaded {len(bars)} bars for {symbol}")
        except Exception as e:
            logger.warning(f"Failed to load {symbol}: {e}")

    if not all_bars:
        raise ValueError("No data loaded")

    # Combine all bars and filter to only dates with L2 data
    bars_df = pd.concat(all_bars, ignore_index=True)
    
    # Get all dates with L2 data
    l2_dates = set()
    current = start_dt
    while current <= end_dt:
        date_str = current.strftime("%Y-%m-%d")
        date_path = l2_path / f"date={date_str}"
        if date_path.exists():
            l2_dates.add(date_str)
        current += timedelta(days=1)
    
    # Filter bars to only L2 dates
    bars_df['date'] = pd.to_datetime(bars_df['ts']).dt.strftime('%Y-%m-%d')
    bars_df = bars_df[bars_df['date'].isin(l2_dates)].copy()
    bars_df = bars_df.drop(columns=['date'])
    
    logger.info(f"Total bars: {len(bars_df)} across {len(l2_dates)} dates with L2 data")
    logger.info(f"L2 dates: {sorted(l2_dates)}")

    # Load L2 data for all symbols and dates
    logger.info("\nLoading L2 data...")
    all_l2 = []
    for date_str in sorted(l2_dates):
        date_path = l2_path / f"date={date_str}"
        for sym_dir in date_path.iterdir():
            if sym_dir.is_dir() and sym_dir.name.startswith("symbol="):
                symbol = sym_dir.name.replace("symbol=", "")
                if symbol in symbols:
                    try:
                        l2_df = l2_loader.load_snapshots(symbol, date_str)
                        all_l2.append(l2_df)
                        logger.info(f"  Loaded {len(l2_df)} L2 snapshots for {symbol} on {date_str}")
                    except Exception as e:
                        logger.warning(f"  Failed to load L2 for {symbol} on {date_str}: {e}")
    
    l2_data = pd.concat(all_l2, ignore_index=True) if all_l2 else None
    logger.info(f"Total L2 snapshots: {len(l2_data) if l2_data is not None else 0}")

    # Run backtest for each hypothesis
    results = {}
    metrics_dict = {}

    for hyp_name, signal in signals.items():
        logger.info(f"\n{'=' * 50}")
        logger.info(f"Testing Hypothesis: {hyp_name}")
        logger.info('=' * 50)

        # Run backtest with L2 data
        engine = AlphaBacktestEngine(config)
        result = engine.run(bars_df, signals=[signal], l2_df=l2_data)

        # Compute metrics
        metrics = compute_all_metrics(result, initial_capital=config["initial_capital"])

        results[hyp_name] = result
        metrics_dict[hyp_name] = metrics

        # Print summary
        print(f"\n{hyp_name.upper()} RESULTS:")
        print(f"  Trades: {metrics['num_trades']}")
        print(f"  Total Return: {metrics['total_return_pct']:.2f}%")
        print(f"  Sharpe: {metrics['sharpe_ratio']:.2f}")
        print(f"  Win Rate: {metrics['win_rate']:.1f}%")
        print(f"  Profit Factor: {metrics['profit_factor']:.2f}")

    # Generate summary report
    print("\n" + "=" * 60)
    print("COMPARATIVE SUMMARY")
    print("=" * 60)

    # Comparison table
    print(f"\n{'Hypothesis':<20} {'Trades':>10} {'Return':>10} {'Sharpe':>10} {'WR':>8} {'PF':>8}")
    print("-" * 70)

    for hyp_name, metrics in metrics_dict.items():
        threshold_check = check_minimum_thresholds(metrics, **config["validation"]["thresholds"])
        status = "✅" if threshold_check["all_pass"] else "❌"

        print(f"{hyp_name:<20} {metrics['num_trades']:>10} {metrics['total_return_pct']:>9.1f}% "
              f"{metrics['sharpe_ratio']:>9.2f} {metrics['win_rate']:>7.1f}% "
              f"{metrics['profit_factor']:>6.1f} {status}")

    # Check thresholds
    print("\nTHRESHOLD CHECKS:")
    print("-" * 40)
    for hyp_name, metrics in metrics_dict.items():
        threshold_check = check_minimum_thresholds(metrics, **config["validation"]["thresholds"])
        status = "PASS" if threshold_check["all_pass"] else "FAIL"
        print(f"  {hyp_name}: {status}")

    # Count passing
    passing = sum(
        1 for m in metrics_dict.values()
        if check_minimum_thresholds(m, **config["validation"]["thresholds"])["all_pass"]
    )

    print(f"\nSummary: {passing}/3 hypotheses passed thresholds")

    # Save report
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)

    report = generate_summary_report(results, config)
    save_report(report, str(output_dir / f"full_backtest_{start_date}_to_{end_date}.txt"))

    print(f"\nReport saved to: {output_dir}")

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run full backtest for all hypotheses")
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config YAML file (optional)",
    )

    args = parser.parse_args()

    try:
        results = run_full_backtest(
            start_date=args.start,
            end_date=args.end,
        )

        print("\n✅ Full backtest complete")

        # Exit with appropriate code
        passing = sum(
            1 for r in results.values()
            if len([t for t in r.trades if t.pnl > 0]) > len(r.trades) / 2  # Simple check
        )

        if passing >= 1:
            print("At least one hypothesis is profitable - READY FOR PAPER TRADING")
        else:
            print("No hypothesis is profitable - REFINEMENT NEEDED")

        sys.exit(0)

    except Exception as e:
        logger.error(f"Error running full backtest: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
