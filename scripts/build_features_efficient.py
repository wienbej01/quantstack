#!/usr/bin/env python3
"""Efficient improved feature builder - processes in batches."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def process_existing_features():
    """Use existing features as base and add improvements."""

    logging.info("EFFICIENT IMPROVED FEATURES")

    # Load existing features
    existing_path = Path("run/intraday_features_rolling/features.parquet")
    if not existing_path.exists():
        logging.error("Existing features not found")
        return False

    output_dir = Path("run/intraday_features_improved")
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Loading existing features...")
    df = pl.read_parquet(existing_path)
    logging.info(f"Loaded {len(df):,} rows")

    # Convert to pandas for processing
    pdf = df.to_pandas()

    # Process in batches by month to avoid memory issues
    all_improved = []

    for month, month_df in pdf.groupby(pd.to_datetime(pdf["date"]).dt.to_period("M")):
        logging.info(f"Processing {month}: {len(month_df):,} rows")

        try:
            # Add improved features
            month_df = add_improved_features(month_df)
            all_improved.append(month_df)

        except Exception as e:
            logging.error(f"Error processing {month}: {e}")
            continue

    if not all_improved:
        logging.error("No improved features generated")
        return False

    # Combine and save
    logging.info("Combining results...")
    combined_df = pd.concat(all_improved, ignore_index=True)

    output_path = output_dir / "features.parquet"
    combined_df.to_parquet(output_path, index=False)

    logging.info("=" * 60)
    logging.info("IMPROVED FEATURES COMPLETE")
    logging.info("=" * 60)
    logging.info(f"Rows: {len(combined_df):,}")
    logging.info(f"Symbols: {combined_df['symbol'].nunique()}")
    logging.info(
        f"Date range: {combined_df['date'].min()} to {combined_df['date'].max()}"
    )

    # Label comparison
    if "label_long_atr" in combined_df.columns:
        orig_long = combined_df["label_long"].mean() * 100
        atr_long = combined_df["label_long_atr"].mean() * 100
        logging.info(
            f"Labels - Original Long: {orig_long:.2f}%, ATR Long: {atr_long:.2f}%"
        )

    logging.info(f"Output: {output_path}")
    return True


def add_improved_features(df):
    """Add improved features to dataframe."""

    # Process by symbol-date
    improved_groups = []

    for (symbol, date), group in df.groupby(["symbol", "date"]):
        if len(group) < 50:
            continue

        try:
            group = group.sort_values("timestamp").copy()

            # Previous close (simplified)
            group["prev_close"] = group["close"].iloc[0]

            # ATR calculation
            group["tr"] = np.maximum(
                group["high"] - group["low"],
                np.maximum(
                    abs(group["high"] - group["prev_close"]),
                    abs(group["low"] - group["prev_close"]),
                ),
            )
            group["atr"] = group["tr"].rolling(14, min_periods=1).mean()

            # Improved relative features
            group["gap_pct"] = (group["open"] - group["prev_close"]) / group[
                "prev_close"
            ]
            group["price_vs_open"] = (group["close"] - group["open"]) / group["open"]
            group["atr_pct"] = group["atr"] / group["close"]

            # Time features
            group["hour"] = pd.to_datetime(group["timestamp"]).dt.hour
            group["is_morning"] = (group["hour"] < 12).astype(int)

            # ATR-normalized labels
            group["forward_return"] = group["close"].pct_change(-5)
            group["atr_threshold"] = group["atr"] / group["close"] * 1.5
            group["label_long_atr"] = (
                group["forward_return"] > group["atr_threshold"]
            ).astype(int)
            group["label_short_atr"] = (
                group["forward_return"] < -group["atr_threshold"]
            ).astype(int)

            improved_groups.append(group)

        except Exception as e:
            logging.warning(f"Error processing {symbol} {date}: {e}")
            continue

    if improved_groups:
        return pd.concat(improved_groups, ignore_index=True)
    else:
        return pd.DataFrame()


if __name__ == "__main__":
    success = process_existing_features()
    if not success:
        exit(1)
