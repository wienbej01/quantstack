"""Main L2 collector - standalone implementation."""

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


from ib_insync import IB, Stock, Ticker
from qx_l2.features import L2FeatureEngineer
from qx_l2.journal import L2Journal
from qx_l2.scheduler import L2Scheduler
from qx_l2.storage import L2Storage
from qx_l2.symbols import L2SymbolSelector

logger = logging.getLogger(__name__)


@dataclass
class CollectorState:
    """State for a single symbol."""

    symbol: str
    contract: Optional[Stock] = None
    ticker: Optional[Ticker] = None
    feature_eng: Optional[L2FeatureEngineer] = None
    last_snapshot_ts: float = 0.0


class L2Collector:
    """Standalone L2 data collector."""

    SYSTEM_NAME = "L2COLLECT"

    def __init__(self, config: dict):
        self.config = config

        # System identification
        system_cfg = config.get("system", {})
        self.system_name = system_cfg.get("name", self.SYSTEM_NAME)
        self.client_id = system_cfg.get("client_id", 500)
        self.system_tag = f"{self.system_name}_{self.client_id}"

        # IBKR connection
        ibkr_cfg = config.get("ibkr", {})
        self.host = ibkr_cfg.get("host", "127.0.0.1")
        self.port = ibkr_cfg.get("port", 7497)
        self.timeout = ibkr_cfg.get("timeout", 30)

        # Collection parameters
        coll_cfg = config.get("collection", {})
        self.levels = coll_cfg.get("levels", 10)
        self.snapshot_interval_ms = coll_cfg.get("snapshot_interval_ms", 1000)
        self.smart_depth = coll_cfg.get("smart_depth", True)
        self.rotate_seconds = coll_cfg.get("rotate_seconds", 300)

        # Components
        self.symbol_selector = L2SymbolSelector(config)
        self.scheduler = L2Scheduler(config)
        self.storage = L2Storage(config)
        self.journal = L2Journal(config)

        # Feature engineering
        feat_cfg = config.get("features", {})
        self.features_enabled = feat_cfg.get("enabled", True)

        # State
        self.ib: Optional[IB] = None
        self._states: dict[str, CollectorState] = {}
        self._raw_buffer: list[dict] = []
        self._feat_buffer: list[dict] = []
        self._session_id: str = ""
        self._running = False

    def connect(self) -> bool:
        """Connect to IBKR."""
        try:
            self.ib = IB()
            self.ib.connect(
                self.host, self.port, clientId=self.client_id, timeout=self.timeout
            )
            logger.info(
                f"[{self.system_tag}] Connected to IBKR {self.host}:{self.port}"
            )
            return True
        except Exception as e:
            logger.error(f"[{self.system_tag}] Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from IBKR."""
        if self.ib and self.ib.isConnected():
            # Unsubscribe all
            for state in self._states.values():
                if state.contract:
                    try:
                        self.ib.cancelMktDepth(state.contract)
                    except Exception:
                        pass
            self.ib.disconnect()
            logger.info(f"[{self.system_tag}] Disconnected from IBKR")

    def _subscribe_symbol(self, symbol: str) -> bool:
        """Subscribe to L2 data for a symbol."""
        try:
            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)

            # Request market depth
            self.ib.reqMktDepth(
                contract, numRows=self.levels, isSmartDepth=self.smart_depth
            )

            state = CollectorState(
                symbol=symbol,
                contract=contract,
                ticker=self.ib.ticker(contract),
                feature_eng=(
                    L2FeatureEngineer(self.config) if self.features_enabled else None
                ),
            )
            self._states[symbol] = state

            logger.info(f"[{self.system_tag}] Subscribed to {symbol}")
            return True
        except Exception as e:
            logger.error(f"[{self.system_tag}] Failed to subscribe {symbol}: {e}")
            return False

    def _unsubscribe_symbol(self, symbol: str):
        """Unsubscribe from L2 data."""
        if symbol in self._states:
            state = self._states[symbol]
            if state.contract:
                try:
                    self.ib.cancelMktDepth(state.contract)
                except Exception:
                    pass
            del self._states[symbol]
            logger.debug(f"[{self.system_tag}] Unsubscribed from {symbol}")

    def _make_snapshot(self, symbol: str) -> Optional[dict]:
        """Create snapshot from current ticker state."""
        state = self._states.get(symbol)
        if not state or not state.ticker:
            return None

        ticker = state.ticker
        now = time.time()

        # Basic L1 data
        snapshot = {
            "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "ts_epoch": now,
            "date_et": self.scheduler.now_local().strftime("%Y-%m-%d"),
            "symbol": symbol,
            "exchange": "SMART",
            "smart_depth": self.smart_depth,
            "l1_bid": self._safe_float(ticker.bid),
            "l1_ask": self._safe_float(ticker.ask),
            "l1_last": self._safe_float(ticker.last),
            "l1_bid_size": self._safe_float(ticker.bidSize),
            "l1_ask_size": self._safe_float(ticker.askSize),
        }

        # Calculate derived L1
        if snapshot["l1_bid"] and snapshot["l1_ask"]:
            snapshot["l1_mid"] = (snapshot["l1_bid"] + snapshot["l1_ask"]) / 2
            snapshot["l1_spread"] = snapshot["l1_ask"] - snapshot["l1_bid"]
        else:
            snapshot["l1_mid"] = None
            snapshot["l1_spread"] = None

        # L2 depth data
        has_depth = False
        dom_bids = getattr(ticker, "domBids", []) or []
        dom_asks = getattr(ticker, "domAsks", []) or []

        for i in range(self.levels):
            level = i + 1

            # Bid side
            if i < len(dom_bids):
                bid = dom_bids[i]
                snapshot[f"bid_px_{level}"] = self._safe_float(
                    getattr(bid, "price", None)
                )
                snapshot[f"bid_sz_{level}"] = self._safe_float(
                    getattr(bid, "size", None)
                )
                snapshot[f"bid_mm_{level}"] = getattr(bid, "marketMaker", None)
                if snapshot[f"bid_px_{level}"]:
                    has_depth = True
            else:
                snapshot[f"bid_px_{level}"] = None
                snapshot[f"bid_sz_{level}"] = None
                snapshot[f"bid_mm_{level}"] = None

            # Ask side
            if i < len(dom_asks):
                ask = dom_asks[i]
                snapshot[f"ask_px_{level}"] = self._safe_float(
                    getattr(ask, "price", None)
                )
                snapshot[f"ask_sz_{level}"] = self._safe_float(
                    getattr(ask, "size", None)
                )
                snapshot[f"ask_mm_{level}"] = getattr(ask, "marketMaker", None)
                if snapshot[f"ask_px_{level}"]:
                    has_depth = True
            else:
                snapshot[f"ask_px_{level}"] = None
                snapshot[f"ask_sz_{level}"] = None
                snapshot[f"ask_mm_{level}"] = None

        snapshot["has_depth"] = has_depth
        return snapshot

    def _safe_float(self, x: Any) -> Optional[float]:
        """Safely convert to float."""
        try:
            if x is None:
                return None
            v = float(x)
            return v if math.isfinite(v) else None
        except Exception:
            return None

    def poll_once(self):
        """Poll all subscribed symbols once."""
        if not self.ib or not self.ib.isConnected():
            return

        self.ib.sleep(0)  # Process IBKR messages
        now = time.time()
        interval_sec = self.snapshot_interval_ms / 1000.0

        for symbol, state in self._states.items():
            if now - state.last_snapshot_ts < interval_sec:
                continue

            snapshot = self._make_snapshot(symbol)
            if snapshot:
                self._raw_buffer.append(snapshot)
                state.last_snapshot_ts = now

                # Compute features
                if self.features_enabled and state.feature_eng:
                    features = state.feature_eng.compute(snapshot, self.levels)
                    if features:
                        self._feat_buffer.append(features)

        # Flush buffers if needed
        flush_rows = self.config.get("storage", {}).get("flush_rows", 300)
        if len(self._raw_buffer) >= flush_rows:
            self._flush_buffers()

    def _flush_buffers(self):
        """Flush data buffers to storage."""
        if self._raw_buffer:
            self.storage.write_batch(self._raw_buffer, "raw")
            self._raw_buffer = []

        if self._feat_buffer:
            self.storage.write_batch(self._feat_buffer, "features")
            self._feat_buffer = []

    def run_once(self, symbols: list[str] = None):
        """Run single collection cycle."""
        if symbols is None:
            symbols = self.symbol_selector.get_symbols()

        if not self.connect():
            return

        try:
            # Subscribe
            for symbol in symbols:
                self._subscribe_symbol(symbol)

            # Collect for one window or until interrupted
            logger.info(f"[{self.system_tag}] Collecting for {len(symbols)} symbols")

            while self.scheduler.is_collection_time():
                self.poll_once()
                time.sleep(0.1)

            self._flush_buffers()

        finally:
            self.disconnect()

    def run_daemon(self):
        """Run as daemon, collecting during scheduled windows."""
        logger.info(f"[{self.system_tag}] Starting daemon mode")
        self._running = True

        def on_window_start():
            symbols = self.symbol_selector.get_symbols()
            self._session_id = self.journal.start_session(
                symbols, str(self.scheduler.current_window())
            )

            if not self.connect():
                self.journal.log_error(
                    "CONNECTION", "Failed to connect", self._session_id
                )
                return

            for symbol in symbols:
                self._subscribe_symbol(symbol)

        def on_window_end():
            self._flush_buffers()

            # Calculate stats
            stats = {
                "records": len(self._raw_buffer),
                "depth_rate": 1.0,  # TODO: calculate actual
                "avg_spread": 0.01,  # TODO: calculate actual
            }
            self.journal.end_session(self._session_id, stats)
            self.disconnect()

        try:
            self.scheduler.run_daemon(on_window_start, on_window_end)
        except KeyboardInterrupt:
            logger.info(f"[{self.system_tag}] Daemon stopped")
            self._running = False
            if self.ib and self.ib.isConnected():
                self._flush_buffers()
                self.disconnect()

    def run_interactive(self):
        """Run interactively with status updates."""
        symbols = self.symbol_selector.get_symbols()

        print(f"\n{'='*50}")
        print(f"L2 Collector - {self.system_tag}")
        print(f"{'='*50}")
        print(f"Symbols: {symbols}")
        print(f"Windows: {[str(w) for w in self.scheduler.windows]}")
        print(f"Levels: {self.levels}")
        print(f"{'='*50}\n")

        if not self.scheduler.is_collection_time():
            next_window = self.scheduler.next_window_start()
            print(f"Outside collection window. Next: {next_window}")
            print("Use --daemon to wait for windows, or --once to collect now.")
            return

        self.run_once(symbols)
