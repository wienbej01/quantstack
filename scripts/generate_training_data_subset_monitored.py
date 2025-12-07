#!/usr/bin/env python3
"""Generate training data with progress monitoring."""

import logging
import time
from pathlib import Path
from threading import Thread

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def heartbeat_monitor(interval=60):
    """Log heartbeat every N seconds."""
    while True:
        time.sleep(interval)
        LOGGER.info("[HEARTBEAT] Process still running...")


def main():
    # Start heartbeat thread
    heartbeat = Thread(target=heartbeat_monitor, args=(60,), daemon=True)
    heartbeat.start()

    # Load SIP membership (only train on stocks in play)
    sip_file = Path("run/sip_membership_smb_1month/sip_membership.parquet")
    LOGGER.info(f"Loading SIP membership from {sip_file}")
    sip = pd.read_parquet(sip_file)
    
    symbols = sorted(sip["symbol"].unique())
    LOGGER.info(f"SIP symbols: {len(symbols)} - {symbols}")

    # Date range
    start_date = "2024-05-01"
    end_date = "2024-05-31"

    LOGGER.info("=" * 80)
    LOGGER.info("Generating Training Data from SIP")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Symbols: {len(symbols)}")
    LOGGER.info(f"Date range: {start_date} to {end_date}")

    # Import here to avoid early failures
    from extensions.intraday_ml.data_prep import create_training_dataset

    LOGGER.info("Starting create_training_dataset...")
    LOGGER.info("This may take 10-30 minutes...")

    try:
        dataset = create_training_dataset(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            features_config={
                "volume_momentum": {"window": 20},
                "price_momentum": {"window": 20},
                "volatility": {"window": 20},
            },
            targets_config={
                "forward_window_minutes": 30,
                "profit_threshold_pct": 0.015,
                "stop_threshold_pct": 0.01,
            },
            data_loader_config={
                "gold_path": "/home/jacobw/gcs-mount/gold/stocks/1m",
            },
            include_ohlcv=True,
        )

        LOGGER.info(f"Generated {len(dataset)} rows")
        LOGGER.info(f"Unique symbols: {dataset['symbol'].nunique()}")
        LOGGER.info(f"Columns: {dataset.columns.tolist()}")

        # Save
        output_path = Path("artefacts/extensions/intraday_ml/v4_sip_smb/training_data.parquet")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_parquet(output_path, index=False)

        LOGGER.info(f"Saved to: {output_path}")
        LOGGER.info("=" * 80)
        LOGGER.info("SUCCESS - Training data generated")
        LOGGER.info("Next: python scripts/train_v4_subset.py")

    except Exception as e:
        LOGGER.error(f"FAILED: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
