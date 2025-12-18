#!/usr/bin/env python3
"""Fix timezone inconsistencies in gold data."""

import os
import sys
from pathlib import Path

import pandas as pd

# Add R2K ingest to path
r2k_path = Path.home() / "data_download" / "r2k_ingest"
sys.path.insert(0, str(r2k_path.parent))


def check_timezone_consistency():
    """Check timezone consistency in gold data."""
    print("🔍 Checking timezone consistency in gold data...")

    gold_path = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
    sample_symbols = ["AAPL", "MSFT", "JPM", "GS", "BAC"]

    timezone_issues = []

    for symbol in sample_symbols:
        symbol_path = gold_path / symbol
        if not symbol_path.exists():
            continue

        # Find latest parquet file
        parquet_files = list(symbol_path.rglob("*.parquet"))
        if not parquet_files:
            continue

        latest_file = max(parquet_files, key=lambda x: x.stat().st_mtime)

        try:
            df = pd.read_parquet(latest_file)

            # Check timestamp column
            if "ts" in df.columns:
                # Check if timestamps are timezone-aware
                ts_sample = df["ts"].iloc[0]

                if hasattr(ts_sample, "tz"):
                    tz_info = ts_sample.tz
                    print(f"   {symbol}: {tz_info}")

                    if tz_info is None:
                        timezone_issues.append(f"{symbol}: No timezone info")
                    elif str(tz_info) != "America/New_York":
                        timezone_issues.append(f"{symbol}: Wrong timezone {tz_info}")
                else:
                    # Numeric timestamp
                    print(f"   {symbol}: Numeric timestamp (needs conversion)")
                    timezone_issues.append(f"{symbol}: Numeric timestamp")

        except Exception as e:
            print(f"   {symbol}: Error reading file - {e}")
            timezone_issues.append(f"{symbol}: Read error")

    if timezone_issues:
        print("\n❌ Timezone Issues Found:")
        for issue in timezone_issues:
            print(f"   - {issue}")
        return False
    else:
        print("\n✅ All sampled symbols have consistent ET timezone")
        return True


def fix_folder_structures():
    """Fix inconsistent ticker folder structures."""
    print("🔧 Checking folder structures...")

    gold_path = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    flat_structure_symbols = []
    nested_structure_symbols = []

    # Check first 20 symbols for structure
    symbols = sorted(
        [d.name for d in gold_path.iterdir() if d.is_dir() and d.name != "1m"]
    )[:20]

    for symbol in symbols:
        symbol_path = gold_path / symbol

        # Check if files are directly in symbol folder (flat) or in year folders (nested)
        parquet_files = list(symbol_path.glob("*.parquet"))
        year_dirs = [
            d for d in symbol_path.iterdir() if d.is_dir() and d.name.isdigit()
        ]

        if parquet_files and not year_dirs:
            flat_structure_symbols.append(symbol)
        elif year_dirs and not parquet_files:
            nested_structure_symbols.append(symbol)
        else:
            print(f"   {symbol}: Mixed structure (needs cleanup)")

    print(f"   Flat structure: {len(flat_structure_symbols)} symbols")
    print(f"   Nested structure: {len(nested_structure_symbols)} symbols")

    if flat_structure_symbols:
        print(f"   Sample flat: {flat_structure_symbols[:5]}")
    if nested_structure_symbols:
        print(f"   Sample nested: {nested_structure_symbols[:5]}")

    return len(flat_structure_symbols) == 0  # True if all are properly nested


def main():
    """Main data validation and fix process."""
    print("🔍 Gold Data Validation and Fix Process")
    print("=" * 50)

    # Check timezone consistency
    timezone_ok = check_timezone_consistency()

    # Check folder structures
    structure_ok = fix_folder_structures()

    print("\n📊 Validation Summary:")
    print(f"   Timezone consistency: {'✅' if timezone_ok else '❌'}")
    print(f"   Folder structures: {'✅' if structure_ok else '❌'}")

    if not timezone_ok or not structure_ok:
        print("\n🔧 Fixes needed:")
        if not timezone_ok:
            print("   - Timezone normalization required")
        if not structure_ok:
            print("   - Folder structure cleanup required")

        print("\n💡 Recommendation:")
        print("   Run data update pipeline to fix issues:")
        print("   python3 scripts/update_gold_data.py")
    else:
        print("\n✅ Gold data is consistent and ready for use")


if __name__ == "__main__":
    main()
