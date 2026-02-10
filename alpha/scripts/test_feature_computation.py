#!/usr/bin/env python3
"""Debug why signals aren't generating with detailed logging."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from src.data import L2Loader, GoldLoader
from src.features.l2_features import AlphaL2Features

# Load data
symbol = 'HAL'
date = '2025-12-23'

l2_loader = L2Loader()
gold_loader = GoldLoader()

l2_df = l2_loader.load_snapshots(symbol, date)
bars = gold_loader.load_bars(symbol, date, date)

print(f"Loaded {len(l2_df)} L2 snapshots and {len(bars)} bars for {symbol} on {date}")

# Initialize feature engineer
config = {"features": {}}
l2_features = AlphaL2Features(config)

# Test on first L2 snapshot
snapshot = l2_df.iloc[100]  # Skip first few to avoid startup issues
features = l2_features.compute_all_features(snapshot)

print(f"\nL2 Snapshot @ {snapshot['ts_utc']}:")
print(f"  bid_px_1: {snapshot.get('bid_px_1')}")
print(f"  ask_px_1: {snapshot.get('ask_px_1')}")
print(f"  bid_sz_1: {snapshot.get('bid_sz_1')}")
print(f"  ask_sz_1: {snapshot.get('ask_sz_1')}")

print(f"\nComputed Features:")
print(f"  spread: {features.get('spread')}")
print(f"  mid_price: {features.get('mid_price')}")
print(f"  book_imbalance_5: {features.get('book_imbalance_5')}")
print(f"  book_imbalance_10: {features.get('book_imbalance_10')}")

# Find a bar close to this L2 snapshot
snapshot_time = pd.to_datetime(snapshot['ts_utc'])
bars['time_diff'] = abs((bars['ts'] - snapshot_time).dt.total_seconds())
closest_bar = bars.loc[bars['time_diff'].idxmin()]

print(f"\nClosest bar @ {closest_bar['ts']}:")
print(f"  close: {closest_bar['close']}")
print(f"  spread_pct: {features.get('spread') / closest_bar['close'] * 100:.4f}%")

# Check signal conditions
book_imb = features.get('book_imbalance_5')
spread_pct = features.get('spread') / closest_bar['close'] * 100

print(f"\nSignal Check (relaxed thresholds):")
print(f"  |book_imb| > 0.20: {abs(book_imb) > 0.20} (value: {book_imb:.3f})")
print(f"  spread_pct < 0.10: {spread_pct < 0.10} (value: {spread_pct:.4f}%)")

if abs(book_imb) > 0.20 and spread_pct < 0.10:
    print(f"\n✅ SIGNAL CONDITIONS MET!")
else:
    print(f"\n❌ Signal conditions NOT met")
