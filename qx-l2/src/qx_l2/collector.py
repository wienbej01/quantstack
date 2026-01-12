"""
L2 Collector - Platform-based implementation.

Replaces socket-based ib_insync with IBKR API Platform client.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from cpapi.platform_client import IBKRPlatformClient

logger = logging.getLogger(__name__)


class L2Collector:
    """L2 data collector using IBKR API Platform."""

    def __init__(self, config: Dict):
        self.config = config
        self.client = IBKRPlatformClient("l2-collector", "L2 Data Collector")
        self.symbols = []
        self.running = False

    def connect(self) -> bool:
        """Connect to IBKR API Platform."""
        try:
            success = self.client.register(["market-data"])
            if success:
                logger.info("Connected to IBKR API Platform")
                return True
            else:
                logger.error("Failed to register with platform")
                return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from platform."""
        try:
            self.client.unregister()
            logger.info("Disconnected from platform")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")

    def start_collection(self, symbols: List[str]):
        """Start L2 data collection."""
        self.symbols = symbols
        self.running = True

        logger.info(f"Starting L2 collection for {len(symbols)} symbols")

        while self.running:
            try:
                # Send heartbeat
                self.client.heartbeat()

                # Collect data for each symbol
                for symbol in symbols:
                    if not self.running:
                        break
                    self._collect_symbol_data(symbol)

                time.sleep(1)  # 1 second between cycles

            except Exception as e:
                logger.error(f"Collection error: {e}")
                time.sleep(5)

    def _collect_symbol_data(self, symbol: str):
        """Collect L2 data for a symbol."""
        try:
            # Search for contract
            contracts = self.client.search_contracts(symbol, "STK")
            if not contracts:
                logger.warning(f"No contract found for {symbol}")
                return

            conid = contracts[0].get("conid")
            if not conid:
                return

            # Get market data snapshot
            data = self.client.get_market_snapshot(
                [conid], ["31", "84", "85", "86", "88"]
            )
            if data:
                logger.debug(f"Collected data for {symbol}: {len(data)} fields")

        except Exception as e:
            logger.error(f"Error collecting {symbol}: {e}")

    def stop(self):
        """Stop collection."""
        self.running = False
        self.disconnect()


def main():
    """Main entry point for l2-collect command."""
    import argparse

    import yaml

    parser = argparse.ArgumentParser(description="L2 Data Collector")
    parser.add_argument("--config", required=True, help="Config file path")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    args = parser.parse_args()

    # Load config
    with open(args.config) as f:
        config = yaml.safe_load(f)

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create collector
    collector = L2Collector(config)

    try:
        if not collector.connect():
            logger.error("Failed to connect to platform")
            return 1

        # Get symbols from config or default list
        symbols = config.get("symbols", ["AAPL", "MSFT", "GOOGL"])

        # Start collection
        collector.start_collection(symbols)

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Collector error: {e}")
        return 1
    finally:
        collector.stop()

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
