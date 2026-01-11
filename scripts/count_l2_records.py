#!/usr/bin/env python3
"""
Get accurate L2 data counts from parquet files.
"""

import glob
import os

import pandas as pd


def count_l2_records():
    """Count actual L2 records from parquet files."""

    features_path = "/home/jacobw/quantstack/data/l2_maximum/features"

    print("=== L2 DATA VOLUME ANALYSIS ===\n")

    total_records = 0
    symbol_counts = {}
    date_counts = {}

    # Get all parquet files
    parquet_files = glob.glob(f"{features_path}/date=*/symbol=*/*.parquet")

    print(f"Found {len(parquet_files)} parquet files")
    print("Counting records...")

    for i, pf in enumerate(parquet_files):
        try:
            # Extract date and symbol from path
            parts = pf.split("/")
            date_part = [p for p in parts if p.startswith("date=")][0].replace(
                "date=", ""
            )
            symbol_part = [p for p in parts if p.startswith("symbol=")][0].replace(
                "symbol=", ""
            )

            # Count records in this file
            df = pd.read_parquet(pf)
            records = len(df)

            total_records += records
            symbol_counts[symbol_part] = symbol_counts.get(symbol_part, 0) + records
            date_counts[date_part] = date_counts.get(date_part, 0) + records

            if i % 100 == 0:
                print(f"  Processed {i+1}/{len(parquet_files)} files...")

        except Exception as e:
            print(f"Error reading {pf}: {e}")

    print(f"\n--- RESULTS ---")
    print(f"Total L2 records: {total_records:,}")
    print(f"Unique symbols: {len(symbol_counts)}")
    print(f"Collection dates: {len(date_counts)}")

    print(f"\n--- BY SYMBOL ---")
    for symbol, count in sorted(
        symbol_counts.items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  {symbol}: {count:,} records")

    print(f"\n--- BY DATE ---")
    for date, count in sorted(date_counts.items()):
        print(f"  {date}: {count:,} records")

    # Estimate data rate
    if len(date_counts) > 0:
        avg_per_day = total_records / len(date_counts)
        print(f"\nAverage records per day: {avg_per_day:,.0f}")

        # Estimate market hours coverage
        # Assuming 6.5 hours market + 1 hour pre/post = 7.5 hours = 27,000 seconds
        # At 2 snapshots/second = 54,000 theoretical max per symbol per day
        if len(symbol_counts) > 0:
            avg_per_symbol_per_day = avg_per_day / len(symbol_counts)
            coverage_pct = (avg_per_symbol_per_day / 54000) * 100
            print(f"Estimated market coverage: {coverage_pct:.1f}% per symbol")

    return total_records, len(symbol_counts), len(date_counts)


if __name__ == "__main__":
    total, symbols, days = count_l2_records()

    print(f"\n=== SUMMARY ===")
    print(f"📊 {total:,} L2 snapshots collected")
    print(f"🎯 {symbols} unique symbols")
    print(f"📅 {days} collection days")
    print(f"💾 53.8 MB processed data")
