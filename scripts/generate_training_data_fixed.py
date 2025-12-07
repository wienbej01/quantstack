#!/usr/bin/env python3
"""Generate training data with FIXED thresholds (no directional balance)."""

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

    # Load SIP membership
    sip_file = Path("run/sip_membership_smb_1month/sip_membership.parquet")
    LOGGER.info(f"Loading SIP membership from {sip_file}")
    sip = pd.read_parquet(sip_file)
    
    symbols = sorted(sip["symbol"].unique())
    LOGGER.info(f"SIP symbols: {len(symbols)} - {symbols}")

    # Date range
    start_date = "2024-05-01"
    end_date = "2024-05-31"

    LOGGER.info("=" * 80)
    LOGGER.info("Generating Training Data - FIXED THRESHOLDS")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Symbols: {len(symbols)}")
    LOGGER.info(f"Date range: {start_date} to {end_date}")
    LOGGER.info("Directional balance: DISABLED")
    LOGGER.info("Fixed threshold: 2% move in 30 minutes")

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
                "horizons": [30],
                "atr_window": 14,
                "atr_multiplier": 31.0,  # Calibrated for 2% moves (ATR ~0.065% × 31 = 2%)
                "atr_multiplier_long": 31.0,
                "atr_multiplier_short": 31.0,
                "atr_return_bounds": {
                    "min": 0.0001,  # Very low min
                    "max": 1.0,  # Very high max (don't clip)
                },
                "directional_balance": {
                    "enabled": False,  # DISABLE auto-balancing
                },
                "volatility_scaling": {
                    "enabled": False,  # DISABLE volatility scaling
                },
                "risk_reward": {
                    "enabled": False,  # DISABLE risk/reward adjustments
                },
            },
            data_loader_config={
                "gold_path": "/home/jacobw/gcs-mount/gold/stocks/1m",
            },
            include_ohlcv=True,
        )

        LOGGER.info(f"Generated {len(dataset)} rows")
        LOGGER.info(f"Unique symbols: {dataset['symbol'].nunique()}")
        
        # Check label distribution
        label_counts = dataset['label'].value_counts()
        LOGGER.info("Label distribution:")
        for label, count in label_counts.items():
            LOGGER.info(f"  {label}: {count:,} ({count/len(dataset)*100:.1f}%)")

        # Save
        output_path = Path("artefacts/extensions/intraday_ml/v4_sip_smb_fixed/training_data.parquet")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_parquet(output_path, index=False)

        LOGGER.info(f"Saved to: {output_path}")
        LOGGER.info("=" * 80)
        LOGGER.info("SUCCESS - Training data generated with fixed thresholds")

    except Exception as e:
        LOGGER.error(f"FAILED: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
