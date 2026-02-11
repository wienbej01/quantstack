#!/usr/bin/env python3
"""Run backtest with threshold sensitivity matrix."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta

import pandas as pd
from src.backtest import AlphaBacktestEngine
from src.data import GoldLoader, L2Loader
from src.metrics import compute_all_metrics
from src.signals import LiquidityFadeSignal, OrderFlowSignal, WhaleDetectSignal

# Base config
base_config = {
    "initial_capital": 100000,
    "position_size_pct": 0.02,
    "max_positions": 5,
    "order_flow": {},
    "whale_detect": {},
    "liquidity_fade": {},
}

# Threshold matrix
threshold_matrix = {
    "order_flow": [
        {
            "book_imbalance_threshold": 0.20,
            "trade_imbalance_threshold": 0.15,
            "max_spread_pct": 0.10,
        },
        {
            "book_imbalance_threshold": 0.25,
            "trade_imbalance_threshold": 0.20,
            "max_spread_pct": 0.08,
        },
        {
            "book_imbalance_threshold": 0.35,
            "trade_imbalance_threshold": 0.25,
            "max_spread_pct": 0.05,
        },  # Current
    ],
    "whale_detect": [
        {
            "large_order_multiplier": 3.0,
            "min_relative_volume": 1.2,
            "min_flow_imbalance": 0.05,
        },
        {
            "large_order_multiplier": 4.0,
            "min_relative_volume": 1.3,
            "min_flow_imbalance": 0.08,
        },
        {
            "large_order_multiplier": 5.0,
            "min_relative_volume": 1.5,
            "min_flow_imbalance": 0.10,
        },  # Current
    ],
    "liquidity_fade": [
        {"depth_drop_threshold": 0.30, "price_spike_pct": 0.001},
        {"depth_drop_threshold": 0.40, "price_spike_pct": 0.0015},
        {"depth_drop_threshold": 0.50, "price_spike_pct": 0.002},  # Current
    ],
}

# Date range
start_date = "2025-12-23"
end_date = "2026-01-20"

# Load data
print("Loading data...")
gold_loader = GoldLoader()
l2_loader = L2Loader()
l2_path = Path("~/quantstack/data/l2/l2_maximum/raw").expanduser()

# Get symbols with L2 data
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
print(f"Found {len(symbols)} symbols with L2 data")

# Load Gold data
all_bars = []
for symbol in symbols:
    try:
        bars = gold_loader.load_bars(symbol, start_date, end_date)
        if not bars.empty:
            bars["symbol"] = symbol
            all_bars.append(bars)
    except Exception as e:
        pass

bars_df = pd.concat(all_bars, ignore_index=True)

# Get L2 dates
l2_dates = set()
current = start_dt
while current <= end_dt:
    date_str = current.strftime("%Y-%m-%d")
    date_path = l2_path / f"date={date_str}"
    if date_path.exists():
        l2_dates.add(date_str)
    current += timedelta(days=1)

# Filter to L2 dates
bars_df["date"] = pd.to_datetime(bars_df["ts"]).dt.strftime("%Y-%m-%d")
bars_df = bars_df[bars_df["date"].isin(l2_dates)].copy()
bars_df = bars_df.drop(columns=["date"])

print(f"Loaded {len(bars_df)} bars across {len(l2_dates)} dates")

# Load L2 data
print("Loading L2 data...")
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
                except Exception:
                    pass

l2_data = pd.concat(all_l2, ignore_index=True) if all_l2 else None
print(f"Loaded {len(l2_data) if l2_data is not None else 0} L2 snapshots")

# Run matrix
results = []

for hyp_name, threshold_sets in threshold_matrix.items():
    print(f"\n{'='*60}")
    print(f"Testing {hyp_name.upper()}")
    print("=" * 60)

    for i, thresholds in enumerate(threshold_sets, 1):
        # Update config
        config = base_config.copy()
        config[hyp_name].update(thresholds)

        # Create signal
        if hyp_name == "order_flow":
            signal = OrderFlowSignal(config)
        elif hyp_name == "whale_detect":
            signal = WhaleDetectSignal(config)
        else:
            signal = LiquidityFadeSignal(config)

        # Run backtest
        engine = AlphaBacktestEngine(config)
        result = engine.run(bars_df, signals=[signal], l2_df=l2_data)

        # Compute metrics
        metrics = compute_all_metrics(result, initial_capital=config["initial_capital"])

        # Store results
        results.append(
            {
                "hypothesis": hyp_name,
                "threshold_set": i,
                "thresholds": str(thresholds),
                "trades": metrics["num_trades"],
                "return_pct": metrics["total_return_pct"],
                "sharpe": metrics["sharpe_ratio"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown": metrics["max_drawdown_pct"],
            }
        )

        print(f"\nSet {i}: {thresholds}")
        print(f"  Trades: {metrics['num_trades']}")
        print(f"  Return: {metrics['total_return_pct']:.2f}%")
        print(f"  Sharpe: {metrics['sharpe_ratio']:.2f}")
        print(f"  Win Rate: {metrics['win_rate']:.1f}%")

# Save results
results_df = pd.DataFrame(results)
results_df.to_csv("output/threshold_matrix_results.csv", index=False)

print("\n" + "=" * 60)
print("THRESHOLD SENSITIVITY MATRIX RESULTS")
print("=" * 60)
print(results_df.to_string(index=False))
print(f"\nResults saved to: output/threshold_matrix_results.csv")
