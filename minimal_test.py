#!/usr/bin/env python3
"""Minimal test to check data access."""

import sys
from pathlib import Path

# Add all qx modules to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "qx-data" / "src"))

from qx_data.gold_loader import load_bars


def main():
    print("Minimal data access test")
    print("=" * 30)

    try:
        # Try to load just one symbol for one day
        bars = load_bars(
            root="/home/jacobw/gcs-mount",
            family="stocks",
            symbols=["AAPL"],
            dates=["2024-01-03"],
            validate=False,
        )
        print(f"✓ Loaded {len(bars)} bars for AAPL on 2024-01-03")

        if not bars.empty:
            print(f"Sample columns: {list(bars.columns)}")
            print(f"Timestamp range: {bars['ts'].min()} to {bars['ts'].max()}")
            print(
                f"Price range: ${bars['close'].min():.2f} - ${bars['close'].max():.2f}"
            )

        print("✓ Data access test successful!")

    except Exception as e:
        print(f"✗ Data access failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
