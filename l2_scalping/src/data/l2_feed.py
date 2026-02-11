"""L2 Data Feed - ib_insync implementation."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from qx_broker.ibkr import (
    ContractFactory,
    IBKRConnectionConfig,
    IBKRDepthConfig,
    IBKRMarketDepth,
    IBKRSession,
    IBKRSessionConfig,
)

logger = logging.getLogger(__name__)

# Optional storage for L2 data collection
try:
    from qx_l2.storage import L2Storage

    L2_STORAGE_AVAILABLE = True
except ImportError:
    L2_STORAGE_AVAILABLE = False


@dataclass
class L2Snapshot:
    """L2 market data snapshot with computed features."""

    symbol: str
    timestamp: float
    mid: float
    spread: float
    obi_1: float
    obi_5: float
    depth_bid: float
    depth_ask: float
    pressure: float
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None


class L2DataFeed:
    """L2 data feed using ib_insync."""

    def __init__(self, config: dict):
        self.config = config
        ibkr_cfg = config.get("ibkr", config)
        market_data_cfg = config.get("market_data", config)

        self.symbols = market_data_cfg.get("symbols", config.get("symbols", []))
        self.depth_levels = int(market_data_cfg.get("depth_levels", 5))
        self.smart_depth = bool(
            market_data_cfg.get("smart_depth", config.get("smart_depth", False))
        )
        self.exchange = market_data_cfg.get("exchange", config.get("exchange", "SMART"))

        data_client_id = int(
            ibkr_cfg.get("data_client_id_base", ibkr_cfg.get("data_client_id", 250))
        )
        client_id_max = int(ibkr_cfg.get("client_id_max", data_client_id))
        client_id_fallbacks = max(0, client_id_max - data_client_id)
        self.host = str(ibkr_cfg.get("host", "127.0.0.1"))
        self.port = int(ibkr_cfg.get("port", 7497))
        self.client_id = data_client_id
        connection = IBKRConnectionConfig(
            host=self.host,
            port=self.port,
            client_id=data_client_id,
            connect_timeout=float(ibkr_cfg.get("timeout", 30)),
            request_timeout=float(ibkr_cfg.get("timeout", 30)),
            reconnect_attempts=int(ibkr_cfg.get("max_reconnect_attempts", 5)),
            reconnect_backoff_sec=float(ibkr_cfg.get("reconnect_delay", 5)),
            allow_client_id_fallback=client_id_fallbacks > 0,
            client_id_fallbacks=client_id_fallbacks,
        )
        session_cfg = IBKRSessionConfig(
            system_name="L2_SCALPING_DATA", connection=connection
        )
        self.session = IBKRSession(session_cfg)

        max_symbols = int(
            market_data_cfg.get(
                "max_symbols", config.get("max_symbols", len(self.symbols) or 1)
            )
        )
        self.market_depth = IBKRMarketDepth(
            self.session,
            IBKRDepthConfig(
                num_rows=self.depth_levels,
                smart_depth=self.smart_depth,
                max_symbols=max_symbols,
            ),
        )
        self.contracts = ContractFactory(self.session)

        self._snapshots: dict[str, L2Snapshot] = {}
        self._callbacks: list[Callable[[L2Snapshot], None]] = []
        self._running = False
        self._poll_thread: threading.Thread | None = None
        self._contract_map: dict[str, object] = {}

        # L2 storage for data collection (shared with l2-collector)
        self._storage = None
        self._storage_buffer: list[dict] = []
        self._raw_storage_buffer: list[dict] = []
        self._storage_flush_interval = 100  # flush every 100 snapshots
        if L2_STORAGE_AVAILABLE:
            data_root = Path(
                os.environ.get("L2_DATA_ROOT", "/home/jacobw/quantstack/data/l2")
            ).expanduser()
            storage_cfg = {"storage": {"base_dir": str(data_root / "l2_maximum")}}
            self._storage = L2Storage(storage_cfg)
            logger.info("L2 storage enabled - writing to shared location")

    def connect(self) -> bool:
        """Connect to IBKR gateway."""
        if not self.session.connect():
            logger.error("L2 Data Feed failed to connect")
            return False

        self._subscribe_symbols()
        self._start_polling()
        logger.info("L2 Data Feed connected to IBKR")
        return True

    def disconnect(self) -> None:
        """Disconnect from IBKR gateway."""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2)
        self._flush_storage()  # Flush remaining data
        for symbol, contract in list(self._contract_map.items()):
            try:
                self.market_depth.cancel(contract)
            except Exception as exc:
                logger.warning("Failed to cancel depth for %s: %s", symbol, exc)
        self._contract_map.clear()
        self.session.disconnect()
        logger.info("L2 Data Feed disconnected")

    def _subscribe_symbols(self) -> None:
        for symbol in self.symbols:
            try:
                contract = self.contracts.stock(
                    symbol, exchange=self.exchange, primary_exchange="NYSE"
                )
                contract = self.contracts.qualify(contract)
                self.market_depth.subscribe(contract)
                self._contract_map[symbol] = contract
                logger.info("Subscribed to %s", symbol)
            except Exception as exc:
                logger.error("Failed to subscribe to %s: %s", symbol, exc)

    def _start_polling(self) -> None:
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._poll_all_symbols()
                time.sleep(0.5)
            except Exception as exc:
                logger.error("Poll loop error: %s", exc)
                time.sleep(1)

    def _poll_all_symbols(self) -> None:
        for symbol in list(self._contract_map.keys()):
            depth_snapshot = self.market_depth.snapshot(symbol)
            if not depth_snapshot:
                continue

            raw_record = self._build_raw_record(symbol, depth_snapshot)
            if raw_record is not None:
                self._store_raw_snapshot(raw_record)

            snapshot = self._build_snapshot(symbol, depth_snapshot)
            if snapshot:
                self._snapshots[symbol] = snapshot
                self._notify_callbacks(snapshot)
                self._store_snapshot(snapshot)

        # Flush storage buffer periodically
        if self._storage and (
            len(self._storage_buffer) >= self._storage_flush_interval
            or len(self._raw_storage_buffer) >= self._storage_flush_interval
        ):
            self._flush_storage()

    def _store_snapshot(self, snapshot: L2Snapshot) -> None:
        """Store feature snapshot for L2 data collection."""
        if not self._storage:
            return
        now = datetime.now(timezone.utc)
        record = {
            "ts_utc": now.isoformat(),
            "ts_epoch": now.timestamp(),
            "date_et": now.astimezone(ZoneInfo("America/New_York")).strftime(
                "%Y-%m-%d"
            ),
            "symbol": snapshot.symbol,
            "mid": snapshot.mid,
            "spread": snapshot.spread,
            "obi_1": snapshot.obi_1,
            "obi_5": snapshot.obi_5,
            "depth_bid": snapshot.depth_bid,
            "depth_ask": snapshot.depth_ask,
            "pressure": snapshot.pressure,
            "bid": snapshot.bid,
            "ask": snapshot.ask,
            "bid_size": snapshot.bid_size,
            "ask_size": snapshot.ask_size,
        }
        self._storage_buffer.append(record)

    def _store_raw_snapshot(self, record: dict) -> None:
        if not self._storage:
            return
        self._raw_storage_buffer.append(record)

    def _flush_storage(self) -> None:
        """Flush storage buffers to disk."""
        if not self._storage:
            return

        if self._raw_storage_buffer:
            try:
                self._storage.write_batch(self._raw_storage_buffer, data_type="raw")
                self._raw_storage_buffer.clear()
            except Exception as exc:
                logger.warning("Failed to flush raw L2 storage: %s", exc)

        if self._storage_buffer:
            try:
                self._storage.write_batch(self._storage_buffer, data_type="features")
                self._storage_buffer.clear()
            except Exception as exc:
                logger.warning("Failed to flush feature storage: %s", exc)

    def _build_raw_record(self, symbol: str, depth_snapshot) -> dict | None:
        ts_epoch = float(depth_snapshot.timestamp)
        ts_utc = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
        date_et = ts_utc.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        bids = list(depth_snapshot.bids or [])
        asks = list(depth_snapshot.asks or [])
        record: dict[str, object] = {
            "ts_utc": ts_utc.isoformat(),
            "ts_epoch": ts_epoch,
            "date_et": date_et,
            "symbol": symbol,
            "exchange": self.exchange,
            "smart_depth": self.smart_depth,
            "has_depth": bool(bids or asks),
            "l1_bid": None,
            "l1_ask": None,
            "l1_last": None,
            "l1_bid_size": None,
            "l1_ask_size": None,
            "l1_mid": None,
            "l1_spread": None,
        }

        if bids:
            record["l1_bid"] = bids[0].price
            record["l1_bid_size"] = bids[0].size
        if asks:
            record["l1_ask"] = asks[0].price
            record["l1_ask_size"] = asks[0].size
        if bids and asks:
            record["l1_mid"] = (bids[0].price + asks[0].price) / 2
            record["l1_spread"] = asks[0].price - bids[0].price

        for idx, level in enumerate(bids[: self.depth_levels], start=1):
            record[f"bid_px_{idx}"] = level.price
            record[f"bid_sz_{idx}"] = level.size
            record[f"bid_mm_{idx}"] = level.market_maker

        for idx, level in enumerate(asks[: self.depth_levels], start=1):
            record[f"ask_px_{idx}"] = level.price
            record[f"ask_sz_{idx}"] = level.size
            record[f"ask_mm_{idx}"] = level.market_maker

        return record

    def _build_snapshot(self, symbol: str, depth_snapshot) -> L2Snapshot | None:
        if not depth_snapshot or not depth_snapshot.bids or not depth_snapshot.asks:
            return None

        bids = depth_snapshot.bids
        asks = depth_snapshot.asks
        bid = bids[0].price
        ask = asks[0].price
        bid_size = bids[0].size
        ask_size = asks[0].size

        mid = (bid + ask) / 2
        spread = ask - bid

        total_size = bid_size + ask_size
        if total_size > 0:
            obi_1 = (bid_size - ask_size) / total_size
        else:
            obi_1 = 0.0

        depth_bid_size = sum(level.size for level in bids[: self.depth_levels])
        depth_ask_size = sum(level.size for level in asks[: self.depth_levels])
        depth_total = depth_bid_size + depth_ask_size
        if depth_total > 0:
            obi_5 = (depth_bid_size - depth_ask_size) / depth_total
        else:
            obi_5 = 0.0

        depth_bid = sum(level.size * level.price for level in bids[: self.depth_levels])
        depth_ask = sum(level.size * level.price for level in asks[: self.depth_levels])
        depth_value_total = depth_bid + depth_ask
        if depth_value_total > 0:
            pressure = (depth_bid - depth_ask) / depth_value_total
        else:
            pressure = 0.0

        return L2Snapshot(
            symbol=symbol,
            timestamp=time.time(),
            mid=mid,
            spread=spread,
            obi_1=obi_1,
            obi_5=obi_5,
            depth_bid=depth_bid,
            depth_ask=depth_ask,
            pressure=pressure,
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
        )

    def _notify_callbacks(self, snapshot: L2Snapshot) -> None:
        for callback in self._callbacks:
            try:
                callback(snapshot)
            except Exception as exc:
                logger.error("Callback error: %s", exc)

    def add_data_callback(self, callback: Callable[[L2Snapshot], None]) -> None:
        """Register a callback for market data updates."""
        self._callbacks.append(callback)

    def get_latest_snapshot(self, symbol: str) -> L2Snapshot | None:
        """Get latest snapshot for symbol."""
        return self._snapshots.get(symbol)

    def health_check(self) -> dict:
        """Return health status with actual data flow validation."""
        import time

        now = time.time()
        stale_threshold = 30  # seconds

        # Check for stale snapshots (no updates in 30s = no real data)
        fresh_snapshots = 0
        stale_symbols = []
        for symbol, snapshot in self._snapshots.items():
            if now - snapshot.timestamp < stale_threshold:
                fresh_snapshots += 1
            else:
                stale_symbols.append(symbol)

        # Data is only healthy if we have fresh snapshots for subscribed symbols
        subscribed = len(self._contract_map)
        data_healthy = fresh_snapshots > 0 and fresh_snapshots >= subscribed * 0.5

        return {
            "connected": self._running,
            "symbols_subscribed": subscribed,
            "symbols_with_data": len(self._snapshots),
            "fresh_snapshots": fresh_snapshots,
            "stale_symbols": stale_symbols,
            "data_healthy": data_healthy,
        }
