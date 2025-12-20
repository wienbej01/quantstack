#!/usr/bin/env python3
"""Fix gold data issues: remove 2025-only tickers, apply R2K filtering, normalize timezone."""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def load_russell_2000_tickers():
    """Load Russell 2000 ticker list."""
    r2k_file = Path("/home/jacobw/data_download/russell_2000.xlsx")

    if not r2k_file.exists():
        logger.warning("Russell 2000 file not found, skipping R2K filtering")
        return None

    try:
        # Try different sheet names and column names
        for sheet in [0, "Sheet1", "Russell 2000"]:
            try:
                df = pd.read_excel(r2k_file, sheet_name=sheet)
                break
            except:
                continue

        # Find ticker column
        ticker_col = None
        for col in ["Ticker", "ticker", "Symbol", "symbol", "TICKER"]:
            if col in df.columns:
                ticker_col = col
                break

        if ticker_col is None:
            logger.error("No ticker column found in Russell 2000 file")
            return None

        tickers = set(df[ticker_col].dropna().astype(str).str.strip().str.upper())
        logger.info(f"Loaded {len(tickers)} Russell 2000 tickers")
        return tickers

    except Exception as e:
        logger.error(f"Error loading Russell 2000 file: {e}")
        return None


def apply_price_filter(ticker_path, price_range=(5.0, 50.0)):
    """Check if ticker meets price range criteria."""
    try:
        # Check latest available data
        year_dirs = sorted(
            [d for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()]
        )
        if not year_dirs:
            return False

        # Sample from multiple recent months
        sample_files = []
        for year_dir in year_dirs[-2:]:  # Last 2 years
            parquet_files = sorted(year_dir.glob("*.parquet"))
            if parquet_files:
                sample_files.extend(parquet_files[-3:])  # Last 3 months per year

        if not sample_files:
            return False

        total_days = 0
        days_in_range = 0

        for file_path in sample_files:
            try:
                df = pd.read_parquet(file_path)
                if "close" not in df.columns or len(df) == 0:
                    continue

                # Count trading days
                daily_closes = df.groupby(df["ts"].dt.date)["close"].last()
                total_days += len(daily_closes)

                # Count days in price range
                in_range = (
                    (daily_closes >= price_range[0]) & (daily_closes <= price_range[1])
                ).sum()
                days_in_range += in_range

            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                continue

        if total_days == 0:
            return False

        fraction_in_range = days_in_range / total_days
        return fraction_in_range >= 0.1  # 10% threshold

    except Exception as e:
        logger.error(f"Error applying price filter to {ticker_path}: {e}")
        return False


def fix_timezone_format(file_path):
    """Fix timezone format in parquet file."""
    try:
        df = pd.read_parquet(file_path)

        if "ts" not in df.columns:
            return False

        # Check if timezone info exists
        if df["ts"].dt.tz is not None:
            logger.info(f"Fixing timezone for {file_path}")

            # Convert to naive datetime (should already be ET)
            df["ts"] = df["ts"].dt.tz_localize(None)

            # Save back
            temp_path = str(file_path) + ".tmp"
            df.to_parquet(temp_path, index=False)
            os.replace(temp_path, file_path)
            return True

        return False

    except Exception as e:
        logger.error(f"Error fixing timezone for {file_path}: {e}")
        return False


def main():
    """Main fix function."""
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    if not gold_root.exists():
        logger.error(f"Gold root not found: {gold_root}")
        return

    # Load Russell 2000 tickers
    r2k_tickers = load_russell_2000_tickers()

    # Statistics
    stats = {
        "total_tickers": 0,
        "removed_2025_only": 0,
        "removed_not_r2k": 0,
        "removed_price_filter": 0,
        "timezone_fixes": 0,
        "kept_tickers": 0,
    }

    logger.info("Starting gold data cleanup...")

    for ticker_dir in gold_root.iterdir():
        if not ticker_dir.is_dir():
            continue

        ticker = ticker_dir.name
        stats["total_tickers"] += 1

        if stats["total_tickers"] % 100 == 0:
            logger.info(f"Processed {stats['total_tickers']} tickers...")

        # Check year structure
        year_dirs = [d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        years = [int(d.name) for d in year_dirs]

        should_remove = False
        removal_reason = ""

        # 1. Remove tickers with only 2025 data
        if years == [2025]:
            should_remove = True
            removal_reason = "2025-only data"
            stats["removed_2025_only"] += 1

        # 2. Remove tickers not in Russell 2000 (if available)
        elif r2k_tickers and ticker not in r2k_tickers:
            should_remove = True
            removal_reason = "not in Russell 2000"
            stats["removed_not_r2k"] += 1

        # 3. Apply price filter
        elif not apply_price_filter(ticker_dir):
            should_remove = True
            removal_reason = "price filter (<10% days in $5-$50 range)"
            stats["removed_price_filter"] += 1

        if should_remove:
            logger.info(f"Removing {ticker}: {removal_reason}")
            try:
                shutil.rmtree(ticker_dir)
            except Exception as e:
                logger.error(f"Error removing {ticker_dir}: {e}")
        else:
            # Keep ticker, fix timezone issues
            stats["kept_tickers"] += 1

            # Fix timezone format in all files
            for year_dir in year_dirs:
                for parquet_file in year_dir.glob("*.parquet"):
                    if fix_timezone_format(parquet_file):
                        stats["timezone_fixes"] += 1

    # Summary
    logger.info("\n=== CLEANUP SUMMARY ===")
    logger.info(f"Total tickers processed: {stats['total_tickers']}")
    logger.info(f"Removed - 2025-only data: {stats['removed_2025_only']}")
    logger.info(f"Removed - not in Russell 2000: {stats['removed_not_r2k']}")
    logger.info(f"Removed - price filter: {stats['removed_price_filter']}")
    logger.info(f"Timezone fixes applied: {stats['timezone_fixes']}")
    logger.info(f"Tickers kept: {stats['kept_tickers']}")

    total_removed = (
        stats["removed_2025_only"]
        + stats["removed_not_r2k"]
        + stats["removed_price_filter"]
    )
    logger.info(f"Total removed: {total_removed}")

    # Verify final state
    remaining_tickers = len([d for d in gold_root.iterdir() if d.is_dir()])
    logger.info(f"Remaining tickers in gold: {remaining_tickers}")


if __name__ == "__main__":
    # Confirm before running
    response = input("This will permanently remove ticker data. Continue? (yes/no): ")
    if response.lower() != "yes":
        logger.info("Aborted by user")
        exit(0)

    main()
    logger.info("Gold data cleanup complete!")
