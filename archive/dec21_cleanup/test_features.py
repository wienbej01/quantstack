#!/usr/bin/env python3
"""Test building features for one symbol/month."""

from pathlib import Path

import polars as pl


def test_single_symbol():
    print("Testing single symbol feature building...")

    # Load September 2025 AAPL data
    test_file = Path("/home/jacobw/gcs-mount/gold/stocks/1m/AAPL/2025/2025-09.parquet")
    df = pl.read_parquet(test_file)

    # Rename ts to timestamp
    df = df.rename({"ts": "timestamp"})

    print(f"Loaded {len(df)} rows for AAPL Sep 2025")
    print(
        f"Date range: {df['timestamp'].dt.date().min()} to {df['timestamp'].dt.date().max()}"
    )

    # Build basic features
    df = df.with_columns(
        [
            ((pl.col("close") - pl.col("open")) / pl.col("open")).alias("returns"),
            (pl.col("high") - pl.col("low")).alias("range"),
            pl.col("timestamp").dt.hour().alias("hour_et"),
        ]
    )

    # Add forward return
    df = df.with_columns([pl.col("returns").shift(-30).alias("return_30min")])

    # Select key columns
    features = df.select(
        ["timestamp", "returns", "return_30min", "hour_et", "volume"]
    ).drop_nulls()

    print(f"Generated {len(features)} feature rows")
    print("Sample features:")
    print(features.head(3))

    return features


if __name__ == "__main__":
    features = test_single_symbol()
    print("✅ Test successful!")
