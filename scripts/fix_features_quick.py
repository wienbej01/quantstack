#!/usr/bin/env python3
"""Quick fix for existing features."""

import logging
from pathlib import Path

import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("QUICK FIX: Cleaning existing features")

    features_path = Path("run/intraday_features_fixed/features.parquet")
    df = pl.read_parquet(features_path)

    # Remove remaining raw price features
    cols_to_drop = [
        "first_open",
        "prev_session_close",
        "volume",
        "cum_volume",
        "cum_dollar_vol",
    ]
    existing_cols = [c for c in cols_to_drop if c in df.columns]

    if existing_cols:
        logging.info(f"Dropping columns: {existing_cols}")
        df = df.drop(existing_cols)

    # Save fixed features
    df.write_parquet(features_path)
    logging.info(f"Fixed features saved: {len(df):,} rows, {len(df.columns)} columns")

    return True


if __name__ == "__main__":
    main()
