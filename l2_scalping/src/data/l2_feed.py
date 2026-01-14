"""
L2 Data Feed - Platform-based implementation.

Replaces socket-based ib_insync with IBKR API Platform client.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from cpapi.platform_client import IBKRPlatformClient

logger = logging.getLogger(__name__)


@dataclass
class L2Snapshot:
    """L2 market data snapshot."""
    symbol: str
    timestamp: datetime
    bid_price: float | None = None
    ask_price: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    last_price: float | None = None
    volume: int | None = None


class L2DataFeed:
    """L2 data feed using IBKR API Platform."""

    def __init__(self, config: dict):
        self.config = config
        self.client = IBKRPlatformClient("l2-scalping-data", "L2 Scalping Data")
        
        # Get symbols from config
        market_data_cfg = config.get("market_data", {})
        self.symbols = market_data_cfg.get("symbols", [])
        
        self.contracts: dict[str, int] = {}  # symbol -> conid
        self._snapshots: dict[str, L2Snapshot] = {}
        self._callbacks: list[Callable] = []
        self._running = False
        self._poll_thread: threading.Thread | None = None

    def connect(self) -> bool:
        """Connect to IBKR API Platform."""
        try:
            success = self.client.register(["market-data"])
            if success:
                logger.info("L2 Data Feed connected to platform")
                # Subscribe to symbols
                self._subscribe_symbols()
                # Start polling thread
                self._start_polling()
                return True
            else:
                logger.error("L2 Data Feed failed to register with platform")
                return False
        except Exception as e:
            logger.error(f"L2 Data Feed connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from platform."""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2)
        try:
            self.client.unregister()
            logger.info("L2 Data Feed disconnected from platform")
        except Exception as e:
            logger.error(f"L2 Data Feed disconnect error: {e}")

    def _subscribe_symbols(self):
        """Subscribe to configured symbols."""
        for symbol in self.symbols:
            try:
                contracts = self.client.search_contracts(symbol, "STK")
                if contracts and len(contracts) > 0:
                    self.contracts[symbol] = contracts[0].get("conid")
                    logger.info(f"Subscribed to {symbol} (conid: {self.contracts[symbol]})")
            except Exception as e:
                logger.error(f"Failed to subscribe to {symbol}: {e}")

    def _start_polling(self):
        """Start background polling thread."""
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self):
        """Background polling loop."""
        while self._running:
            try:
                self._poll_all_symbols()
                time.sleep(0.5)  # 2 Hz polling
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
                time.sleep(1)

    def _poll_all_symbols(self):
        """Poll market data for all symbols."""
        if not self.contracts:
            return

        conids = list(self.contracts.values())
        try:
            data = self.client.get_market_snapshot(conids)
            if data:
                for item in data:
                    conid = item.get("conid")
                    symbol = self._conid_to_symbol(conid)
                    if symbol:
                        snapshot = self._parse_snapshot(symbol, item)
                        self._snapshots[symbol] = snapshot
                        self._notify_callbacks(snapshot)
        except Exception as e:
            logger.error(f"Poll error: {e}")

    def _conid_to_symbol(self, conid: int) -> str | None:
        """Convert conid back to symbol."""
        for symbol, cid in self.contracts.items():
            if cid == conid:
                return symbol
        return None

    def _parse_snapshot(self, symbol: str, data: dict) -> L2Snapshot:
        """Parse API response into L2Snapshot."""
        return L2Snapshot(
            symbol=symbol,
            timestamp=datetime.now(),
            bid_price=data.get("84"),  # bid
            ask_price=data.get("86"),  # ask
            bid_size=data.get("88"),   # bid size
            ask_size=data.get("85"),   # ask size
            last_price=data.get("31"), # last
            volume=data.get("87")      # volume
        )

    def _notify_callbacks(self, snapshot: L2Snapshot):
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(snapshot)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def add_data_callback(self, callback: Callable):
        """Register a callback for market data updates."""
        self._callbacks.append(callback)

    def get_latest_snapshot(self, symbol: str) -> L2Snapshot | None:
        """Get latest snapshot for symbol."""
        return self._snapshots.get(symbol)

    def health_check(self) -> dict:
        """Return health status."""
        return {
            "connected": self._running,
            "symbols": len(self.contracts),
            "snapshots": len(self._snapshots)
        }
