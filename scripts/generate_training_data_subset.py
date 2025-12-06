#!/usr/bin/env python3
"""Generate training data for 100-symbol subset test."""

import logging
from pathlib import Path

from extensions.intraday_ml.data_prep import create_training_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    # Load top 100 symbols by market cap (proxy: alphabetically first 100)
    universe_file = "/home/jacobw/quantstack/run/smb_universe.txt"
    with open(universe_file) as f:
        all_symbols = [line.strip() for line in f if line.strip()]

    # Take first 100 (includes major names like AAPL, ABBV, etc.)
    symbols = all_symbols[:100]

    LOGGER.info("=" * 80)
    LOGGER.info("Generating Training Data for 100-Symbol Subset")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Symbols: {len(symbols)}")
    LOGGER.info(f"Sample: {symbols[:10]}")

    # Use same date range as existing training data
    start_date = "2024-01-01"
    end_date = "2024-05-31"

    LOGGER.info(f"Date range: {start_date} to {end_date}")

    # Load configs
    features_config = {
        "volume_momentum": {"window": 20},
        "price_momentum": {"window": 20},
        "volatility": {"window": 20},
    }

    targets_config = {
        "forward_window_minutes": 30,
        "profit_threshold_pct": 0.015,  # 1.5%
        "stop_threshold_pct": 0.01,  # 1.0%
    }

    data_loader_config = {
        "gold_path": "/home/jacobw/gcs-mount/gold/stocks/1m",
    }

    LOGGER.info("Creating training dataset...")
    LOGGER.info("This will take 30-60 minutes for 100 symbols...")

    try:
        dataset = create_training_dataset(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            features_config=features_config,
            targets_config=targets_config,
            data_loader_config=data_loader_config,
            include_ohlcv=True,
        )

        LOGGER.info(f"Generated {len(dataset)} rows")
        LOGGER.info(f"Unique symbols: {dataset['symbol'].nunique()}")

        # Save
        output_path = Path(
            "artefacts/extensions/intraday_ml/v4_subset_100/training_data.parquet"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_parquet(output_path, index=False)

        LOGGER.info(f"Saved to: {output_path}")
        LOGGER.info("=" * 80)
        LOGGER.info("Next: python scripts/train_v4_subset.py")

    except Exception as e:
        LOGGER.error(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
