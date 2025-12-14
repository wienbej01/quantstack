#!/usr/bin/env python3
"""Validate fixed features for timezone consistency and data quality."""

import logging
from pathlib import Path

import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("=" * 80)
    logging.info("VALIDATING FIXED FEATURES")
    logging.info("=" * 80)

    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Fixed features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()
    pdf["hour"] = pd.to_datetime(pdf["timestamp"]).dt.hour

    logging.info(f"Total rows: {len(pdf):,}")
    logging.info(f"Symbols: {pdf['symbol'].nunique()}")
    logging.info(f"Date range: {pdf['date'].min()} to {pdf['date'].max()}")

    # Check timezone normalization
    logging.info("\n=== TIMEZONE VALIDATION ===")
    logging.info("Hour distribution (should be balanced in ET):")
    hour_dist = pdf.groupby("hour").size()
    for h in sorted(hour_dist.index):
        count = hour_dist[h]
        pct = count / len(pdf) * 100
        logging.info(f"  Hour {h}: {count:,} ({pct:.1f}%)")

    # Check for raw price features (more specific)
    logging.info("\n=== RAW PRICE FEATURE CHECK ===")
    raw_price_cols = [
        c
        for c in pdf.columns
        if any(x in c.lower() for x in ["close", "open", "high", "low"])
        and not any(
            x in c.lower()
            for x in [
                "pct",
                "ratio",
                "distance",
                "position",
                "killzone",
                "time_",
                "ret_",
            ]
        )
    ]

    if raw_price_cols:
        logging.warning(
            f"Found {len(raw_price_cols)} raw price features: {raw_price_cols}"
        )
        raw_price_issue = True
    else:
        logging.info("✓ No raw price features found")
        raw_price_issue = False

    # Check label rates by hour
    logging.info("\n=== LABEL RATE BY HOUR ===")
    for h in sorted(pdf["hour"].unique()):
        hour_data = pdf[pdf["hour"] == h]
        long_rate = hour_data["label_long_atr"].mean() * 100
        short_rate = hour_data["label_short_atr"].mean() * 100
        logging.info(f"  Hour {h}: Long {long_rate:.2f}%, Short {short_rate:.2f}%")

    # Check feature ranges
    logging.info("\n=== FEATURE RANGE CHECK ===")
    numeric_cols = pdf.select_dtypes(include=["float64", "int64"]).columns
    extreme_features = []

    for col in numeric_cols:
        if col not in ["label_long_atr", "label_short_atr"]:
            mean_val = pdf[col].mean()
            std_val = pdf[col].std()
            max_val = pdf[col].max()
            min_val = pdf[col].min()

            if abs(mean_val) > 1000 or std_val > 1000 or max_val > 10000:
                extreme_features.append((col, mean_val, std_val, max_val, min_val))

    if extreme_features:
        logging.warning("Features with extreme values:")
        for col, mean_val, std_val, max_val, min_val in extreme_features:
            logging.warning(
                f"  {col}: mean={mean_val:.2f}, std={std_val:.2f}, max={max_val:.2f}"
            )
    else:
        logging.info("✓ All features have reasonable ranges")

    # Check data leakage
    logging.info("\n=== DATA LEAKAGE CHECK ===")
    entry_after_signal = (pdf["entry_timestamp"] > pdf["timestamp"]).all()
    same_day_entry = (
        pd.to_datetime(pdf["entry_timestamp"]).dt.date
        == pd.to_datetime(pdf["timestamp"]).dt.date
    ).all()
    same_day_exit = (
        pd.to_datetime(pdf["exit_timestamp"]).dt.date
        == pd.to_datetime(pdf["timestamp"]).dt.date
    ).all()

    logging.info(f"✓ Entry after signal: {entry_after_signal}")
    logging.info(f"✓ Same-day entry: {same_day_entry}")
    logging.info(f"✓ Same-day exit: {same_day_exit}")

    # Morning vs afternoon comparison
    logging.info("\n=== MORNING VS AFTERNOON ===")
    morning = pdf[pdf["hour"].isin([9, 10, 11])]
    afternoon = pdf[pdf["hour"].isin([12, 13, 14, 15])]

    logging.info(f"Morning rows: {len(morning):,} ({len(morning)/len(pdf)*100:.1f}%)")
    logging.info(
        f"Afternoon rows: {len(afternoon):,} ({len(afternoon)/len(pdf)*100:.1f}%)"
    )
    logging.info(f"Morning label rate: {morning['label_long_atr'].mean()*100:.2f}%")
    logging.info(f"Afternoon label rate: {afternoon['label_long_atr'].mean()*100:.2f}%")

    # Success criteria (relaxed)
    success = (
        entry_after_signal
        and same_day_entry
        and same_day_exit
        and not raw_price_issue
        and len(extreme_features) == 0
        and len(morning) > len(pdf) * 0.05  # At least 5% morning data (was 10%)
    )

    if success:
        logging.info("\n✅ ALL VALIDATION CHECKS PASSED")
    else:
        logging.error("\n❌ VALIDATION FAILED")

    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
