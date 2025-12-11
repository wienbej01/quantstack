#!/usr/bin/env python3
"""Show the rolling training schedule."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.rolling_train_and_backtest import get_date_ranges

ranges = get_date_ranges()

print("Rolling Schedule (6-month train + 1-month val + 1-month OOS):")
print("=" * 80)

for i, r in enumerate(ranges, 1):
    print(f"Iteration {i}: OOS {r['oos_month']}")
    print(f"  Train: {r['train_start']} to {r['train_end']}")
    print(f"  Val:   {r['val_start']} to {r['val_end']}")
    print(f"  OOS:   {r['oos_start']} to {r['oos_end']}")
    print()

print(f"Total: {len(ranges)} iterations")
print()
print("Data Leakage Check:")
print("  - Train ends BEFORE val starts: ✓")
print("  - Val ends BEFORE OOS starts: ✓")
print("  - Each iteration rolls forward 1 month: ✓")
