#!/usr/bin/env python3
"""Get full R2000 + S&P 500 universe and ensure complete data from 2021-01."""

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def get_sp500_tickers():
    """Get S&P 500 ticker list from Wikipedia."""
    logger.info("Fetching S&P 500 tickers from Wikipedia...")

    try:
        # Read the Wikipedia table
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)

        # The first table contains the current S&P 500 companies
        sp500_df = tables[0]

        # Extract tickers (Symbol column)
        if "Symbol" in sp500_df.columns:
            tickers = sp500_df["Symbol"].dropna().astype(str).str.strip().str.upper()
        else:
            logger.error("Could not find Symbol column in S&P 500 table")
            return set()

        # Clean up tickers (remove any special characters)
        clean_tickers = set()
        for ticker in tickers:
            # Handle special cases like BRK.B, BF.B
            clean_ticker = ticker.replace(".", "-")  # Convert to standard format
            clean_tickers.add(clean_ticker)

        logger.info(f"Found {len(clean_tickers)} S&P 500 tickers")
        return clean_tickers

    except Exception as e:
        logger.error(f"Error fetching S&P 500 tickers: {e}")
        return set()


def get_russell2000_tickers():
    """Get Russell 2000 ticker list from local file."""
    logger.info("Loading Russell 2000 tickers from local file...")

    r2k_file = Path("/home/jacobw/data_download/russell_2000.xlsx")

    if not r2k_file.exists():
        logger.error("Russell 2000 file not found")
        return set()

    try:
        df = pd.read_excel(r2k_file)

        if "Ticker" in df.columns:
            tickers = df["Ticker"].dropna().astype(str).str.strip().str.upper()
            logger.info(f"Found {len(tickers)} Russell 2000 tickers")
            return set(tickers)
        else:
            logger.error("No 'Ticker' column found in Russell 2000 file")
            return set()

    except Exception as e:
        logger.error(f"Error loading Russell 2000 file: {e}")
        return set()


def analyze_current_gold_coverage(universe_tickers):
    """Analyze current gold data coverage for the universe."""
    logger.info("Analyzing current gold data coverage...")

    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    if not gold_root.exists():
        logger.error(f"Gold root not found: {gold_root}")
        return {}

    coverage = {
        "has_data": set(),
        "missing_completely": set(),
        "has_2021_data": set(),
        "missing_2021_data": set(),
        "only_2025_data": set(),
    }

    existing_tickers = set()
    for ticker_dir in gold_root.iterdir():
        if ticker_dir.is_dir():
            existing_tickers.add(ticker_dir.name)

    coverage["has_data"] = universe_tickers & existing_tickers
    coverage["missing_completely"] = universe_tickers - existing_tickers

    # Check for 2021+ data coverage
    for ticker in coverage["has_data"]:
        ticker_path = gold_root / ticker
        year_dirs = [
            d for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()
        ]
        years = sorted([int(d.name) for d in year_dirs])

        if years:
            if min(years) <= 2021:
                coverage["has_2021_data"].add(ticker)
            else:
                coverage["missing_2021_data"].add(ticker)

            if years == [2025]:
                coverage["only_2025_data"].add(ticker)

    # Log summary
    logger.info(f"Universe size: {len(universe_tickers)}")
    logger.info(f"Has some data: {len(coverage['has_data'])}")
    logger.info(f"Missing completely: {len(coverage['missing_completely'])}")
    logger.info(f"Has 2021+ data: {len(coverage['has_2021_data'])}")
    logger.info(f"Missing 2021+ data: {len(coverage['missing_2021_data'])}")
    logger.info(f"Only 2025 data: {len(coverage['only_2025_data'])}")

    return coverage


def create_download_list(coverage):
    """Create list of tickers that need downloading."""
    logger.info("Creating download priority list...")

    # Priority 1: Completely missing tickers
    priority_1 = coverage["missing_completely"]

    # Priority 2: Tickers missing 2021+ data (including 2025-only)
    priority_2 = coverage["missing_2021_data"] | coverage["only_2025_data"]

    download_list = {
        "priority_1_missing": priority_1,
        "priority_2_incomplete": priority_2,
        "total_to_download": priority_1 | priority_2,
    }

    logger.info(f"Priority 1 (missing): {len(priority_1)} tickers")
    logger.info(f"Priority 2 (incomplete): {len(priority_2)} tickers")
    logger.info(f"Total to download: {len(download_list['total_to_download'])} tickers")

    return download_list


def save_universe_files(sp500_tickers, r2k_tickers, coverage, download_list):
    """Save universe and download lists to files."""
    logger.info("Saving universe and download lists...")

    output_dir = Path("/home/jacobw/quantstack/universe_data")
    output_dir.mkdir(exist_ok=True)

    # Combined universe
    full_universe = sp500_tickers | r2k_tickers

    # Save individual lists
    pd.DataFrame({"ticker": sorted(sp500_tickers)}).to_csv(
        output_dir / "sp500_tickers.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(r2k_tickers)}).to_csv(
        output_dir / "russell2000_tickers.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(full_universe)}).to_csv(
        output_dir / "full_universe.csv", index=False
    )

    # Save download lists
    pd.DataFrame({"ticker": sorted(download_list["priority_1_missing"])}).to_csv(
        output_dir / "download_priority_1_missing.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(download_list["priority_2_incomplete"])}).to_csv(
        output_dir / "download_priority_2_incomplete.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(download_list["total_to_download"])}).to_csv(
        output_dir / "download_all_needed.csv", index=False
    )

    # Save coverage analysis
    coverage_summary = {
        "universe_size": len(full_universe),
        "sp500_count": len(sp500_tickers),
        "russell2000_count": len(r2k_tickers),
        "overlap_count": len(sp500_tickers & r2k_tickers),
        "has_data": len(coverage["has_data"]),
        "missing_completely": len(coverage["missing_completely"]),
        "has_2021_data": len(coverage["has_2021_data"]),
        "missing_2021_data": len(coverage["missing_2021_data"]),
        "only_2025_data": len(coverage["only_2025_data"]),
        "total_to_download": len(download_list["total_to_download"]),
    }

    pd.DataFrame([coverage_summary]).to_csv(
        output_dir / "coverage_summary.csv", index=False
    )

    logger.info(f"Files saved to: {output_dir}")

    return coverage_summary


def create_download_config():
    """Create updated download configuration without price filters."""
    logger.info("Creating updated download configuration...")

    config_template = """
# Updated R2K + S&P 500 Download Configuration
# Removes $5-$50 price filter, includes full universe

lookback_years: 4                    # Download from 2021-01
prefilter_frac_min: 0.0             # Remove price filter requirement
month_chunk: "1M"
concurrency: 8

http:
  timeout_sec: 30
  max_retries: 6
  backoff_base_sec: 1.5

paths:
  universe_dir: "/home/jacobw/quantstack/universe_data"
  prefilter_dir: "artefacts/prefilter"
  checkpoints_dir: "artefacts/checkpoints"
  bronze_root: "/home/jacobw/gcs-mount/bronze/stocks/1m"
  silver_root: "/home/jacobw/gcs-mount/silver/stocks/1m"
  gold_root: "/home/jacobw/gcs-mount/gold/stocks/1m"

calendar: "XNYS"
price_band: [0.01, 10000.0]         # Effectively no price filter

polygon:
  api_key_env: "POLYGON_API_KEY"

# Universe configuration
universe:
  include_sp500: true
  include_russell2000: true
  start_date: "2021-01-01"
  end_date: "2025-12-31"
"""

    config_path = Path("/home/jacobw/quantstack/universe_data/download_config.yaml")
    with open(config_path, "w") as f:
        f.write(config_template.strip())

    logger.info(f"Download config saved to: {config_path}")


def main():
    """Main function."""
    logger.info("Starting full universe analysis and download preparation...")

    # Get ticker lists
    sp500_tickers = get_sp500_tickers()
    r2k_tickers = get_russell2000_tickers()

    if not sp500_tickers or not r2k_tickers:
        logger.error("Failed to get ticker lists")
        return

    # Combine universe
    full_universe = sp500_tickers | r2k_tickers
    overlap = sp500_tickers & r2k_tickers

    logger.info(f"S&P 500: {len(sp500_tickers)} tickers")
    logger.info(f"Russell 2000: {len(r2k_tickers)} tickers")
    logger.info(f"Overlap: {len(overlap)} tickers")
    logger.info(f"Combined universe: {len(full_universe)} tickers")

    # Analyze current coverage
    coverage = analyze_current_gold_coverage(full_universe)

    # Create download list
    download_list = create_download_list(coverage)

    # Save all files
    summary = save_universe_files(sp500_tickers, r2k_tickers, coverage, download_list)

    # Create download config
    create_download_config()

    # Print summary
    logger.info("\n=== UNIVERSE ANALYSIS SUMMARY ===")
    for key, value in summary.items():
        logger.info(f"{key}: {value}")

    logger.info("\n=== NEXT STEPS ===")
    logger.info("1. Review files in /home/jacobw/quantstack/universe_data/")
    logger.info("2. Use download_all_needed.csv for missing tickers")
    logger.info("3. Update data_download configuration to use new universe")
    logger.info("4. Run download for missing/incomplete tickers")
    logger.info("5. Remove 2025-only data after backfill complete")


if __name__ == "__main__":
    main()
