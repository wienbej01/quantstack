"""1-minute bar data feed using IBKR real-time bars."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from ib_insync import Contract, RealTimeBar, Stock

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


@dataclass
class Bar:
    """1-minute OHLCV bar."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BarFeed:
    """Real-time 1-minute bar feed using IBKR."""

    def __init__(self, session, config: dict):
        self.session = session
        self.config = config
        self._callbacks: list[Callable[[Bar], None]] = []
        self._contracts: dict[str, Contract] = {}
        self._bar_lists: dict[int, str] = {}  # Map RealTimeBarList id -> symbol
        self._lock = threading.Lock()
        self._running = False

    def add_callback(self, callback: Callable[[Bar], None]) -> None:
        """Register callback for bar updates."""
        self._callbacks.append(callback)

    def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to 1-min bars for symbols."""
        for symbol in symbols:
            if symbol in self._contracts:
                continue

            contract = Stock(symbol, "SMART", "USD")
            self._contracts[symbol] = contract

            try:
                # Request 5-second real-time bars (aggregate to 1-min in strategy)
                bar_list = self.session.call(
                    self.session.ib.reqRealTimeBars,
                    contract,
                    5,  # 5-second bars (minimum)
                    "TRADES",
                    False,  # useRTH
                    [],
                    timeout=10,
                )
                # Map bar_list to symbol for lookup in callback
                self._bar_lists[id(bar_list)] = symbol
                logger.info(f"Subscribed to bars for {symbol}")
            except Exception as e:
                logger.error(f"Failed to subscribe to {symbol}: {e}")

        # Hook bar event
        self.session.call_soon(self._attach_bar_handler)
        self._running = True

    def unsubscribe_all(self) -> None:
        """Cancel all bar subscriptions."""
        self._running = False
        for symbol, contract in self._contracts.items():
            try:
                self.session.call(
                    self.session.ib.cancelRealTimeBars,
                    contract,
                    timeout=5,
                )
            except Exception as e:
                logger.warning(f"Failed to unsubscribe {symbol}: {e}")
        self._contracts.clear()

    def _attach_bar_handler(self) -> None:
        """Attach real-time bar event handler."""
        self.session.ib.barUpdateEvent += self._on_bar_update

    def _on_bar_update(self, bars, has_new_bar: bool) -> None:
        """Handle incoming bar updates."""
        if not has_new_bar or not self._running:
            return

        # bars is a RealTimeBarList - get symbol from our mapping
        symbol = self._bar_lists.get(id(bars))
        if not symbol:
            logger.warning(f"Bar update for unknown list id={id(bars)}")
            return

        # Get the latest bar
        if not bars:
            return
        
        bar = bars[-1]  # Most recent bar

        # Convert to Bar dataclass
        bar_data = Bar(
            symbol=symbol,
            timestamp=datetime.now(ET),
            open=bar.open_,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=float(bar.volume),
        )

        logger.info(f"Bar: {symbol} C={bar.close:.2f} V={bar.volume:.0f}")

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(bar_data)
            except Exception as e:
                logger.error(f"Bar callback error for {symbol}: {e}")


class AggregatedBarFeed:
    """Aggregates 5-second bars into 1-minute bars."""

    def __init__(self, session, config: dict):
        self._bar_feed = BarFeed(session, config)
        self._callbacks: list[Callable[[Bar], None]] = []
        self._pending: dict[str, list[Bar]] = {}
        self._last_minute: dict[str, int] = {}
        self._lock = threading.Lock()

        self._bar_feed.add_callback(self._on_5s_bar)

    def add_callback(self, callback: Callable[[Bar], None]) -> None:
        """Register callback for 1-minute bar updates."""
        self._callbacks.append(callback)

    def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to 1-min bars for symbols."""
        self._bar_feed.subscribe(symbols)

    def unsubscribe_all(self) -> None:
        """Cancel all subscriptions."""
        self._bar_feed.unsubscribe_all()

    def _on_5s_bar(self, bar: Bar) -> None:
        """Aggregate 5-second bars into 1-minute bars."""
        current_minute = bar.timestamp.minute

        with self._lock:
            last_minute = self._last_minute.get(bar.symbol)

            # New minute started - emit aggregated bar
            if last_minute is not None and current_minute != last_minute:
                pending = self._pending.get(bar.symbol, [])
                if pending:
                    agg_bar = self._aggregate(bar.symbol, pending)
                    self._emit(agg_bar)
                self._pending[bar.symbol] = []

            # Accumulate bar
            if bar.symbol not in self._pending:
                self._pending[bar.symbol] = []
            self._pending[bar.symbol].append(bar)
            self._last_minute[bar.symbol] = current_minute

    def _aggregate(self, symbol: str, bars: list[Bar]) -> Bar:
        """Aggregate list of bars into single bar."""
        return Bar(
            symbol=symbol,
            timestamp=bars[-1].timestamp,
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
        )

    def _emit(self, bar: Bar) -> None:
        """Emit aggregated bar to callbacks."""
        for callback in self._callbacks:
            try:
                callback(bar)
            except Exception as e:
                logger.error(f"1-min bar callback error for {bar.symbol}: {e}")
