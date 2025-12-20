#!/usr/bin/env python3
"""Fast migration with progress tracking and skipping existing files."""

import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def convert_bronze_to_gold_fast(bronze_df):
    """Fast bronze to gold conversion."""
    if bronze_df.empty:
        return pd.DataFrame()

    # Column mapping
    col_map = {
        "t": "ts_ms",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "vw": "vwap",
        "n": "trades",
    }
    bronze_df = bronze_df.rename(columns=col_map)

    # Sort by timestamp
    bronze_df = bronze_df.sort_values("ts_ms").reset_index(drop=True)

    # Create gold DataFrame with minimal calculations
    gold_df = pd.DataFrame(
        {
            "ts": pd.to_datetime(bronze_df["ts_ms"], unit="ms", utc=True)
            .dt.tz_convert("US/Eastern")
            .dt.tz_localize(None),
            "open": bronze_df["open"].astype("float64"),
            "high": bronze_df["high"].astype("float64"),
            "low": bronze_df["low"].astype("float64"),
            "close": bronze_df["close"].astype("float64"),
            "volume": bronze_df["volume"].astype("float64"),
            "bar_index": range(len(bronze_df)),
            "ret_1m": bronze_df["close"].pct_change().fillna(0.0),
            "session_id": 1,  # Simplified
            "is_first_bar": False,
            "is_last_bar": False,
        }
    )

    # Mark first and last bars
    if len(gold_df) > 0:
        gold_df.iloc[0, gold_df.columns.get_loc("is_first_bar")] = True
        gold_df.iloc[-1, gold_df.columns.get_loc("is_last_bar")] = True

    return gold_df


def process_single_file(bronze_path, gold_path):
    """Process a single bronze file to gold."""
    try:
        if os.path.exists(gold_path):
            return "skipped"

        bronze_df = pd.read_parquet(bronze_path)
        if bronze_df.empty:
            return "empty"

        gold_df = convert_bronze_to_gold_fast(bronze_df)
        if gold_df.empty:
            return "empty"

        os.makedirs(os.path.dirname(gold_path), exist_ok=True)
        gold_df.to_parquet(gold_path, index=False)
        return "success"

    except Exception as e:
        logger.error(f"Error processing {bronze_path}: {e}")
        return "failed"


def main():
    """Main fast migration."""
    bronze_root = Path("/home/jacobw/gcs-mount/bronze/stocks/1m")
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    logger.info("Starting fast migration...")

    stats = {"success": 0, "skipped": 0, "failed": 0, "empty": 0}
    start_time = time.time()

    # Get all bronze files
    bronze_files = list(bronze_root.rglob("*.parquet"))
    total_files = len(bronze_files)
    logger.info(f"Found {total_files} bronze files to process")

    for i, bronze_path in enumerate(bronze_files):
        if i % 1000 == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            logger.info(
                f"Progress: {i}/{total_files} ({i/total_files*100:.1f}%) - {rate:.1f} files/sec"
            )

        # Build gold path
        rel_path = bronze_path.relative_to(bronze_root)
        parts = rel_path.parts

        if len(parts) >= 3:  # ticker/year/file
            ticker, year, filename = parts[0], parts[1], parts[2]

            # Convert filename format
            if "_" in filename:
                gold_filename = filename.split("_", 1)[1]  # Remove ticker prefix
            else:
                gold_filename = filename

            gold_path = gold_root / ticker / year / gold_filename

            result = process_single_file(bronze_path, gold_path)
            stats[result] += 1

    elapsed = time.time() - start_time
    logger.info(f"Migration complete in {elapsed/60:.1f} minutes")
    logger.info(f"Results: {stats}")


if __name__ == "__main__":
    main()
