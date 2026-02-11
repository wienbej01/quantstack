"""L2 market depth (DOM) helpers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ib_insync import Contract, DOMLevel, Ticker
from qx_broker.ibkr.config import IBKRDepthConfig
from qx_broker.ibkr.connection import IBKRSession


@dataclass(frozen=True)
class DepthLevel:
    price: float
    size: float
    market_maker: str | None


@dataclass(frozen=True)
class DepthSnapshot:
    symbol: str
    timestamp: float
    bids: list[DepthLevel]
    asks: list[DepthLevel]


class IBKRMarketDepth:
    def __init__(self, session: IBKRSession, config: IBKRDepthConfig) -> None:
        self.session = session
        self.config = config
        self.config.validate()
        self._lock = threading.Lock()
        self._tickers: dict[str, Ticker] = {}
        self._last_update: dict[str, float] = {}
        self._event_hooked = False

    def subscribe(
        self,
        contract: Contract,
        num_rows: int | None = None,
        smart_depth: bool | None = None,
    ) -> Ticker:
        if num_rows is None:
            num_rows = self.config.num_rows
        if smart_depth is None:
            smart_depth = self.config.smart_depth
        if num_rows < 1 or num_rows > 10:
            raise ValueError("num_rows must be between 1 and 5")

        with self._lock:
            if (
                contract.symbol not in self._tickers
                and len(self._tickers) >= self.config.max_symbols
            ):
                raise RuntimeError("Exceeded max_symbols for L2 depth subscriptions")

        ticker = self.session.call(
            self.session.ib.reqMktDepth,
            contract,
            num_rows,
            smart_depth,
            None,
            timeout=10,
        )
        with self._lock:
            self._tickers[contract.symbol] = ticker
        self._ensure_event_hook()
        return ticker

    def cancel(self, contract: Contract, smart_depth: bool | None = None) -> None:
        if smart_depth is None:
            smart_depth = self.config.smart_depth
        self.session.call(
            self.session.ib.cancelMktDepth, contract, smart_depth, timeout=5
        )
        with self._lock:
            self._tickers.pop(contract.symbol, None)
            self._last_update.pop(contract.symbol, None)

    def snapshot(self, symbol: str) -> DepthSnapshot | None:
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
                if ticker.contract and ticker.contract.symbol in self._tickers:
                    self._last_update[ticker.contract.symbol] = now

    @staticmethod
    def _levels_from_dom(levels: list[DOMLevel]) -> list[DepthLevel]:
        result: list[DepthLevel] = []
        for level in levels:
            result.append(
                DepthLevel(
                    price=float(level.price),
                    size=float(level.size),
                    market_maker=level.marketMaker,
                )
            )
        return result

    @classmethod
    def _snapshot_from_ticker(cls, symbol: str, ticker: Ticker) -> DepthSnapshot:
        bids = cls._levels_from_dom(list(ticker.domBids or []))
        asks = cls._levels_from_dom(list(ticker.domAsks or []))
        return DepthSnapshot(symbol=symbol, timestamp=time.time(), bids=bids, asks=asks)
