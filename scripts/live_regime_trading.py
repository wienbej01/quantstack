#!/usr/bin/env python3
"""Live regime-aware trading with L2 data collection."""

import logging
import time
from typing import Any

import yaml

from qx_core.logging import setup_logging
from qx_screener.sip.live_sip import LiveSIPSelector


def load_config(config_path: str) -> dict[str, Any]:
    """Load trading configuration."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    """Main live trading loop."""
    config_path = "experiments/live_regime_aware/config.yaml"
    config = load_config(config_path)

    # Setup logging
    setup_logging(config.get("logging", {}))
    logger = logging.getLogger(__name__)

    logger.info("Starting live regime-aware trading system")

    # Initialize live SIP selector
    live_sip = LiveSIPSelector(
        polygon_config=config["data"]["polygon"], l2_config=config["data"]["l2"]
    )

    try:
        # Daily universe selection
        logger.info("Selecting daily universe...")
        sip_universe, l2_symbols = live_sip.get_daily_universe()

        # Start L2 collection for focus symbols
        if config["data"]["l2"]["enabled"]:
            logger.info(f"Starting L2 collection for: {l2_symbols}")
            live_sip.start_l2_collection(l2_symbols)

        # Main trading loop
        logger.info("Entering main trading loop...")
        loop_count = 0

        while True:
            try:
                # Poll L2 data
                if config["data"]["l2"]["enabled"]:
                    live_sip.poll_l2_data()

                # Trading logic would go here
                # For now, just log L2 features every 10 loops
                if loop_count % 10 == 0:
                    for symbol in l2_symbols:
                        features = live_sip.get_l2_features(symbol)
                        if features:
                            logger.info(
                                f"{symbol} L2: mid={features.get('mid'):.4f}, "
                                f"spread={features.get('spread'):.4f}, "
                                f"obi_1={features.get('obi_1'):.3f}"
                            )

                loop_count += 1
                time.sleep(1)  # 1 second polling

            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                time.sleep(5)

    finally:
        # Cleanup
        logger.info("Stopping live trading system...")
        metadata = live_sip.stop()
        logger.info(f"Collection metadata: {metadata}")


if __name__ == "__main__":
    main()
