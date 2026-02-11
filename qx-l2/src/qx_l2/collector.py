"""L2 Collector - ib_insync implementation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from qx_broker.ibkr import (
    ContractFactory,
    IBKRConnectionConfig,
    IBKRDepthConfig,
    IBKRMarketData,
    IBKRMarketDataConfig,
    IBKRMarketDepth,
    IBKRSession,
    IBKRSessionConfig,
)
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
    last_snapshot_ts: float = 0.0


class L2Collector:
    """L2 data collector using ib_insync."""

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
        self.levels = int(coll_cfg.get("levels", 5))
        self.smart_depth = bool(coll_cfg.get("smart_depth", False))

        # Symbols
        symbols_cfg = config.get("symbols", {})
        self.exchange = symbols_cfg.get("exchange", "SMART")
        self.primary_exchange = None
        if symbols_cfg.get("nyse_only"):
            self.primary_exchange = "NYSE"

        # Components
        self.symbol_selector = L2SymbolSelector(config)
        self.scheduler = L2Scheduler(config)
        self.storage = L2Storage(config)
        self.journal = L2Journal(config)
        self.feature_engineer = L2FeatureEngineer(config)

        # IBKR session
        ibkr_cfg = config.get("ibkr", {})
        timeout = float(ibkr_cfg.get("timeout", 30))
        connection = IBKRConnectionConfig(
            host=str(ibkr_cfg.get("host", "127.0.0.1")),
            port=int(ibkr_cfg.get("port", 7497)),
            client_id=int(self.client_id),
            connect_timeout=min(10.0, timeout),
            request_timeout=timeout,
        )
        session_cfg = IBKRSessionConfig(
            system_name=self.system_name, connection=connection
        )
        self.session = IBKRSession(session_cfg)

        # Market data + depth
        max_symbols = int(symbols_cfg.get("max_symbols", 3))
        self.market_data = IBKRMarketData(self.session, IBKRMarketDataConfig())
        self.market_depth = IBKRMarketDepth(
            self.session,
            IBKRDepthConfig(
                num_rows=min(self.levels, 5),
                smart_depth=self.smart_depth,
                max_symbols=max_symbols,
            ),
        )
        self.contracts = ContractFactory(self.session)

        # State
        self._states: dict[str, CollectorState] = {}
        self._contracts: dict[str, object] = {}
        self._running = False
        self._active_symbols: list[str] = []

    def connect(self) -> bool:
        """Connect to IBKR gateway."""
        if self.session.connect():
            logger.info("[%s] Connected to IBKR", self.system_tag)
            return True
        logger.error("[%s] Failed to connect to IBKR", self.system_tag)
        return False

    def disconnect(self) -> None:
        """Disconnect from IBKR gateway."""
        try:
            self._unsubscribe_all()
        finally:
            self.session.disconnect()
            logger.info("[%s] Disconnected from IBKR", self.system_tag)

    def _subscribe_symbols(self, symbols: list[str]) -> int:
        """Subscribe to symbols and return count of successful subscriptions."""
        count = 0
        for symbol in symbols:
            try:
                contract = self.contracts.stock(
                    symbol=symbol,
                    exchange=self.exchange,
                    primary_exchange=self.primary_exchange,
                )
                contract = self.contracts.qualify(contract)
                self.market_data.subscribe(contract, snapshot=False)
                self.market_depth.subscribe(contract)
                self._states[symbol] = CollectorState(symbol=symbol)
                self._contracts[symbol] = contract
                count += 1
                logger.info("[%s] Subscribed to %s", self.system_tag, symbol)
            except Exception as exc:
                logger.error(
                    "[%s] Subscription failed for %s: %s", self.system_tag, symbol, exc
                )
        return count

    def _unsubscribe_all(self) -> None:
        for symbol, contract in list(self._contracts.items()):
            try:
                self.market_depth.cancel(contract)
                self.market_data.cancel(contract)
            except Exception as exc:
                logger.warning(
                    "[%s] Unsubscribe failed for %s: %s", self.system_tag, symbol, exc
                )
        self._states.clear()
        self._contracts.clear()

    def _maybe_rotate_symbols(self) -> None:
        symbols = self.symbol_selector.get_symbols()
        if symbols == self._active_symbols:
            return
        self._unsubscribe_all()
        count = self._subscribe_symbols(symbols)
        self._active_symbols = symbols
        logger.info("[%s] Subscribed to %s symbols", self.system_tag, count)

    def _collect_snapshot(self, symbol: str) -> Optional[dict]:
        """Collect L2 snapshot for symbol."""
        state = self._states.get(symbol)
        if not state:
            return None

        depth_snapshot = self.market_depth.snapshot(symbol)
        if not depth_snapshot:
            return None

        now = datetime.now(timezone.utc)
        date_et = now.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

        record: dict[str, object] = {
            "ts_utc": now.isoformat(),
            "ts_epoch": now.timestamp(),
            "date_et": date_et,
            "symbol": symbol,
            "exchange": self.exchange,
            "smart_depth": self.smart_depth,
            "has_depth": bool(depth_snapshot.bids or depth_snapshot.asks),
        }

        for idx, level in enumerate(depth_snapshot.bids[: self.levels], start=1):
            record[f"bid_px_{idx}"] = level.price
            record[f"bid_sz_{idx}"] = level.size

        for idx, level in enumerate(depth_snapshot.asks[: self.levels], start=1):
            record[f"ask_px_{idx}"] = level.price
            record[f"ask_sz_{idx}"] = level.size

        l1_snapshot = self.market_data.snapshot(symbol)
        if l1_snapshot and l1_snapshot.bid is not None and l1_snapshot.ask is not None:
            record["l1_mid"] = (l1_snapshot.bid + l1_snapshot.ask) / 2
            record["l1_spread"] = l1_snapshot.ask - l1_snapshot.bid

        state.last_snapshot_ts = time.time()
        return record

    def _collection_cycle(self) -> None:
        """Run one collection cycle for all subscribed symbols."""
        raw_snapshots = []
        feature_records = []

        for symbol in list(self._states.keys()):
            if not self._running:
                break
            snapshot = self._collect_snapshot(symbol)
            if snapshot:
                raw_snapshots.append(snapshot)

                # Compute features if enabled
                feat_cfg = self.config.get("features", {})
                if feat_cfg.get("enabled", True):
                    features = self.feature_engineer.compute(snapshot, self.levels)
                    if features:
                        feature_records.append(features)

        # Write both raw and features
        if raw_snapshots:
            self.storage.write_batch(raw_snapshots, data_type="raw")
        if feature_records:
            self.storage.write_batch(feature_records, data_type="features")

    def run_daemon(self) -> None:
        """Run as daemon, collecting during scheduled windows."""
        logger.info("[%s] Starting daemon mode", self.system_tag)

        if not self.connect():
            logger.error("[%s] Failed to connect", self.system_tag)
            return

        self._running = True

        try:
            while self._running:
                if self.scheduler.is_collection_time():
                    self._maybe_rotate_symbols()
                    self._collection_cycle()
                    time.sleep(self.snapshot_interval_ms / 1000.0)
                else:
                    self._unsubscribe_all()
                    self._active_symbols = []
                    for _ in range(60):
                        if not self._running:
                            break
                        time.sleep(1)
        except KeyboardInterrupt:
            logger.info("[%s] Interrupted", self.system_tag)
        finally:
            self._running = False
            self.disconnect()

    def run_once(self) -> None:
        """Run single collection cycle."""
        logger.info("[%s] Running single collection", self.system_tag)

        if not self.connect():
            logger.error("[%s] Failed to connect", self.system_tag)
            return

        try:
            self._maybe_rotate_symbols()
            self._running = True
            self._collection_cycle()
        finally:
            self._running = False
            self.disconnect()

    def run_interactive(self) -> None:
        """Run in interactive mode."""
        self.run_once()
