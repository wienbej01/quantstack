#!/usr/bin/env python3
"""Analyze gold data issues: structure, filtering, and timezone consistency."""

import logging
import os
from collections import defaultdict
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def analyze_gold_structure():
    """Analyze gold folder structure and identify issues."""
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    if not gold_root.exists():
        logger.error(f"Gold root not found: {gold_root}")
        return

    # 1. Check folder structure consistency
    logger.info("=== FOLDER STRUCTURE ANALYSIS ===")

    flat_structure = []
    hierarchical_structure = []
    tickers_2025_only = []
    timezone_issues = []

    for ticker_dir in gold_root.iterdir():
        if not ticker_dir.is_dir():
            continue

        ticker = ticker_dir.name

        # Check if files are directly in ticker dir (flat) vs year subdirs (hierarchical)
        parquet_files = list(ticker_dir.glob("*.parquet"))
        year_dirs = [d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()]

        if parquet_files:
            flat_structure.append(ticker)
        elif year_dirs:
            hierarchical_structure.append(ticker)

            # Check for 2025-only data
            years = [int(d.name) for d in year_dirs]
            if years == [2025]:
                tickers_2025_only.append(ticker)

    logger.info(f"Flat structure tickers: {len(flat_structure)}")
    if flat_structure[:5]:
        logger.info(f"  Examples: {flat_structure[:5]}")

    logger.info(f"Hierarchical structure tickers: {len(hierarchical_structure)}")
    if hierarchical_structure[:5]:
        logger.info(f"  Examples: {hierarchical_structure[:5]}")

    logger.info(f"Tickers with 2025 data only: {len(tickers_2025_only)}")
    if tickers_2025_only[:10]:
        logger.info(f"  Examples: {tickers_2025_only[:10]}")

    # 2. Check Russell 2000 filtering
    logger.info("\n=== RUSSELL 2000 FILTERING ANALYSIS ===")

    r2k_file = Path("/home/jacobw/data_download/russell_2000.xlsx")
    if r2k_file.exists():
        try:
            r2k_df = pd.read_excel(r2k_file)
            if "Ticker" in r2k_df.columns:
                r2k_tickers = set(r2k_df["Ticker"].str.upper())
                logger.info(f"Russell 2000 tickers loaded: {len(r2k_tickers)}")

                gold_tickers = set(d.name for d in gold_root.iterdir() if d.is_dir())
                logger.info(f"Gold tickers found: {len(gold_tickers)}")

                not_in_r2k = gold_tickers - r2k_tickers
                logger.info(f"Gold tickers NOT in Russell 2000: {len(not_in_r2k)}")
                if not_in_r2k:
                    logger.info(f"  Examples: {list(not_in_r2k)[:10]}")

                r2k_missing = r2k_tickers - gold_tickers
                logger.info(
                    f"Russell 2000 tickers missing from gold: {len(r2k_missing)}"
                )

        except Exception as e:
            logger.error(f"Error reading Russell 2000 file: {e}")

    # 3. Check timezone consistency
    logger.info("\n=== TIMEZONE CONSISTENCY ANALYSIS ===")

    sample_files = []
    for ticker_dir in list(gold_root.iterdir())[:5]:
        if ticker_dir.is_dir():
            for year_dir in ticker_dir.iterdir():
                if year_dir.is_dir():
                    parquet_files = list(year_dir.glob("*.parquet"))
                    if parquet_files:
                        sample_files.append(parquet_files[0])
                        break

    for file_path in sample_files:
        try:
            df = pd.read_parquet(file_path)
            if "ts" in df.columns:
                tz_info = df["ts"].dt.tz
                sample_ts = df["ts"].iloc[0] if len(df) > 0 else None
                logger.info(
                    f"{file_path.parent.parent.name}/{file_path.parent.name}: tz={tz_info}, sample={sample_ts}"
                )

                if tz_info is not None:
                    timezone_issues.append(str(file_path))
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")

    # 4. Check price range filtering
    logger.info("\n=== PRICE RANGE ANALYSIS ===")

    price_violations = []
    for ticker_dir in list(gold_root.iterdir())[:10]:  # Sample first 10
        if not ticker_dir.is_dir():
            continue

        ticker = ticker_dir.name
        try:
            # Get latest available data
            year_dirs = sorted(
                [d for d in ticker_dir.iterdir() if d.is_dir() and d.name.isdigit()]
            )
            if not year_dirs:
                continue

            latest_year = year_dirs[-1]
            parquet_files = list(latest_year.glob("*.parquet"))
            if not parquet_files:
                continue

            df = pd.read_parquet(parquet_files[-1])  # Latest month
            if "close" in df.columns and len(df) > 0:
                min_price = df["close"].min()
                max_price = df["close"].max()

                # Check if outside $5-$50 range
                if min_price < 5.0 or max_price > 50.0:
                    price_violations.append(
                        {
                            "ticker": ticker,
                            "min_price": min_price,
                            "max_price": max_price,
                        }
                    )

        except Exception as e:
            logger.error(f"Error analyzing prices for {ticker}: {e}")

    if price_violations:
        logger.info(f"Tickers outside $5-$50 range (sample): {len(price_violations)}")
        for violation in price_violations[:5]:
            logger.info(
                f"  {violation['ticker']}: ${violation['min_price']:.2f} - ${violation['max_price']:.2f}"
            )

    # Summary
    logger.info("\n=== SUMMARY ===")
    logger.info(f"Issues found:")
    logger.info(f"  - Flat structure tickers: {len(flat_structure)}")
    logger.info(f"  - 2025-only tickers: {len(tickers_2025_only)}")
    logger.info(f"  - Timezone issues: {len(timezone_issues)}")
    logger.info(f"  - Price violations (sample): {len(price_violations)}")

    return {
        "flat_structure": flat_structure,
        "tickers_2025_only": tickers_2025_only,
        "timezone_issues": timezone_issues,
        "price_violations": price_violations,
    }


def check_download_config():
    """Check current download configuration."""
    logger.info("\n=== DOWNLOAD CONFIGURATION ===")

    config_file = Path("/home/jacobw/data_download/configs/config.yaml")
    if config_file.exists():
        try:
            import yaml

            with open(config_file) as f:
                config = yaml.safe_load(f)

            logger.info(f"Price band: {config.get('price_band', 'NOT SET')}")
            logger.info(
                f"Prefilter fraction min: {config.get('prefilter_frac_min', 'NOT SET')}"
            )

        except Exception as e:
            logger.error(f"Error reading config: {e}")


if __name__ == "__main__":
    logger.info("Starting gold data analysis...")

    issues = analyze_gold_structure()
    check_download_config()

    logger.info("\nAnalysis complete. Review issues above.")
