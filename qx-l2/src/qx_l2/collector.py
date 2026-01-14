"""L2 Collector - Platform-based implementation."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from cpapi.platform_client import IBKRPlatformClient
from qx_l2.journal import L2Journal
from qx_l2.scheduler import L2Scheduler
from qx_l2.storage import L2Storage
from qx_l2.symbols import L2SymbolSelector

logger = logging.getLogger(__name__)


@dataclass
class CollectorState:
    """State for a single symbol."""
    symbol: str
    conid: Optional[int] = None
    last_snapshot_ts: float = 0.0


class L2Collector:
    """L2 data collector using IBKR API Platform."""

    SYSTEM_NAME = "L2COLLECT"

    def __init__(self, config: dict):
        self.config = config

        # System identification
        system_cfg = config.get("system", {})
        self.system_name = system_cfg.get("name", self.SYSTEM_NAME)
        self.client_id = system_cfg.get("client_id", 500)
        self.system_tag = f"{self.system_name}_{self.client_id}"

        # Collection parameters
        coll_cfg = config.get("collection", {})
        self.snapshot_interval_ms = coll_cfg.get("snapshot_interval_ms", 1000)
        self.rotate_seconds = coll_cfg.get("rotate_seconds", 300)

        # Components
        self.symbol_selector = L2SymbolSelector(config)
        self.scheduler = L2Scheduler(config)
        self.storage = L2Storage(config)
        self.journal = L2Journal(config)

        # Platform client
        self.client = IBKRPlatformClient(f"l2-collector-{self.client_id}", "L2 Data Collector")

        # State
        self._states: dict[str, CollectorState] = {}
        self._running = False

    def connect(self) -> bool:
        """Connect to IBKR API Platform."""
        try:
            success = self.client.register(["market-data"])
            if success:
                logger.info(f"[{self.system_tag}] Connected to IBKR API Platform")
                return True
            else:
                logger.error(f"[{self.system_tag}] Failed to register with platform")
                return False
        except Exception as e:
            logger.error(f"[{self.system_tag}] Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from platform."""
        try:
            self.client.unregister()
            logger.info(f"[{self.system_tag}] Disconnected from platform")
        except Exception as e:
            logger.error(f"[{self.system_tag}] Disconnect error: {e}")

    def _resolve_contract(self, symbol: str) -> Optional[int]:
        """Resolve symbol to contract ID."""
        try:
            contracts = self.client.search_contracts(symbol, "STK")
            if contracts and len(contracts) > 0:
                conid = contracts[0].get("conid")
                logger.info(f"[{self.system_tag}] Resolved {symbol} -> conid {conid}")
                return conid
            else:
                logger.warning(f"[{self.system_tag}] No contract found for {symbol}")
                return None
        except Exception as e:
            logger.error(f"[{self.system_tag}] Contract resolution failed for {symbol}: {e}")
            return None

    def _subscribe_symbols(self, symbols: list[str]) -> int:
        """Subscribe to symbols and return count of successful subscriptions."""
        count = 0
        for symbol in symbols:
            conid = self._resolve_contract(symbol)
            if conid:
                self._states[symbol] = CollectorState(symbol=symbol, conid=conid)
                count += 1
                logger.info(f"[{self.system_tag}] Subscribed to {symbol}")
        return count

    def _collect_snapshot(self, symbol: str) -> Optional[dict]:
        """Collect market data snapshot for symbol."""
        state = self._states.get(symbol)
        if not state or not state.conid:
            return None

        try:
            # Get market data snapshot
            data = self.client.get_market_snapshot([state.conid])
            if data and len(data) > 0:
                snapshot = data[0]
                snapshot["symbol"] = symbol
                snapshot["ts"] = datetime.now().isoformat()
                state.last_snapshot_ts = time.time()
                return snapshot
        except Exception as e:
            logger.error(f"[{self.system_tag}] Snapshot failed for {symbol}: {e}")
        return None

    def _collection_cycle(self):
        """Run one collection cycle for all subscribed symbols."""
        for symbol in list(self._states.keys()):
            if not self._running:
                break
            snapshot = self._collect_snapshot(symbol)
            if snapshot:
                self.storage.write_batch([snapshot])
        
        # Send heartbeat
        self.client.heartbeat()

    def run_daemon(self):
        """Run as daemon, collecting during scheduled windows."""
        logger.info(f"[{self.system_tag}] Starting daemon mode")
        
        if not self.connect():
            logger.error(f"[{self.system_tag}] Failed to connect")
            return

        self._running = True
        
        try:
            while self._running:
                # Check if in collection window
                if self.scheduler.is_collection_time():
                    # Get symbols for this window
                    symbols = self.symbol_selector.get_symbols()
                    
                    if symbols and not self._states:
                        # Subscribe to symbols
                        count = self._subscribe_symbols(symbols)
                        logger.info(f"[{self.system_tag}] Subscribed to {count} symbols")
                    
                    # Collect data
                    self._collection_cycle()
                    
                    # Sleep for snapshot interval
                    time.sleep(self.snapshot_interval_ms / 1000.0)
                else:
                    # Outside collection window
                    self._states.clear()
                    # Use short sleeps to allow quick shutdown
                    for _ in range(60):
                        if not self._running:
                            break
                        time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info(f"[{self.system_tag}] Interrupted")
        finally:
            self._running = False
            self.disconnect()

    def run_once(self):
        """Run single collection cycle."""
        logger.info(f"[{self.system_tag}] Running single collection")
        
        if not self.connect():
            logger.error(f"[{self.system_tag}] Failed to connect")
            return

        try:
            symbols = self.symbol_selector.get_symbols()
            if symbols:
                self._subscribe_symbols(symbols)
                self._running = True
                self._collection_cycle()
        finally:
            self._running = False
            self.disconnect()

    def run_interactive(self):
        """Run in interactive mode."""
        self.run_once()
