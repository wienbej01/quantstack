#!/usr/bin/env python3
"""Check bronze data consistency and identify protocol violations."""

import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def check_bronze_consistency():
    """Check bronze data for protocol compliance."""
    bronze_root = Path("/home/jacobw/gcs-mount/bronze/stocks/1m")

    stats = {
        "total_tickers": 0,
        "proper_structure": 0,
        "flat_structure": 0,
        "column_formats": defaultdict(int),
        "timezone_formats": defaultdict(int),
        "sample_errors": [],
        "years_coverage": defaultdict(int),
    }

    logger.info("Checking bronze data consistency...")

    for ticker_dir in bronze_root.iterdir():
        if not ticker_dir.is_dir():
            continue

        ticker = ticker_dir.name
        stats["total_tickers"] += 1

        if stats["total_tickers"] % 200 == 0:
            logger.info(f"Checked {stats['total_tickers']} tickers...")

        # Check structure
        year_dirs = [d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        parquet_files = list(ticker_dir.glob("*.parquet"))

        if parquet_files:
            stats["flat_structure"] += 1
        else:
            stats["proper_structure"] += 1

        # Track year coverage
        for year_dir in year_dirs:
            stats["years_coverage"][year_dir.name] += 1

        # Sample one file for column/timezone checks
        sample_file = None
        for year_dir in year_dirs:
            files = list(year_dir.glob("*.parquet"))
            if files:
                sample_file = files[0]
                break

        if sample_file:
            try:
                df = pd.read_parquet(sample_file)

                # Check column format
                columns_key = tuple(sorted(df.columns))
                stats["column_formats"][columns_key] += 1

                # Check timestamp column and timezone
                ts_cols = [
                    col
                    for col in df.columns
                    if col in ["t", "ts", "ts_ms", "timestamp"]
                ]
                if ts_cols:
                    ts_col = ts_cols[0]
                    ts_dtype = str(df[ts_col].dtype)

                    if "datetime" in ts_dtype:
                        has_tz = df[ts_col].dt.tz is not None
                        tz_info = str(df[ts_col].dt.tz) if has_tz else "None"
                        stats["timezone_formats"][
                            f"{ts_col}:{ts_dtype}:tz={tz_info}"
                        ] += 1
                    else:
                        stats["timezone_formats"][f"{ts_col}:{ts_dtype}"] += 1

            except Exception as e:
                stats["sample_errors"].append(f"{ticker}: {str(e)}")
                if len(stats["sample_errors"]) > 20:  # Limit error collection
                    break

    # Report results
    logger.info(f"\n=== BRONZE CONSISTENCY RESULTS ===")
    logger.info(f"Total tickers: {stats['total_tickers']}")

    logger.info(f"\nFile Structure:")
    logger.info(f"  Proper structure: {stats['proper_structure']}")
    logger.info(f"  Flat structure: {stats['flat_structure']}")

    logger.info(f"\nColumn Formats (top 5):")
    for cols, count in sorted(
        stats["column_formats"].items(), key=lambda x: x[1], reverse=True
    )[:5]:
        logger.info(f"  {count} files: {list(cols)}")

    logger.info(f"\nTimezone Formats:")
    for tz_format, count in sorted(
        stats["timezone_formats"].items(), key=lambda x: x[1], reverse=True
    ):
        logger.info(f"  {count} files: {tz_format}")

    logger.info(f"\nYear Coverage:")
    for year in sorted(stats["years_coverage"].keys()):
        logger.info(f"  {year}: {stats['years_coverage'][year]} tickers")

    if stats["sample_errors"]:
        logger.info(f"\nSample Errors ({len(stats['sample_errors'])}):")
        for error in stats["sample_errors"][:5]:
            logger.info(f"  {error}")

    return stats


if __name__ == "__main__":
    results = check_bronze_consistency()
