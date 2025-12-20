#!/usr/bin/env python3
"""Fix bronze column naming issues for migration."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_bronze_file(file_path):
    """Check bronze file columns and fix if needed."""
    try:
        df = pd.read_parquet(file_path)
        logger.info(f"Columns in {file_path}: {list(df.columns)}")

        # Common column mappings
        column_map = {
            "t": "ts_ms",
            "timestamp": "ts_ms",
            "time": "ts_ms",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "vw": "vwap",
            "n": "trades",
        }

        # Check if we need to rename columns
        needs_fix = False
        for old_col, new_col in column_map.items():
            if old_col in df.columns and new_col not in df.columns:
                needs_fix = True
                break

        if needs_fix:
            logger.info(f"Fixing columns in {file_path}")
            df = df.rename(columns=column_map)
            df.to_parquet(file_path, index=False)
            logger.info(f"Fixed columns: {list(df.columns)}")

        return True

    except Exception as e:
        logger.error(f"Error checking {file_path}: {e}")
        return False


if __name__ == "__main__":
    # Check the specific file mentioned in the error
    problem_file = (
        "/home/jacobw/gcs-mount/bronze/stocks/1m/ABT/2025/ABT_2025-06.parquet"
    )
    check_bronze_file(problem_file)
