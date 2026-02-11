"""Order placement helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ib_insync import Contract, LimitOrder, MarketOrder, Order, Trade
from qx_broker.ibkr.config import IBKROrderConfig
from qx_broker.ibkr.connection import IBKRSession
from qx_broker.ibkr.rate_limit import CancelRateLimiter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderResult:
    trade: Trade
    order_ref: str


class IBKROrderManager:
    def __init__(self, session: IBKRSession, config: IBKROrderConfig) -> None:
        self.session = session
        self.config = config
        self.config.validate()
        self._cancel_limiter = CancelRateLimiter(self.config.min_cancel_interval_sec)

    def place_market(
        self,
        contract: Contract,
        action: str,
        quantity: int,
        strategy: str | None = None,
    ) -> OrderResult:
        order = MarketOrder(action, quantity)
        return self._place_order(contract, order, strategy)

    def place_limit(
        self,
        contract: Contract,
        action: str,
        quantity: int,
        limit_price: float,
        strategy: str | None = None,
    ) -> OrderResult:
        order = LimitOrder(action, quantity, limit_price)
        return self._place_order(contract, order, strategy)

    def place_order(
        self, contract: Contract, order: Order, strategy: str | None = None
    ) -> OrderResult:
        return self._place_order(contract, order, strategy)

    def what_if(self, contract: Contract, order: Order):
        return self.session.call(
            self.session.ib.whatIfOrder, contract, order, timeout=10
        )

    def place_bracket(
        self,
        contract: Contract,
        action: str,
        quantity: int,
        limit_price: float,
        take_profit_price: float,
        stop_loss_price: float,
        strategy: str | None = None,
    ) -> list[OrderResult]:
        orders = self.session.call(
            self.session.ib.bracketOrder,
            action,
            quantity,
            limit_price,
            take_profit_price,
            stop_loss_price,
            timeout=10,
        )
        results: list[OrderResult] = []
        for order in orders:
            results.append(self._place_order(contract, order, strategy))
        return results

    def cancel_order(self, trade: Trade) -> None:
        if trade is None or trade.order is None:
            return
        order_id = getattr(trade.order, "orderId", None)
        if order_id is not None and not self._cancel_limiter.allow(int(order_id)):
            logger.debug("Cancel throttled for order %s", order_id)
            return
        self.session.call(self.session.ib.cancelOrder, trade.order, timeout=5)

    def open_trades(self) -> list[Trade]:
        return self.session.call(self.session.ib.openTrades, timeout=10)

    def open_orders(self) -> list[Order]:
        return self.session.call(self.session.ib.openOrders, timeout=10)

    def fills(self):
        return self.session.call(self.session.ib.fills, timeout=10)

    def executions(self):
        return self.session.call(self.session.ib.executions, timeout=10)

    def _place_order(
        self, contract: Contract, order: Order, strategy: str | None
    ) -> OrderResult:
        order_ref = order.orderRef or self._build_order_ref(strategy, contract.symbol)
        order.orderRef = order_ref
        if self.config.account:
            order.account = self.config.account
        trade = self.session.call(
            self.session.ib.placeOrder, contract, order, timeout=10
        )
        return OrderResult(trade=trade, order_ref=order_ref)

    def _build_order_ref(self, strategy: str | None, symbol: str) -> str:
        parts = [
            self.session.config.system_name,
            str(self.session.active_client_id),
            self.config.order_ref_prefix,
        ]
        if strategy:
            parts.append(strategy)
        parts.append(symbol)
        return "_".join([part for part in parts if part])
