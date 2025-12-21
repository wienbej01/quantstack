"""Real-time L2 Data Feed for Scalping System

Integrates with existing qx-l2 collector and provides real-time feature computation.
"""

import logging
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Callable, Dict, List, Optional

import pandas as pd
from ib_insync import IB, Stock, Ticker
from qx_l2.features import L2FeatureEngineer

logger = logging.getLogger(__name__)


@dataclass
class L2Snapshot:
    """Real-time L2 snapshot with computed features"""

    symbol: str
    timestamp: float
    # L1 data
    bid: float
    ask: float
    mid: float
    spread: float
    bid_size: float
    ask_size: float
    # L2 features
    obi_1: float
    obi_5: float
    depth_bid: float
    depth_ask: float
    pressure: float
    # Deltas (if available)
    d_mid_5s: float = 0.0
    d_obi_1_5s: float = 0.0


class L2DataFeed:
    """Real-time L2 data feed with feature computation"""

    def __init__(self, config: Dict):
        self.config = config
        self.ib: Optional[IB] = None
        self.is_connected = False
        self._loop_thread: Optional[threading.Thread] = None
        self._running = False

        # Connection parameters
        ibkr_cfg = config.get("ibkr", config)
        self.host = ibkr_cfg.get("host", "127.0.0.1")
        self.port = ibkr_cfg.get("port", 7497)
        self.client_id = ibkr_cfg.get("data_client_id", 2)

        # Subscribed symbols
        market_cfg = config.get("market_data", {})
        self.symbols = market_cfg.get("symbols", [])
        self.contracts: Dict[str, Stock] = {}
        self.tickers: Dict[str, Ticker] = {}

        # Feature engineering
        self.feature_engineers: Dict[str, L2FeatureEngineer] = {}
        self.depth_levels = market_cfg.get("depth_levels", 10)
        self.smart_depth = market_cfg.get("smart_depth", False)
        self.exchange = market_cfg.get("exchange", "NYSE")

        # Data callbacks
        self.data_callbacks: List[Callable[[L2Snapshot], None]] = []

        # Data history for delta computation
        self.history: Dict[str, List[L2Snapshot]] = {}
        self.max_history = config.get("max_history_points", 120)  # 1 minute at 2Hz

        logger.info(f"L2 Data Feed initialized for symbols: {self.symbols}")

    def connect(self) -> bool:
        """Connect to IBKR for market data"""
        try:
            if self.ib and self.ib.isConnected():
                return True

            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=30)

            # Set up event handlers
            self.ib.pendingTickersEvent += self._on_ticker_update
            self.ib.errorEvent += self._on_error

            self.is_connected = True
            self._running = True
            self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._loop_thread.start()
            logger.info(f"Connected to IBKR for market data: {self.host}:{self.port}")

            # Subscribe to symbols
            self._subscribe_symbols()

            return True

        except Exception as e:
            logger.error(f"Failed to connect to IBKR for market data: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from IBKR"""
        self._running = False
        if self._loop_thread:
            self._loop_thread.join(timeout=1)
        if self.ib and self.ib.isConnected():
            # Cancel all subscriptions
            for ticker in self.tickers.values():
                self.ib.cancelMktData(ticker.contract)

            self.ib.disconnect()

        self.is_connected = False
        self.tickers.clear()
        logger.info("Disconnected from IBKR market data")

    def _subscribe_symbols(self) -> None:
        """Subscribe to L2 data for all symbols"""
        for symbol in self.symbols:
            try:
                contract = Stock(symbol, self.exchange, "USD")

                # Request market depth (L2)
                ticker = self.ib.reqMktDepth(
                    contract, numRows=self.depth_levels, isSmartDepth=self.smart_depth
                )

                if ticker:
                    self.contracts[symbol] = contract
                    self.tickers[symbol] = ticker

                    # Initialize feature engineer
                    self.feature_engineers[symbol] = L2FeatureEngineer(self.config)

                    # Initialize history
                    self.history[symbol] = []

                    logger.info(f"Subscribed to L2 data: {symbol}")
                else:
                    logger.error(f"Failed to subscribe to {symbol}")

            except Exception as e:
                logger.error(f"Error subscribing to {symbol}: {e}")

    def _on_ticker_update(self, tickers: List[Ticker]) -> None:
        """Handle ticker updates"""
        for ticker in tickers:
            if ticker.contract.symbol in self.symbols:
                self._process_ticker_update(ticker)

    def _process_ticker_update(self, ticker: Ticker) -> None:
        """Process individual ticker update"""
        symbol = ticker.contract.symbol

        try:
            # Extract L1 data
            if not (ticker.bid and ticker.ask and ticker.bidSize and ticker.askSize):
                return  # Skip incomplete data

            bid = float(ticker.bid)
            ask = float(ticker.ask)
            mid = (bid + ask) / 2
            spread = ask - bid
            bid_size = float(ticker.bidSize)
            ask_size = float(ticker.askSize)

            # Calculate OBI at level 1
            total_size = bid_size + ask_size
            obi_1 = (bid_size - ask_size) / total_size if total_size > 0 else 0.0

            # Extract L2 depth data
            depth_bid = 0.0
            depth_ask = 0.0
            obi_5 = 0.0

            if hasattr(ticker, "domBids") and hasattr(ticker, "domAsks"):
                dom_bids = ticker.domBids or []
                dom_asks = ticker.domAsks or []

                # Sum depth
                for i in range(min(10, len(dom_bids))):
                    if dom_bids[i].size:
                        depth_bid += float(dom_bids[i].size)

                for i in range(min(10, len(dom_asks))):
                    if dom_asks[i].size:
                        depth_ask += float(dom_asks[i].size)

                # Calculate OBI at level 5
                if len(dom_bids) >= 5 and len(dom_asks) >= 5:
                    bid_5 = float(dom_bids[4].size) if dom_bids[4].size else 0.0
                    ask_5 = float(dom_asks[4].size) if dom_asks[4].size else 0.0
                    total_5 = bid_5 + ask_5
                    obi_5 = (bid_5 - ask_5) / total_5 if total_5 > 0 else 0.0

            pressure = depth_bid - depth_ask

            # Create snapshot
            snapshot = L2Snapshot(
                symbol=symbol,
                timestamp=time.time(),
                bid=bid,
                ask=ask,
                mid=mid,
                spread=spread,
                bid_size=bid_size,
                ask_size=ask_size,
                obi_1=obi_1,
                obi_5=obi_5,
                depth_bid=depth_bid,
                depth_ask=depth_ask,
                pressure=pressure,
            )

            # Compute deltas if we have history
            self._compute_deltas(snapshot)

            # Store in history
            self.history[symbol].append(snapshot)
            if len(self.history[symbol]) > self.max_history:
                self.history[symbol].pop(0)

            # Notify callbacks
            for callback in self.data_callbacks:
                try:
                    callback(snapshot)
                except Exception as e:
                    logger.error(f"Error in data callback: {e}")

        except Exception as e:
            logger.error(f"Error processing ticker update for {symbol}: {e}")

    def _compute_deltas(self, snapshot: L2Snapshot) -> None:
        """Compute delta features from history"""
        symbol = snapshot.symbol
        history = self.history.get(symbol, [])

        if len(history) < 10:  # Need at least 10 points for 5s delta at 2Hz
            return

        # 5-second delta (10 points back at 2Hz)
        if len(history) >= 10:
            old_snapshot = history[-10]
            snapshot.d_mid_5s = snapshot.mid - old_snapshot.mid
            snapshot.d_obi_1_5s = snapshot.obi_1 - old_snapshot.obi_1

    def _on_error(
        self, reqId: int, errorCode: int, errorString: str, contract=None
    ) -> None:
        """Handle IBKR errors"""
        logger.error(f"IBKR Data Error {errorCode}: {errorString}")

        # Handle critical errors
        if errorCode in [1100, 1101, 1102]:
            logger.critical("Critical data connection error, reconnecting...")
            self.is_connected = False
            threading.Thread(target=self._reconnect, daemon=True).start()

    def _reconnect(self) -> None:
        """Attempt to reconnect"""
        time.sleep(5)
        logger.info("Attempting to reconnect data feed...")
        self.connect()

    def add_data_callback(self, callback: Callable[[L2Snapshot], None]) -> None:
        """Add callback for data updates"""
        self.data_callbacks.append(callback)

    def _run_loop(self) -> None:
        """Run IBKR event loop"""
        while self._running and self.ib and self.ib.isConnected():
            try:
                self.ib.sleep(0.1)
            except Exception as e:
                logger.error(f"Data feed loop error: {e}")
                break

    def get_latest_snapshot(self, symbol: str) -> Optional[L2Snapshot]:
        """Get latest snapshot for symbol"""
        history = self.history.get(symbol, [])
        return history[-1] if history else None

    def get_symbol_history(self, symbol: str, count: int = 10) -> List[L2Snapshot]:
        """Get recent history for symbol"""
        history = self.history.get(symbol, [])
        return history[-count:] if len(history) >= count else history

    def health_check(self) -> Dict[str, any]:
        """Get data feed health status"""
        return {
            "connected": self.is_connected,
            "subscribed_symbols": len(self.tickers),
            "data_points": {symbol: len(hist) for symbol, hist in self.history.items()},
            "timestamp": time.time(),
        }


class MockL2DataFeed:
    """Mock data feed for testing (REMOVE BEFORE PAPER TRADING)"""

    def __init__(self, config: Dict):
        self.config = config
        self.symbols = config.get("symbols", ["PFE", "HAL", "LUV"])
        self.data_callbacks: List[Callable[[L2Snapshot], None]] = []
        self.is_running = False
        self._thread: Optional[threading.Thread] = None

        # Mock data parameters
        self.base_prices = {"PFE": 25.50, "HAL": 27.80, "LUV": 45.20}
        self.last_obi = {symbol: 0.0 for symbol in self.symbols}

        logger.warning("MOCK DATA FEED INITIALIZED - REMOVE BEFORE PAPER TRADING")

    def connect(self) -> bool:
        """Mock connection"""
        self.is_running = True
        self._thread = threading.Thread(target=self._generate_mock_data, daemon=True)
        self._thread.start()
        logger.info("Mock data feed started")
        return True

    def disconnect(self) -> None:
        """Mock disconnection"""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=1)
        logger.info("Mock data feed stopped")

    def _generate_mock_data(self) -> None:
        """Generate mock L2 data"""
        import random

        while self.is_running:
            for symbol in self.symbols:
                # Generate realistic L2 data
                base_price = self.base_prices[symbol]
                spread = 0.01 + random.random() * 0.02  # 1-3 cent spread

                bid = base_price - spread / 2
                ask = base_price + spread / 2
                mid = (bid + ask) / 2

                # Generate OBI with some persistence
                obi_change = random.gauss(0, 0.1)
                new_obi = max(
                    -0.95, min(0.95, self.last_obi[symbol] * 0.9 + obi_change)
                )
                self.last_obi[symbol] = new_obi

                snapshot = L2Snapshot(
                    symbol=symbol,
                    timestamp=time.time(),
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    spread=spread,
                    bid_size=100 + random.randint(0, 500),
                    ask_size=100 + random.randint(0, 500),
                    obi_1=new_obi,
                    obi_5=new_obi * 0.8 + random.gauss(0, 0.05),
                    depth_bid=5000 + random.randint(-1000, 1000),
                    depth_ask=5000 + random.randint(-1000, 1000),
                    pressure=random.gauss(0, 1000),
                )

                # Notify callbacks
                for callback in self.data_callbacks:
                    try:
                        callback(snapshot)
                    except Exception as e:
                        logger.error(f"Error in mock data callback: {e}")

            time.sleep(0.5)  # 2Hz

    def add_data_callback(self, callback: Callable[[L2Snapshot], None]) -> None:
        """Add callback for data updates"""
        self.data_callbacks.append(callback)

    def health_check(self) -> Dict[str, any]:
        """Mock health check"""
        return {
            "connected": self.is_running,
            "subscribed_symbols": len(self.symbols),
            "mock_mode": True,
            "timestamp": time.time(),
        }
