#!/usr/bin/env python3
"""Check gold data consistency: file structure and time format."""

import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def check_gold_consistency():
    """Check file structure and time format consistency."""
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    structure_issues = []
    timezone_issues = []
    sample_checks = 0
    max_samples = 50  # Limit samples for speed

    logger.info("Checking gold data consistency...")

    for ticker_dir in gold_root.iterdir():
        if not ticker_dir.is_dir() or sample_checks >= max_samples:
            break

        ticker = ticker_dir.name
        sample_checks += 1

        # Check structure: should have year subdirectories
        year_dirs = [d for d in ticker_dir.iterdir() if d.is_dir()]
        parquet_files = list(ticker_dir.glob("*.parquet"))

        if parquet_files:
            structure_issues.append(
                f"{ticker}: Has flat structure (parquet files in root)"
            )

        if not year_dirs:
            structure_issues.append(f"{ticker}: No year subdirectories found")
            continue

        # Check a sample file from each year
        for year_dir in year_dirs[:2]:  # Check max 2 years per ticker
            year_files = list(year_dir.glob("*.parquet"))
            if not year_files:
                continue

            # Check first file in year
            sample_file = year_files[0]
            try:
                df = pd.read_parquet(sample_file)

                if "ts" in df.columns:
                    # Check timezone info
                    ts_dtype = str(df["ts"].dtype)
                    has_tz = df["ts"].dt.tz is not None

                    if has_tz:
                        timezone_issues.append(
                            f"{ticker}/{year_dir.name}: Has timezone info ({df['ts'].dt.tz})"
                        )

                    # Check sample timestamp format
                    sample_ts = df["ts"].iloc[0] if len(df) > 0 else None
                    logger.debug(
                        f"{ticker}/{year_dir.name}: {ts_dtype}, tz={has_tz}, sample={sample_ts}"
                    )

            except Exception as e:
                logger.error(f"Error reading {sample_file}: {e}")

    # Report results
    logger.info(f"\n=== CONSISTENCY CHECK RESULTS ===")
    logger.info(f"Checked {sample_checks} tickers")

    logger.info(f"\nStructure Issues: {len(structure_issues)}")
    for issue in structure_issues[:10]:
        logger.info(f"  {issue}")
    if len(structure_issues) > 10:
        logger.info(f"  ... and {len(structure_issues) - 10} more")

    logger.info(f"\nTimezone Issues: {len(timezone_issues)}")
    for issue in timezone_issues[:10]:
        logger.info(f"  {issue}")
    if len(timezone_issues) > 10:
        logger.info(f"  ... and {len(timezone_issues) - 10} more")

    # Check specific examples
    logger.info(f"\n=== DETAILED SAMPLE CHECK ===")
    sample_tickers = ["AAPL", "MSFT", "GOOGL"]

    for ticker in sample_tickers:
        ticker_path = gold_root / ticker
        if not ticker_path.exists():
            continue

        logger.info(f"\n{ticker}:")

        # Check structure
        year_dirs = sorted(
            [d.name for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()]
        )
        logger.info(f"  Years: {year_dirs}")

        # Check latest year
        if year_dirs:
            latest_year = ticker_path / year_dirs[-1]
            files = sorted([f.name for f in latest_year.glob("*.parquet")])
            logger.info(f"  Files in {year_dirs[-1]}: {len(files)} files")
            logger.info(f"  Sample files: {files[:3]}")

            # Check sample file content
            if files:
                sample_file = latest_year / files[0]
                try:
                    df = pd.read_parquet(sample_file)
                    logger.info(f"  Columns: {list(df.columns)}")
                    logger.info(f"  Rows: {len(df)}")

                    if "ts" in df.columns:
                        logger.info(f"  Timestamp dtype: {df['ts'].dtype}")
                        logger.info(f"  Has timezone: {df['ts'].dt.tz is not None}")
                        logger.info(f"  Sample ts: {df['ts'].iloc[0]}")
                        logger.info(
                            f"  Date range: {df['ts'].min()} to {df['ts'].max()}"
                        )

                except Exception as e:
                    logger.error(f"  Error reading sample: {e}")

    return {
        "structure_issues": len(structure_issues),
        "timezone_issues": len(timezone_issues),
        "samples_checked": sample_checks,
    }


if __name__ == "__main__":
    results = check_gold_consistency()

    if results["structure_issues"] == 0 and results["timezone_issues"] == 0:
        logger.info("\n✅ All checks passed - data is consistent!")
    else:
        logger.info(
            f"\n⚠️  Found issues - Structure: {results['structure_issues']}, Timezone: {results['timezone_issues']}"
        )
