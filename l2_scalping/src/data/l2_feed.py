"""
L2 Data Feed - Platform-based implementation.

Replaces socket-based ib_insync with IBKR API Platform client.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from cpapi.platform_client import IBKRPlatformClient

logger = logging.getLogger(__name__)


@dataclass
class L2Snapshot:
    """L2 market data snapshot."""

    symbol: str
    timestamp: datetime
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    last_price: Optional[float] = None
    volume: Optional[int] = None


class L2DataFeed:
    """L2 data feed using IBKR API Platform."""

    def __init__(self, config: Dict):
        self.config = config
        self.client = IBKRPlatformClient("l2-scalping-data", "L2 Scalping Data")
        self.symbols = []
        self.contracts = {}  # symbol -> conid mapping

    def connect(self) -> bool:
        """Connect to IBKR API Platform."""
        try:
            success = self.client.register(["market-data"])
            if success and self.client.check_auth_status():
                logger.info("Connected to IBKR API Platform for data feed")
                return True
            else:
                logger.error("Platform not authenticated")
                return False
        except Exception as e:
            logger.error(f"Data feed connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from platform."""
        try:
            self.client.unregister()
            logger.info("Data feed disconnected from platform")
        except Exception as e:
            logger.error(f"Data feed disconnect error: {e}")

    def subscribe_symbols(self, symbols: List[str]) -> bool:
        """Subscribe to symbols."""
        try:
            self.symbols = symbols

            # Get contract IDs for all symbols
            for symbol in symbols:
                contracts = self.client.search_contracts(symbol, "STK")
                if contracts:
                    self.contracts[symbol] = contracts[0].get("conid")
                    logger.info(
                        f"Subscribed to {symbol} (conid: {self.contracts[symbol]})"
                    )
                else:
                    logger.warning(f"No contract found for {symbol}")

            return len(self.contracts) > 0

        except Exception as e:
            logger.error(f"Subscription error: {e}")
            return False

    def get_snapshot(self, symbol: str) -> Optional[L2Snapshot]:
        """Get L2 snapshot for symbol."""
        try:
            conid = self.contracts.get(symbol)
            if not conid:
                return None

            # Get market data snapshot
            # Fields: 31=bid, 84=ask, 85=bid_size, 86=ask_size, 31=last, 87=volume
            data = self.client.get_market_snapshot(
                [conid], ["31", "84", "85", "86", "87"]
            )

            if not data:
                return None

            snapshot_data = data[0] if data else {}

            return L2Snapshot(
                symbol=symbol,
                timestamp=datetime.now(),
                bid_price=snapshot_data.get("31"),
                ask_price=snapshot_data.get("84"),
                bid_size=snapshot_data.get("85"),
                ask_size=snapshot_data.get("86"),
                volume=snapshot_data.get("87"),
            )

        except Exception as e:
            logger.error(f"Snapshot error for {symbol}: {e}")
            return None

    def get_all_snapshots(self) -> List[L2Snapshot]:
        """Get snapshots for all subscribed symbols."""
        snapshots = []

        for symbol in self.symbols:
            snapshot = self.get_snapshot(symbol)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    def heartbeat(self):
        """Send heartbeat to platform."""
        try:
            self.client.heartbeat()
        except Exception as e:
            logger.error(f"Data feed heartbeat error: {e}")
