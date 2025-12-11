#!/usr/bin/env python3
"""Validate that features have no data leakage."""

from pathlib import Path

import polars as pl


def validate():
    print("=" * 80)
    print("VALIDATING NO DATA LEAKAGE")
    print("=" * 80)

    features_path = Path("run/intraday_features_rolling/features.parquet")
    if not features_path.exists():
        print(f"ERROR: {features_path} not found")
        return

    features = pl.read_parquet(features_path)
    df = features.to_pandas()

    print(f"\nTotal rows: {len(df):,}")
    print(f"Unique symbols: {df['symbol'].nunique()}")
    print(f"Unique dates: {df['date'].nunique()}")

    # Check 1: Entry timestamp > signal timestamp
    df["entry_after_signal"] = df["entry_timestamp"] > df["timestamp"]
    entry_after_pct = df["entry_after_signal"].mean()
    print(f"\n✓ Entry after signal: {entry_after_pct:.2%}")
    if entry_after_pct < 1.0:
        print(f"  WARNING: {(1-entry_after_pct)*100:.2f}% of entries NOT after signal")

    # Check 2: No cross-day entries
    df["signal_date"] = df["timestamp"].dt.date
    df["entry_date"] = df["entry_timestamp"].dt.date
    same_day_entry = (df["signal_date"] == df["entry_date"]).mean()
    print(f"✓ Same-day entry: {same_day_entry:.2%}")
    if same_day_entry < 1.0:
        print(f"  WARNING: {(1-same_day_entry)*100:.2f}% of entries cross days")

    # Check 3: No cross-day exits
    df["exit_date"] = df["exit_timestamp"].dt.date
    same_day_exit = (df["entry_date"] == df["exit_date"]).mean()
    print(f"✓ Same-day exit: {same_day_exit:.2%}")
    if same_day_exit < 1.0:
        print(f"  WARNING: {(1-same_day_exit)*100:.2f}% of exits cross days")

    # Check 4: All exits before 16:00
    df["exit_hour"] = df["exit_timestamp"].dt.hour
    before_close = (df["exit_hour"] < 16).mean()
    print(f"✓ Exits before 16:00: {before_close:.2%}")
    if before_close < 1.0:
        late_exits = df[df["exit_hour"] >= 16]
        print(f"  WARNING: {len(late_exits)} exits at or after 16:00")
        print(
            f"  Latest exit: {df['exit_hour'].max()}:{df['exit_timestamp'].dt.minute.max():02d}"
        )

    # Check 5: Entry-to-exit duration
    df["duration_minutes"] = (
        df["exit_timestamp"] - df["entry_timestamp"]
    ).dt.total_seconds() / 60
    print(f"\n✓ Duration stats:")
    print(f"  Mean: {df['duration_minutes'].mean():.1f} minutes")
    print(f"  Median: {df['duration_minutes'].median():.1f} minutes")
    print(f"  Min: {df['duration_minutes'].min():.1f} minutes")
    print(f"  Max: {df['duration_minutes'].max():.1f} minutes")

    # Check 6: Label distribution
    print(f"\n✓ Label distribution:")
    print(f"  LONG: {df['label_long'].sum():,} ({df['label_long'].mean():.2%})")
    print(f"  SHORT: {df['label_short'].sum():,} ({df['label_short'].mean():.2%})")
    print(f"  NEUTRAL: {((df['label_long'] == 0) & (df['label_short'] == 0)).sum():,}")

    # Check 7: Feature sanity
    print(f"\n✓ Feature ranges:")
    print(f"  returns_5: [{df['returns_5'].min():.4f}, {df['returns_5'].max():.4f}]")
    print(
        f"  volatility_5: [{df['volatility_5'].min():.4f}, {df['volatility_5'].max():.4f}]"
    )
    print(f"  atr: [{df['atr'].min():.4f}, {df['atr'].max():.4f}]")
    print(
        f"  volume_ratio: [{df['volume_ratio'].min():.2f}, {df['volume_ratio'].max():.2f}]"
    )

    print("\n" + "=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    validate()
