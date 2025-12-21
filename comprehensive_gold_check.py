#!/usr/bin/env python3
"""Comprehensive gold data validation."""

import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def comprehensive_check():
    """Comprehensive validation of gold data."""
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    stats = {
        "total_tickers": 0,
        "proper_structure": 0,
        "flat_structure": 0,
        "timezone_clean": 0,
        "timezone_issues": 0,
        "column_consistent": 0,
        "column_issues": 0,
        "years_coverage": defaultdict(int),
        "sample_errors": [],
    }

    expected_columns = ["ts", "open", "high", "low", "close", "volume", "bar_index"]

    logger.info("Running comprehensive gold data validation...")

    for ticker_dir in gold_root.iterdir():
        if not ticker_dir.is_dir():
            continue

        ticker = ticker_dir.name
        stats["total_tickers"] += 1

        if stats["total_tickers"] % 100 == 0:
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

        # Sample one file for detailed checks
        sample_file = None
        for year_dir in year_dirs:
            files = list(year_dir.glob("*.parquet"))
            if files:
                sample_file = files[0]
                break

        if sample_file:
            try:
                df = pd.read_parquet(sample_file)

                # Check timezone
                if "ts" in df.columns:
                    has_tz = df["ts"].dt.tz is not None
                    if has_tz:
                        stats["timezone_issues"] += 1
                    else:
                        stats["timezone_clean"] += 1

                # Check columns
                has_expected = all(col in df.columns for col in expected_columns)
                if has_expected:
                    stats["column_consistent"] += 1
                else:
                    stats["column_issues"] += 1

            except Exception as e:
                stats["sample_errors"].append(f"{ticker}: {str(e)}")

    # Report results
    logger.info(f"\n=== COMPREHENSIVE VALIDATION RESULTS ===")
    logger.info(f"Total tickers: {stats['total_tickers']}")

    logger.info(f"\nFile Structure:")
    logger.info(f"  Proper structure (year subdirs): {stats['proper_structure']}")
    logger.info(f"  Flat structure (files in root): {stats['flat_structure']}")

    logger.info(f"\nTimezone Format:")
    logger.info(f"  Clean (no timezone info): {stats['timezone_clean']}")
    logger.info(f"  Issues (has timezone info): {stats['timezone_issues']}")

    logger.info(f"\nColumn Consistency:")
    logger.info(f"  Consistent columns: {stats['column_consistent']}")
    logger.info(f"  Column issues: {stats['column_issues']}")

    logger.info(f"\nYear Coverage:")
    for year in sorted(stats["years_coverage"].keys()):
        logger.info(f"  {year}: {stats['years_coverage'][year]} tickers")

    if stats["sample_errors"]:
        logger.info(f"\nSample Errors ({len(stats['sample_errors'])}):")
        for error in stats["sample_errors"][:5]:
            logger.info(f"  {error}")
        if len(stats["sample_errors"]) > 5:
            logger.info(f"  ... and {len(stats['sample_errors']) - 5} more")

    # Calculate percentages
    if stats["total_tickers"] > 0:
        structure_pct = (stats["proper_structure"] / stats["total_tickers"]) * 100
        timezone_pct = (stats["timezone_clean"] / stats["total_tickers"]) * 100
        column_pct = (stats["column_consistent"] / stats["total_tickers"]) * 100

        logger.info(f"\n=== QUALITY METRICS ===")
        logger.info(f"Proper structure: {structure_pct:.1f}%")
        logger.info(f"Clean timezone: {timezone_pct:.1f}%")
        logger.info(f"Consistent columns: {column_pct:.1f}%")

        overall_quality = min(structure_pct, timezone_pct, column_pct)
        logger.info(f"Overall quality: {overall_quality:.1f}%")

        if overall_quality >= 95:
            logger.info("✅ EXCELLENT - Data is highly consistent")
        elif overall_quality >= 85:
            logger.info("✅ GOOD - Data is mostly consistent")
        elif overall_quality >= 70:
            logger.info("⚠️  FAIR - Some consistency issues")
        else:
            logger.info("❌ POOR - Significant consistency issues")

    return stats


if __name__ == "__main__":
    results = comprehensive_check()
