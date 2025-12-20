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
        self.poll_interval_sec = coll_cfg.get("poll_interval_sec", 0.1)

        symbols_cfg = config.get("symbols", {})
        self.symbol_exchange = symbols_cfg.get("exchange")
        if not self.symbol_exchange:
            self.symbol_exchange = "SMART" if self.smart_depth else "NYSE"
        self.allowed_primary_exchanges = symbols_cfg.get("allowed_primary_exchanges")

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
        self._req_id_to_symbol: dict[int, str] = {}
        self._disabled_symbols: set[str] = set()
        self._session_stats = self._init_session_stats()

        self._fatal_depth_errors = {10092, 200, 10167, 10147}

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
            self.ib.errorEvent += self._on_ib_error
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
        self._states = {}
        self._req_id_to_symbol = {}

    def _subscribe_symbol(self, symbol: str) -> bool:
        """Subscribe to L2 data for a symbol."""
        if symbol in self._disabled_symbols:
            logger.info(f"[{self.system_tag}] Skipping disabled symbol {symbol}")
            return False
        if symbol in self._states:
            return True

        try:
            contract = Stock(symbol, self.symbol_exchange, "USD")
            details = self.ib.qualifyContracts(contract)
            if not details:
                self.journal.log_error(
                    "CONTRACT",
                    f"Qualify failed for {symbol}",
                    self._session_id,
                    symbol=symbol,
                )
                self._disable_symbol(symbol, "qualify_failed")
                return False

            qualified = details[0]
            contract = qualified.contract if hasattr(qualified, "contract") else qualified

            if self.allowed_primary_exchanges:
                primary = getattr(contract, "primaryExchange", None) or getattr(
                    contract, "exchange", None
                )
                if primary not in self.allowed_primary_exchanges:
                    logger.warning(
                        f"[{self.system_tag}] Skipping {symbol} due to "
                        f"primaryExchange={primary}"
                    )
                    return False

            # Request market depth - disable smartDepth for direct exchange
            ticker = self.ib.reqMktDepth(
                contract, numRows=self.levels, isSmartDepth=self.smart_depth
            )
            req_id = getattr(ticker, "reqId", None)
            if req_id is not None:
                self._req_id_to_symbol[req_id] = symbol

            state = CollectorState(
                symbol=symbol,
                contract=contract,
                ticker=ticker,
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

    def _disable_symbol(self, symbol: str, reason: str):
        """Disable symbol for remainder of process."""
        if symbol not in self._disabled_symbols:
            self._disabled_symbols.add(symbol)
            self._unsubscribe_symbol(symbol)
            logger.warning(f"[{self.system_tag}] Disabled {symbol}: {reason}")

    def _on_ib_error(self, req_id, error_code, error_string, contract=None):
        """Handle IBKR errors with symbol-level safeguards."""
        symbol = None
        if contract is not None:
            symbol = getattr(contract, "symbol", None)
        if symbol is None:
            symbol = self._req_id_to_symbol.get(req_id)

        if error_code in self._fatal_depth_errors and symbol:
            self.journal.log_error(
                "IBKR_DEPTH",
                f"code={error_code} msg={error_string}",
                self._session_id,
                symbol=symbol,
            )
            self._disable_symbol(symbol, f"IBKR error {error_code}")
        else:
            self.journal.log_error(
                "IBKR_ERROR",
                f"code={error_code} msg={error_string}",
                self._session_id,
                symbol=symbol,
            )

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

        for symbol, state in list(self._states.items()):
            if now - state.last_snapshot_ts < interval_sec:
                continue

            try:
                snapshot = self._make_snapshot(symbol)
                if snapshot:
                    self._raw_buffer.append(snapshot)
                    self._session_stats["records"] += 1
                    if snapshot.get("has_depth"):
                        self._session_stats["depth_records"] += 1
                    spread = snapshot.get("l1_spread")
                    if spread is not None:
                        self._session_stats["spread_total"] += spread
                        self._session_stats["spread_count"] += 1
                    state.last_snapshot_ts = now

                    # Compute features
                    if self.features_enabled and state.feature_eng:
                        features = state.feature_eng.compute(snapshot, self.levels)
                        if features:
                            self._feat_buffer.append(features)
            except Exception as e:
                self.journal.log_error(
                    "SNAPSHOT",
                    f"{symbol}: {e}",
                    self._session_id,
                    symbol=symbol,
                )

        # Flush buffers if needed
        flush_rows = self.config.get("storage", {}).get("flush_rows", 300)
        if len(self._raw_buffer) >= flush_rows:
            self._flush_buffers()

    def _flush_buffers(self):
        """Flush data buffers to storage."""
        if self._raw_buffer:
            try:
                self.storage.write_batch(self._raw_buffer, "raw")
                self._raw_buffer = []
            except Exception as e:
                self.journal.log_error("STORAGE", f"raw: {e}", self._session_id)

        if self._feat_buffer:
            try:
                self.storage.write_batch(self._feat_buffer, "features")
                self._feat_buffer = []
            except Exception as e:
                self.journal.log_error("STORAGE", f"features: {e}", self._session_id)

    @staticmethod
    def _init_session_stats() -> dict[str, float]:
        """Initialize per-session stats tracking."""
        return {
            "records": 0,
            "depth_records": 0,
            "spread_total": 0.0,
            "spread_count": 0,
        }

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

            self._session_stats = self._init_session_stats()
            while self.scheduler.is_collection_time():
                self.poll_once()
                time.sleep(self.poll_interval_sec)

            self._flush_buffers()

        finally:
            self.disconnect()

    def run_daemon(self):
        """Run as daemon, collecting during scheduled windows."""
        logger.info(f"[{self.system_tag}] Starting daemon mode")
        self._running = True
        was_in_window = False

        def on_window_start():
            symbols = self.symbol_selector.get_symbols()
            self._session_id = self.journal.start_session(
                symbols, str(self.scheduler.current_window())
            )
            self._session_stats = self._init_session_stats()

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
            records = self._session_stats["records"]
            depth_records = self._session_stats["depth_records"]
            spread_count = self._session_stats["spread_count"]
            spread_total = self._session_stats["spread_total"]
            stats = {
                "records": records,
                "depth_rate": (depth_records / records) if records else 0.0,
                "avg_spread": (spread_total / spread_count) if spread_count else 0.0,
            }
            self.journal.end_session(self._session_id, stats)
            self.disconnect()

        try:
            while self._running:
                in_window = self.scheduler.is_collection_time()

                if in_window and not was_in_window:
                    window = self.scheduler.current_window()
                    logger.info(f"Collection window started: {window}")
                    on_window_start()
                elif not in_window and was_in_window:
                    logger.info("Collection window ended")
                    on_window_end()

                if in_window:
                    self.poll_once()
                    time.sleep(self.poll_interval_sec)
                else:
                    time.sleep(5)

                was_in_window = in_window
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
