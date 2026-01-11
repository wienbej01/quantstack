#!/usr/bin/env python3
"""Run pattern backtest from command line."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest_runner import PatternBacktestRunner


def main():
    parser = argparse.ArgumentParser(description="Backtest discovered trading patterns")

    parser.add_argument("--patterns", required=True, help="Path to patterns CSV file")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--output-dir", required=True, help="Output directory for results"
    )

    parser.add_argument(
        "--sip-dir",
        default="/home/jacobw/intraday_stack/data/daily_sip",
        help="SIP directory",
    )
    parser.add_argument(
        "--gold-dir",
        default="/home/jacobw/gcs-mount/gold/stocks/1m",
        help="Gold data directory",
    )

    parser.add_argument(
        "--position-size", type=int, default=100, help="Position size in shares"
    )
    parser.add_argument(
        "--commission", type=float, default=2.0, help="Commission per round-turn"
    )
    parser.add_argument(
        "--horizon", type=int, default=60, help="Exit horizon in minutes"
    )
    parser.add_argument(
        "--min-lift", type=float, default=2.0, help="Minimum pattern lift"
    )
    parser.add_argument(
        "--max-patterns", type=int, default=20, help="Maximum patterns to trade"
    )
    parser.add_argument(
        "--lookback-days", type=int, default=5, help="Days of lookback for features"
    )

    args = parser.parse_args()

    # Create runner
    runner = PatternBacktestRunner(
        patterns_csv=Path(args.patterns),
        start_date=args.start_date,
        end_date=args.end_date,
        sip_dir=Path(args.sip_dir),
        gold_dir=Path(args.gold_dir),
        output_dir=Path(args.output_dir),
        position_size=args.position_size,
        commission=args.commission,
        horizon_minutes=args.horizon,
        min_lift=args.min_lift,
        max_patterns=args.max_patterns,
        lookback_days=args.lookback_days,
    )

    # Run backtest
    runner.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
