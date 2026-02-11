#!/usr/bin/env python3
"""Run single hypothesis test.

Tests one hypothesis (H1, H2, or H3) with walk-forward validation.
Generates report with performance metrics and pass/fail recommendation.

Usage:
    python scripts/run_hypothesis_test.py --hypothesis order_flow --start 2024-01-01 --end 2024-12-31
    python scripts/run_hypothesis_test.py --hypothesis whale_detect --start 2024-01-01 --end 2024-12-31
    python scripts/run_hypothesis_test.py --hypothesis liquidity_fade --start 2024-01-01 --end 2024-12-31
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd  # ADD THIS LINE - Required for pd.concat()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest import AlphaBacktestEngine
from src.backtest.regime_split import RegimeStratifier
from src.backtest.walk_forward import WalkForwardValidator
from src.data import GoldLoader, L2Loader, SipLoader
from src.metrics import (
    check_minimum_thresholds,
    compute_all_metrics,
    format_metrics_report,
)
from src.metrics.diagnostics import (
    analyze_attribution,
    generate_trade_attribution,
    save_report,
)
from src.signals import LiquidityFadeSignal, OrderFlowSignal, WhaleDetectSignal

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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


def get_signal(hypothesis: str, config: dict):
    """Get signal instance for hypothesis."""
    if hypothesis == "order_flow":
        return OrderFlowSignal(config)
    elif hypothesis == "whale_detect":
        return WhaleDetectSignal(config)
    elif hypothesis == "liquidity_fade":
        return LiquidityFadeSignal(config)
    else:
        raise ValueError(f"Unknown hypothesis: {hypothesis}")


def run_single_hypothesis(
    hypothesis: str,
    start_date: str,
    end_date: str,
    config: dict = None,
) -> dict:
    """Run backtest for a single hypothesis.

    Args:
        hypothesis: Hypothesis name (order_flow, whale_detect, liquidity_fade)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        config: Optional config dict

    Returns:
        Dict with results and metrics
    """
    if config is None:
        config = DEFAULT_CONFIG

    logger.info(f"Running hypothesis test: {hypothesis}")
    logger.info(f"Date range: {start_date} to {end_date}")

    # Initialize signal
    signal = get_signal(hypothesis, config)

    # Load data
    logger.info("Loading data...")
    gold_loader = GoldLoader()
    sip_loader = SipLoader()

    # Get SIP universe for date range
    sip_universe_df = sip_loader.load_universe_range(start_date, end_date)
    symbols = sip_universe_df["symbol"].unique().tolist()
    logger.info(f"SIP universe: {len(symbols)} symbols")

    # Load Gold data for symbols (configurable limit)
    max_symbols = config.get("max_symbols", 10)
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    logger.info(f"Testing {len(symbols)} symbols (max_symbols={max_symbols})")

    all_bars = []
    for symbol in symbols:
        try:
            bars = gold_loader.load_bars(symbol, start_date, end_date)
            if not bars.empty:
                bars["symbol"] = symbol  # ADD THIS LINE - Critical fix
                all_bars.append(bars)
                logger.info(f"Loaded {len(bars)} bars for {symbol}")
        except Exception as e:
            logger.warning(f"Failed to load {symbol}: {e}")

    if not all_bars:
        raise ValueError("No data loaded")

    # Combine all bars
    bars_df = pd.concat(all_bars, ignore_index=True)
    logger.info(f"Total bars: {len(bars_df)}")

    # Run backtest
    logger.info("Running backtest...")
    engine = AlphaBacktestEngine(config)
    result = engine.run(bars_df, signals=[signal])

    # Compute metrics
    logger.info("Computing metrics...")
    metrics = compute_all_metrics(result, initial_capital=config["initial_capital"])

    # Check thresholds
    thresholds = config["validation"]["thresholds"]
    threshold_check = check_minimum_thresholds(metrics, **thresholds)

    # Print report
    print("\n" + format_metrics_report(metrics))

    # Print threshold results
    print("\nTHRESHOLD CHECKS")
    print("-" * 40)
    print(
        f"Sharpe > {thresholds['min_sharpe']}:        {'✅ PASS' if threshold_check['sharpe_pass'] else '❌ FAIL'}"
    )
    print(
        f"Win Rate > {thresholds['min_win_rate']}%:       {'✅ PASS' if threshold_check['win_rate_pass'] else '❌ FAIL'}"
    )
    print(
        f"Profit Factor > {thresholds['min_profit_factor']}:  {'✅ PASS' if threshold_check['profit_factor_pass'] else '❌ FAIL'}"
    )
    print(
        f"T-Stat > {thresholds['min_t_stat']}:          {'✅ PASS' if threshold_check['t_stat_pass'] else '❌ FAIL'}"
    )
    print(
        f"Trades > {thresholds['min_trades']}:           {'✅ PASS' if threshold_check['min_trades_pass'] else '❌ FAIL'}"
    )
    print("-" * 40)
    print(
        f"\nOverall: {'✅ ALL THRESHOLDS PASSED' if threshold_check['all_pass'] else '❌ SOME THRESHOLDS FAILED'}"
    )

    # Generate trade attribution
    attribution_df = generate_trade_attribution(result.trades)
    if not attribution_df.empty:
        logger.info("Trade attribution analysis...")
        analysis = analyze_attribution(attribution_df)

        print("\nTRADE ATTRIBUTION")
        print("-" * 40)
        if "win_rate_by_exit_reason" in analysis:
            print("Win Rate by Exit Reason:")
            for reason, wr in analysis["win_rate_by_exit_reason"].items():
                print(f"  {reason}: {wr:.1f}%")

        if "win_rate_by_signal" in analysis:
            print("\nWin Rate by Signal:")
            for signal, wr in analysis["win_rate_by_signal"].items():
                print(f"  {signal}: {wr:.1f}%")

    # Return results
    return {
        "hypothesis": hypothesis,
        "metrics": metrics,
        "threshold_check": threshold_check,
        "result": result,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run single hypothesis test")
    parser.add_argument(
        "--hypothesis",
        type=str,
        required=True,
        choices=["order_flow", "whale_detect", "liquidity_fade"],
        help="Hypothesis to test",
    )
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
        result = run_single_hypothesis(
            hypothesis=args.hypothesis,
            start_date=args.start,
            end_date=args.end,
        )

        # Save report
        output_dir = Path(__file__).parent.parent / "output"
        output_dir.mkdir(exist_ok=True)

        report_path = (
            output_dir / f"{args.hypothesis}_report_{args.start}_to_{args.end}.txt"
        )
        save_report(
            format_metrics_report(result["metrics"])
            + "\n\n"
            + str(result["threshold_check"]),
            report_path,
        )

        print(f"\nReport saved to: {report_path}")

        # Exit with appropriate code
        sys.exit(0 if result["threshold_check"]["all_pass"] else 1)

    except Exception as e:
        logger.error(f"Error running hypothesis test: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
