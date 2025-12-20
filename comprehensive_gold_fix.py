#!/usr/bin/env python3
"""Comprehensive fix for gold data issues identified in analysis."""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


class GoldDataFixer:
    def __init__(self, gold_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
        self.gold_root = Path(gold_root)
        self.r2k_tickers = None
        self.stats = {
            "total_tickers": 0,
            "removed_2025_only": 0,
            "removed_not_r2k": 0,
            "removed_price_filter": 0,
            "timezone_fixes": 0,
            "kept_tickers": 0,
        }

    def load_russell_2000_tickers(self):
        """Load Russell 2000 ticker list."""
        r2k_file = Path("/home/jacobw/data_download/russell_2000.xlsx")

        if not r2k_file.exists():
            logger.warning("Russell 2000 file not found, skipping R2K filtering")
            return None

        try:
            df = pd.read_excel(r2k_file)
            if "Ticker" in df.columns:
                tickers = set(df["Ticker"].dropna().astype(str).str.strip().str.upper())
                logger.info(f"Loaded {len(tickers)} Russell 2000 tickers")
                self.r2k_tickers = tickers
                return tickers
            else:
                logger.error("No 'Ticker' column found in Russell 2000 file")
                return None

        except Exception as e:
            logger.error(f"Error loading Russell 2000 file: {e}")
            return None

    def check_price_filter(
        self, ticker_path, price_range=(5.0, 50.0), min_fraction=0.1
    ):
        """Check if ticker meets price range criteria."""
        try:
            year_dirs = sorted(
                [d for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()]
            )
            if not year_dirs:
                return False

            # Sample from recent data (avoid 2025-only data)
            valid_years = [d for d in year_dirs if int(d.name) < 2025]
            if not valid_years:
                # If only 2025 data, it will be removed anyway
                return False

            sample_files = []
            for year_dir in valid_years[-2:]:  # Last 2 valid years
                parquet_files = sorted(year_dir.glob("*.parquet"))
                if parquet_files:
                    sample_files.extend(parquet_files[-6:])  # Last 6 months per year

            if not sample_files:
                return False

            total_days = 0
            days_in_range = 0

            for file_path in sample_files[:10]:  # Limit to avoid excessive processing
                try:
                    df = pd.read_parquet(file_path)
                    if "close" not in df.columns or len(df) == 0:
                        continue

                    # Get daily closes (last close per day)
                    daily_closes = df.groupby(df["ts"].dt.date)["close"].last()
                    total_days += len(daily_closes)

                    # Count days in price range
                    in_range = (
                        (daily_closes >= price_range[0])
                        & (daily_closes <= price_range[1])
                    ).sum()
                    days_in_range += in_range

                except Exception as e:
                    logger.debug(f"Error reading {file_path}: {e}")
                    continue

            if total_days == 0:
                return False

            fraction_in_range = days_in_range / total_days
            return fraction_in_range >= min_fraction

        except Exception as e:
            logger.error(f"Error applying price filter to {ticker_path}: {e}")
            return False

    def fix_timezone_format(self, file_path):
        """Fix timezone format in parquet file if needed."""
        try:
            df = pd.read_parquet(file_path)

            if "ts" not in df.columns:
                return False

            # Check if timezone info exists
            if df["ts"].dt.tz is not None:
                logger.debug(f"Fixing timezone for {file_path}")

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

    def process_ticker(self, ticker_dir):
        """Process a single ticker directory."""
        ticker = ticker_dir.name

        # Check year structure
        year_dirs = [d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        years = sorted([int(d.name) for d in year_dirs])

        should_remove = False
        removal_reason = ""

        # 1. Remove tickers with only 2025 data
        if years == [2025]:
            should_remove = True
            removal_reason = "2025-only data"
            self.stats["removed_2025_only"] += 1

        # 2. Remove tickers not in Russell 2000 (if available)
        elif self.r2k_tickers and ticker not in self.r2k_tickers:
            should_remove = True
            removal_reason = "not in Russell 2000"
            self.stats["removed_not_r2k"] += 1

        # 3. Apply price filter (only for tickers with historical data)
        elif not self.check_price_filter(ticker_dir):
            should_remove = True
            removal_reason = "price filter (<10% days in $5-$50 range)"
            self.stats["removed_price_filter"] += 1

        if should_remove:
            logger.info(f"Removing {ticker}: {removal_reason}")
            try:
                shutil.rmtree(ticker_dir)
                return False  # Ticker removed
            except Exception as e:
                logger.error(f"Error removing {ticker_dir}: {e}")
                return False
        else:
            # Keep ticker, fix timezone issues
            self.stats["kept_tickers"] += 1

            # Fix timezone format in all files
            timezone_fixes = 0
            for year_dir in year_dirs:
                year_path = ticker_dir / year_dir.name
                for parquet_file in year_path.glob("*.parquet"):
                    if self.fix_timezone_format(parquet_file):
                        timezone_fixes += 1

            if timezone_fixes > 0:
                self.stats["timezone_fixes"] += timezone_fixes
                logger.debug(f"Fixed {timezone_fixes} timezone issues in {ticker}")

            return True  # Ticker kept

    def run_fix(self, dry_run=False):
        """Run the comprehensive fix."""
        if not self.gold_root.exists():
            logger.error(f"Gold root not found: {self.gold_root}")
            return

        logger.info(f"Starting gold data cleanup (dry_run={dry_run})...")

        # Load Russell 2000 tickers
        self.load_russell_2000_tickers()

        # Get all ticker directories
        ticker_dirs = [d for d in self.gold_root.iterdir() if d.is_dir()]
        self.stats["total_tickers"] = len(ticker_dirs)

        logger.info(f"Found {self.stats['total_tickers']} ticker directories")

        # Process each ticker
        for i, ticker_dir in enumerate(ticker_dirs):
            if (i + 1) % 100 == 0:
                logger.info(
                    f"Processed {i + 1}/{self.stats['total_tickers']} tickers..."
                )

            if not dry_run:
                self.process_ticker(ticker_dir)
            else:
                # Dry run - just analyze
                ticker = ticker_dir.name
                year_dirs = [
                    d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()
                ]
                years = sorted([int(d.name) for d in year_dirs])

                if years == [2025]:
                    self.stats["removed_2025_only"] += 1
                elif self.r2k_tickers and ticker not in self.r2k_tickers:
                    self.stats["removed_not_r2k"] += 1
                elif not self.check_price_filter(ticker_dir):
                    self.stats["removed_price_filter"] += 1
                else:
                    self.stats["kept_tickers"] += 1

        # Summary
        self.print_summary(dry_run)

        if not dry_run:
            # Verify final state
            remaining_tickers = len([d for d in self.gold_root.iterdir() if d.is_dir()])
            logger.info(f"Remaining tickers in gold: {remaining_tickers}")

    def print_summary(self, dry_run=False):
        """Print cleanup summary."""
        action = "WOULD BE" if dry_run else "ACTUAL"

        logger.info(f"\n=== {action} CLEANUP SUMMARY ===")
        logger.info(f"Total tickers processed: {self.stats['total_tickers']}")
        logger.info(f"Removed - 2025-only data: {self.stats['removed_2025_only']}")
        logger.info(f"Removed - not in Russell 2000: {self.stats['removed_not_r2k']}")
        logger.info(f"Removed - price filter: {self.stats['removed_price_filter']}")

        if not dry_run:
            logger.info(f"Timezone fixes applied: {self.stats['timezone_fixes']}")

        logger.info(f"Tickers kept: {self.stats['kept_tickers']}")

        total_removed = (
            self.stats["removed_2025_only"]
            + self.stats["removed_not_r2k"]
            + self.stats["removed_price_filter"]
        )
        logger.info(f"Total removed: {total_removed}")

        if self.stats["total_tickers"] > 0:
            removal_pct = (total_removed / self.stats["total_tickers"]) * 100
            logger.info(f"Removal percentage: {removal_pct:.1f}%")


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description="Fix gold data issues")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--gold-root",
        default="/home/jacobw/gcs-mount/gold/stocks/1m",
        help="Path to gold data root",
    )

    args = parser.parse_args()

    if not args.dry_run:
        response = input(
            "This will permanently remove ticker data. Continue? (yes/no): "
        )
        if response.lower() != "yes":
            logger.info("Aborted by user")
            return

    fixer = GoldDataFixer(args.gold_root)
    fixer.run_fix(dry_run=args.dry_run)

    if args.dry_run:
        logger.info("\nRun without --dry-run to apply changes")
    else:
        logger.info("Gold data cleanup complete!")


if __name__ == "__main__":
    main()
