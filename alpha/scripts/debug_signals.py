#!/usr/bin/env python3
"""Inspect L2 data and debug signal generation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from src.data import L2Loader, GoldLoader
from src.signals import OrderFlowSignal

# 1. Inspect L2 data for Dec 23 (full day coverage)
print("="*60)
print("1. L2 DATA INSPECTION - Dec 23, 2025")
print("="*60)

l2_loader = L2Loader()
symbol = 'HAL'  # Has full day L2 data
date = '2025-12-23'

l2_df = l2_loader.load_snapshots(symbol, date)
print(f"\n{symbol} on {date}:")
print(f"  Snapshots: {len(l2_df)}")
print(f"  Time range: {l2_df['ts_utc'].min()} to {l2_df['ts_utc'].max()}")
print(f"  Duration: {(l2_df['ts_utc'].max() - l2_df['ts_utc'].min()).total_seconds() / 60:.1f} minutes")

# Check for order book imbalance
if 'bid_px_1' in l2_df.columns and 'ask_px_1' in l2_df.columns:
    l2_df['bid_size_total'] = l2_df[[f'bid_sz_{i}' for i in range(1, 11) if f'bid_sz_{i}' in l2_df.columns]].sum(axis=1)
    l2_df['ask_size_total'] = l2_df[[f'ask_sz_{i}' for i in range(1, 11) if f'ask_sz_{i}' in l2_df.columns]].sum(axis=1)
    l2_df['book_imbalance'] = (l2_df['bid_size_total'] - l2_df['ask_size_total']) / (l2_df['bid_size_total'] + l2_df['ask_size_total'])
    
    print(f"\nBook Imbalance Stats:")
    print(f"  Mean: {l2_df['book_imbalance'].mean():.3f}")
    print(f"  Std: {l2_df['book_imbalance'].std():.3f}")
    print(f"  Min: {l2_df['book_imbalance'].min():.3f}")
    print(f"  Max: {l2_df['book_imbalance'].max():.3f}")
    print(f"  |Imbalance| > 0.20: {(l2_df['book_imbalance'].abs() > 0.20).sum()} snapshots ({(l2_df['book_imbalance'].abs() > 0.20).sum() / len(l2_df) * 100:.1f}%)")
    print(f"  |Imbalance| > 0.35: {(l2_df['book_imbalance'].abs() > 0.35).sum()} snapshots ({(l2_df['book_imbalance'].abs() > 0.35).sum() / len(l2_df) * 100:.1f}%)")

# Check spread
if 'l1_bid' in l2_df.columns and 'l1_ask' in l2_df.columns:
    l2_df['spread'] = l2_df['l1_ask'] - l2_df['l1_bid']
    l2_df['spread_pct'] = l2_df['spread'] / l2_df['l1_bid'] * 100
    
    print(f"\nSpread Stats:")
    print(f"  Mean: {l2_df['spread_pct'].mean():.3f}%")
    print(f"  Median: {l2_df['spread_pct'].median():.3f}%")
    print(f"  Spread < 0.05%: {(l2_df['spread_pct'] < 0.05).sum()} snapshots ({(l2_df['spread_pct'] < 0.05).sum() / len(l2_df) * 100:.1f}%)")
    print(f"  Spread < 0.10%: {(l2_df['spread_pct'] < 0.10).sum()} snapshots ({(l2_df['spread_pct'] < 0.10).sum() / len(l2_df) * 100:.1f}%)")

print(f"\nSample L2 data:")
print(l2_df[['ts_utc', 'l1_bid', 'l1_ask', 'bid_sz_1', 'ask_sz_1']].head(10))

# 2. Debug signal generation
print("\n" + "="*60)
print("2. SIGNAL GENERATION DEBUG")
print("="*60)

# Load Gold data
gold_loader = GoldLoader()
bars = gold_loader.load_bars(symbol, date, date)
print(f"\nGold bars for {symbol} on {date}: {len(bars)}")
print(f"Time range: {bars['ts'].min()} to {bars['ts'].max()}")

# Create signal with relaxed thresholds
config = {
    "initial_capital": 100000,
    "position_size_pct": 0.02,
    "max_positions": 5,
    "order_flow": {
        "book_imbalance_threshold": 0.20,
        "trade_imbalance_threshold": 0.15,
        "max_spread_pct": 0.10,
        "target_return_pct": 0.004,
        "stop_loss_pct": 0.0025,
        "time_limit_minutes": 10
    }
}

signal = OrderFlowSignal(config)

# Test signal on first 10 bars
print(f"\nTesting OrderFlowSignal on first 10 bars:")
bars['symbol'] = symbol

for i in range(min(10, len(bars))):
    bar = bars.iloc[i:i+1]
    bar_time = bar['ts'].iloc[0]
    
    # Try to generate signal
    try:
        result = signal.generate(bar, l2_data=None)  # Will load L2 internally
        print(f"\nBar {i+1} @ {bar_time}:")
        print(f"  Signal: {result}")
    except Exception as e:
        print(f"\nBar {i+1} @ {bar_time}:")
        print(f"  ERROR: {e}")

print("\n" + "="*60)
print("DIAGNOSIS COMPLETE")
print("="*60)
