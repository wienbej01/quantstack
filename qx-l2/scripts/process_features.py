#!/usr/bin/env python3
"""Process raw L2 data into features for historical dates."""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from qx_l2.features import L2FeatureEngineer
from qx_l2.storage import L2Storage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def process_date(config: dict, date_str: str) -> int:
    """Process all raw data for a specific date into features."""
    storage = L2Storage(config)
    feature_engineer = L2FeatureEngineer(config)

    raw_dir = storage.base_dir / "raw" / f"date={date_str}"
    if not raw_dir.exists():
        logger.warning(f"No raw data found for {date_str}")
        return 0

    total_processed = 0
    levels = config.get("collection", {}).get("levels", 10)

    # Process each symbol
    for symbol_dir in raw_dir.iterdir():
        if not symbol_dir.is_dir() or not symbol_dir.name.startswith("symbol="):
            continue

        symbol = symbol_dir.name.split("=")[1]
        logger.info(f"Processing {symbol} for {date_str}")

        # Read all raw parquet files for this symbol
        parquet_files = list(symbol_dir.glob("*.parquet"))
        if not parquet_files:
            continue

        # Load raw data
        dfs = [pd.read_parquet(f) for f in parquet_files]
        raw_df = pd.concat(dfs, ignore_index=True)
        if "symbol" not in raw_df.columns:
            raw_df["symbol"] = symbol

        # Compute features for each snapshot
        feature_records = []
        for _, row in raw_df.iterrows():
            snapshot = row.to_dict()
            features = feature_engineer.compute(snapshot, levels)
            if features:
                feature_records.append(features)

        # Write features
        if feature_records:
            storage.write_batch(feature_records, data_type="features")
            total_processed += len(feature_records)
            logger.info(f"  Processed {len(feature_records)} snapshots for {symbol}")

    return total_processed


def main():
    parser = argparse.ArgumentParser(description="Process raw L2 data into features")
    parser.add_argument(
        "--config", default="configs/maximum_l2.yaml", help="Config file"
    )
    parser.add_argument("--date", help="Process specific date (YYYY-MM-DD)")
    parser.add_argument(
        "--all", action="store_true", help="Process all dates with raw data"
    )

    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return 1

    with open(config_path) as f:
        config = yaml.safe_load(f)

    storage = L2Storage(config)

    if args.date:
        # Process single date
        count = process_date(config, args.date)
        logger.info(f"Processed {count} total snapshots for {args.date}")
    elif args.all:
        # Process all dates
        raw_base = storage.base_dir / "raw"
        if not raw_base.exists():
            logger.error("No raw data directory found")
            return 1

        total_count = 0
        for date_dir in sorted(raw_base.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.startswith("date="):
                continue

            date_str = date_dir.name.split("=")[1]
            count = process_date(config, date_str)
            total_count += count

        logger.info(f"Processed {total_count} total snapshots across all dates")
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
