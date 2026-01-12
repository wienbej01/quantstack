#!/usr/bin/env python3
"""Simplified pattern backtest runner for testing."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Add paths
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir))

from src.pattern_parser import parse_strategies_yaml
from src.rule_evaluator import RuleEvaluator


def create_mock_data(n_bars=1000, n_symbols=5):
    """Create mock data for testing."""
    symbols = [f"SYMBOL_{i}" for i in range(n_symbols)]

    data = []
    base_time = datetime(2025, 1, 1, 9, 30)  # Start at market open

    for i in range(n_bars):
        for symbol in symbols:
            ts = base_time + timedelta(minutes=i)

            # Create realistic OHLCV data
            price = 100 + np.random.randn() * 5
            data.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "open": price,
                    "high": price + abs(np.random.randn()),
                    "low": price - abs(np.random.randn()),
                    "close": price + np.random.randn() * 0.5,
                    "volume": int(1000 + np.random.randn() * 500),
                    # Add some mock features that match our patterns
                    "atr_14": abs(np.random.randn() * 2),
                    "session_range_pct": np.random.rand() * 100,
                    "rvol": abs(np.random.randn() * 2),
                    "rel_strength_60m": np.random.randn() * 5,
                    "ret_60m": np.random.randn() * 0.02,
                    "price_vs_vwap_pct": np.random.randn() * 2,
                    "is_first_hour": i < 60,  # First hour
                    "is_power_hour": i > 330,  # Last hour
                    "rel_outperform_extreme": np.random.rand() < 0.05,
                    "rel_underperform_extreme": np.random.rand() < 0.05,
                    "price_up_vol_weak": np.random.rand() < 0.1,
                    "price_down_vol_weak": np.random.rand() < 0.1,
                    "price_up_vol_strong": np.random.rand() < 0.1,
                    "price_down_vol_strong": np.random.rand() < 0.1,
                }
            )

    return pd.DataFrame(data)


def discretize_features(df):
    """Add discretized features."""
    df = df.copy()

    # Discretize continuous features into bins (0-4)
    for col in [
        "atr_14",
        "session_range_pct",
        "rvol",
        "rel_strength_60m",
        "ret_60m",
        "price_vs_vwap_pct",
    ]:
        if col in df.columns:
            df[f"{col}_bin"] = pd.qcut(
                df[col], q=5, labels=[0, 1, 2, 3, 4], duplicates="drop"
            ).fillna(2)

    # Boolean features are already binary
    for col in [
        "is_first_hour",
        "is_power_hour",
        "rel_outperform_extreme",
        "rel_underperform_extreme",
        "price_up_vol_weak",
        "price_down_vol_weak",
        "price_up_vol_strong",
        "price_down_vol_strong",
    ]:
        if col in df.columns:
            df[f"{col}_bin"] = df[col]

    return df


def simple_backtest():
    """Run a simple backtest to test pattern evaluation."""
    print("=" * 60)
    print("SIMPLE PATTERN BACKTEST TEST")
    print("=" * 60)

    # Load strategies
    strategies_yaml = Path("config/top5_strategies.yaml")
    strategies = parse_strategies_yaml(strategies_yaml)

    print(f"Loaded {len(strategies)} strategies:")
    for strategy in strategies:
        print(f"  - {strategy.method_id}: {strategy.rule_string}")

    # Create evaluators
    evaluators = {}
    for strategy in strategies:
        evaluators[strategy.method_id] = RuleEvaluator(strategy.rule_string)

    # Create mock data
    print("\nGenerating mock data...")
    df = create_mock_data(n_bars=500, n_symbols=3)
    df = discretize_features(df)

    print(f"Created {len(df)} bars for {df['symbol'].nunique()} symbols")
    print(f"Date range: {df['ts'].min()} to {df['ts'].max()}")

    # Test pattern evaluation
    print("\nTesting pattern evaluation...")

    results = {}
    for strategy in strategies:
        strategy_id = strategy.method_id
        evaluator = evaluators[strategy_id]

        signals = 0
        for _, bar in df.iterrows():
            if evaluator.evaluate(bar.to_dict()):
                signals += 1

        signal_rate = signals / len(df) * 100
        results[strategy_id] = {
            "signals": signals,
            "signal_rate": signal_rate,
            "expected_expectancy": strategy.expectancy,
            "expected_win_rate": strategy.win_rate,
        }

        print(f"{strategy_id:30} | Signals: {signals:4d} | Rate: {signal_rate:5.2f}%")

    # Simple P&L simulation
    print("\nSimulating trades...")

    portfolio_value = 1000000  # $1M starting capital
    position_size = 100  # shares
    commission = 2.0  # per round-turn

    total_trades = 0
    total_pnl = 0

    for strategy in strategies:
        strategy_id = strategy.method_id
        evaluator = evaluators[strategy_id]

        strategy_trades = 0
        strategy_pnl = 0

        for _, bar in df.iterrows():
            if evaluator.evaluate(bar.to_dict()):
                # Simulate trade
                entry_price = bar["close"]

                # Simulate random exit after some bars (simplified)
                exit_return = np.random.normal(
                    strategy.expectancy / 100, 0.02
                )  # Use expected return
                exit_price = entry_price * (1 + exit_return)

                # Calculate P&L
                if strategy.direction == "LONG":
                    pnl = (exit_price - entry_price) * position_size - commission
                else:
                    pnl = (entry_price - exit_price) * position_size - commission

                strategy_pnl += pnl
                strategy_trades += 1

        total_trades += strategy_trades
        total_pnl += strategy_pnl

        if strategy_trades > 0:
            avg_pnl = strategy_pnl / strategy_trades
            print(
                f"{strategy_id:30} | Trades: {strategy_trades:3d} | P&L: ${strategy_pnl:8.2f} | Avg: ${avg_pnl:6.2f}"
            )
        else:
            print(
                f"{strategy_id:30} | Trades: {strategy_trades:3d} | P&L: $    0.00 | Avg: $ 0.00"
            )

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total trades: {total_trades}")
    print(f"Total P&L: ${total_pnl:.2f}")
    print(f"Return: {total_pnl / portfolio_value * 100:.2f}%")

    if total_trades > 0:
        print(f"Average P&L per trade: ${total_pnl / total_trades:.2f}")

    print("=" * 60)
    print("✅ Pattern backtest test completed successfully!")

    return results


if __name__ == "__main__":
    simple_backtest()
