#!/usr/bin/env python3
"""Run multi-strategy pattern backtest for January 2025."""

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.multi_strategy_runner import MultiStrategyBacktestRunner


def main():
    """Run the multi-strategy backtest."""

    # Paths
    base_dir = Path(__file__).parent.parent
    strategies_yaml = base_dir / "config" / "top5_strategies.yaml"
    output_dir = base_dir / "output" / "jan2025_backtest"

    # Create runner
    runner = MultiStrategyBacktestRunner(
        strategies_yaml=strategies_yaml,
        sip_dir=Path("/home/jacobw/intraday_stack/data/daily_sip"),
        gold_dir=Path("/home/jacobw/gcs-mount/gold/stocks/1m"),
        output_dir=output_dir,
        lookback_days=5,
    )

    # Run backtest
    try:
        results = runner.run()
        print("\n✅ Backtest completed successfully!")
        print(f"📊 Results saved to: {output_dir}")

        # Print summary
        print("\n📈 Strategy Performance Summary:")
        print("-" * 60)
        for strategy_id, metrics in results.items():
            print(
                f"{strategy_id:30} | Trades: {metrics['total_trades']:3d} | Return: {metrics['total_return']:6.2%}"
            )

        return 0

    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
