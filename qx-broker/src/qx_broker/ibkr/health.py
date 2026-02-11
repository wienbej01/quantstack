"""Health checks for IBKR connectivity and data freshness."""

from __future__ import annotations

from dataclasses import dataclass, field

from qx_broker.ibkr.connection import IBKRSession
from qx_broker.ibkr.market_data import IBKRMarketData
from qx_broker.ibkr.market_depth import IBKRMarketDepth


@dataclass(frozen=True)
class IBKRHealth:
    connected: bool
    current_time_ok: bool
    l1_stale_symbols: list[str] = field(default_factory=list)
    l2_stale_symbols: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return (
            self.connected
            and self.current_time_ok
            and not self.l1_stale_symbols
            and not self.l2_stale_symbols
        )


class IBKRHealthChecker:
    def __init__(
        self,
        session: IBKRSession,
        market_data: IBKRMarketData | None = None,
        market_depth: IBKRMarketDepth | None = None,
    ) -> None:
        self.session = session
        self.market_data = market_data
        self.market_depth = market_depth

    def check(self, max_age_sec: float = 5.0) -> IBKRHealth:
        connected = self.session.is_connected()
        current_time_ok = self.session.check_connection() if connected else False
        l1_stale: list[str] = []
        l2_stale: list[str] = []

        if self.market_data:
            for symbol in self.market_data.symbols():
                age = self.market_data.last_update_age(symbol)
                if age is None or age > max_age_sec:
                    l1_stale.append(symbol)

        if self.market_depth:
            for symbol in self.market_depth.symbols():
                age = self.market_depth.last_update_age(symbol)
                if age is None or age > max_age_sec:
                    l2_stale.append(symbol)

        return IBKRHealth(
            connected=connected,
            current_time_ok=current_time_ok,
            l1_stale_symbols=l1_stale,
            l2_stale_symbols=l2_stale,
        )
