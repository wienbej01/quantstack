#!/usr/bin/env python3

import logging
import shutil
from pathlib import Path
from typing import Any, Dict

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# Column mapping for legacy formats
COLUMN_MAPPING = {
    "t": "ts_ms",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "vw": "vwap",
    "n": "trades",
    "timestamp": "ts_ms",
}

# Standard bronze schema
STANDARD_COLUMNS = [
    "ts_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "trades",
    "ticker",
    "vendor",
    "ingested_at_ms",
    "page",
    "date_et",
    "session",
]


def fix_flat_structure(bronze_dir: Path) -> None:
    """Fix tickers with flat file structure"""
    for ticker_dir in bronze_dir.iterdir():
        if not ticker_dir.is_dir():
            continue

        # Check for flat parquet files in ticker root
        parquet_files = list(ticker_dir.glob("*.parquet"))
        if not parquet_files:
            continue

        logging.info(f"Fixing flat structure for {ticker_dir.name}")

        for file in parquet_files:
            # Extract year from filename or data
            try:
                df = pd.read_parquet(file)
                if "ts_ms" in df.columns:
                    year = pd.to_datetime(df["ts_ms"], unit="ms").dt.year.iloc[0]
                elif "t" in df.columns:
                    year = pd.to_datetime(df["t"], unit="ms").dt.year.iloc[0]
                else:
                    year = 2023  # fallback

                # Create year directory and move file
                year_dir = ticker_dir / str(year)
                year_dir.mkdir(exist_ok=True)

                new_path = (
                    year_dir
                    / f"{year}-{file.stem.split('-')[-1] if '-' in file.stem else '01'}.parquet"
                )
                shutil.move(str(file), str(new_path))
                logging.info(f"Moved {file.name} to {new_path}")

            except Exception as e:
                logging.error(f"Error processing {file}: {e}")


def standardize_columns(file_path: Path) -> bool:
    """Standardize column names and format"""
    try:
        df = pd.read_parquet(file_path)

        # Check if already standardized
        if "ts_ms" in df.columns and "open" in df.columns:
            return False

        # Apply column mapping
        df = df.rename(columns=COLUMN_MAPPING)

        # Ensure required columns exist
        for col in ["ts_ms", "open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                logging.warning(f"Missing required column {col} in {file_path}")
                return False

        # Add missing optional columns with defaults
        if "ticker" not in df.columns:
            df["ticker"] = file_path.parent.parent.name
        if "vendor" not in df.columns:
            df["vendor"] = "polygon"
        if "ingested_at_ms" not in df.columns:
            df["ingested_at_ms"] = df["ts_ms"]

        # Reorder columns to match standard
        available_cols = [col for col in STANDARD_COLUMNS if col in df.columns]
        df = df[available_cols]

        # Save back
        df.to_parquet(file_path, index=False)
        return True

    except Exception as e:
        logging.error(f"Error standardizing {file_path}: {e}")
        return False


def main():
    bronze_dir = Path("/home/jacobw/gcs-mount/bronze/stocks/1m")

    if not bronze_dir.exists():
        logging.error(f"Bronze directory not found: {bronze_dir}")
        return

    logging.info("Step 1: Fixing flat file structures...")
    fix_flat_structure(bronze_dir)

    logging.info("Step 2: Standardizing column formats...")

    processed = 0
    standardized = 0

    for ticker_dir in bronze_dir.iterdir():
        if not ticker_dir.is_dir():
            continue

        for year_dir in ticker_dir.iterdir():
            if not year_dir.is_dir():
                continue

            for file_path in year_dir.glob("*.parquet"):
                processed += 1
                if standardize_columns(file_path):
                    standardized += 1

                if processed % 100 == 0:
                    logging.info(
                        f"Processed {processed} files, standardized {standardized}"
                    )

    logging.info(f"Complete: {processed} files processed, {standardized} standardized")


if __name__ == "__main__":
    main()
