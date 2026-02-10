"""L1 market data helpers."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from ib_insync import Contract, Ticker

from qx_broker.ibkr.connection import IBKRSession
from qx_broker.ibkr.config import IBKRMarketDataConfig


@dataclass(frozen=True)
class L1Snapshot:
    symbol: str
    timestamp: float
    bid: float | None
    ask: float | None
    last: float | None
    bid_size: float | None
    ask_size: float | None
    last_size: float | None
    volume: float | None


class IBKRMarketData:
    def __init__(self, session: IBKRSession, config: IBKRMarketDataConfig) -> None:
        self.session = session
        self.config = config
        self.config.validate()
        self._lock = threading.Lock()
        self._tickers: dict[str, Ticker] = {}
        self._last_update: dict[str, float] = {}
        self._event_hooked = False

    def set_market_data_type(self, market_data_type: int | None = None) -> None:
        data_type = market_data_type if market_data_type is not None else self.config.market_data_type
        self.session.call(self.session.ib.reqMarketDataType, data_type, timeout=5)

    def subscribe(self, contract: Contract, snapshot: bool | None = None) -> Ticker:
        if snapshot is None:
            snapshot = self.config.snapshot
        self.set_market_data_type()
        ticker = self.session.call(
            self.session.ib.reqMktData,
            contract,
            self.config.generic_ticks,
            snapshot,
            False,
            [],
            timeout=10,
        )
        symbol = contract.symbol
        with self._lock:
            self._tickers[symbol] = ticker
        self._ensure_event_hook()
        return ticker

    def cancel(self, contract: Contract) -> None:
        self.session.call(self.session.ib.cancelMktData, contract, timeout=5)
        with self._lock:
            self._tickers.pop(contract.symbol, None)
            self._last_update.pop(contract.symbol, None)

    def snapshot(self, symbol: str) -> L1Snapshot | None:
        with self._lock:
            ticker = self._tickers.get(symbol)
        if not ticker:
            return None
        return self._snapshot_from_ticker(symbol, ticker)

    def symbols(self) -> list[str]:
        with self._lock:
            return list(self._tickers.keys())

    def last_update_age(self, symbol: str) -> float | None:
        with self._lock:
            ts = self._last_update.get(symbol)
        if ts is None:
            return None
        return time.time() - ts

    def _ensure_event_hook(self) -> None:
        if self._event_hooked:
            return
        self.session.call_soon(self._attach_event_handlers)
        self._event_hooked = True

    def _attach_event_handlers(self) -> None:
        self.session.ib.pendingTickersEvent += self._on_pending_tickers

    def _on_pending_tickers(self, tickers: set[Ticker]) -> None:
        now = time.time()
        with self._lock:
            for ticker in tickers:
                if ticker.contract and ticker.contract.symbol:
                    self._last_update[ticker.contract.symbol] = now

    @staticmethod
    def _snapshot_from_ticker(symbol: str, ticker: Ticker) -> L1Snapshot:
        def _value(raw: float | None) -> float | None:
            if raw is None:
                return None
            if isinstance(raw, float) and math.isnan(raw):
                return None
            return float(raw)

        return L1Snapshot(
            symbol=symbol,
            timestamp=time.time(),
            bid=_value(ticker.bid),
            ask=_value(ticker.ask),
            last=_value(ticker.last),
            bid_size=_value(ticker.bidSize),
            ask_size=_value(ticker.askSize),
            last_size=_value(ticker.lastSize),
            volume=_value(ticker.volume),
        )
