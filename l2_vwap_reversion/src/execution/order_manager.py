"""Order execution for L2 VWAP Mean Reversion with bracket orders."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ib_insync import LimitOrder, MarketOrder, Order, Stock, Trade

from qx_broker.ibkr.rate_limit import CancelRateLimiter
logger = logging.getLogger(__name__)


def round_to_tick_size(price: float, tick_size: float = 0.01) -> float:
    """Round price to nearest tick size."""
    return round(price / tick_size) * tick_size


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class OrderResult:
    """Order execution result."""

    order_id: int
    symbol: str
    side: OrderSide
    quantity: int
    status: str
    filled_qty: int = 0
    avg_price: float = 0.0
    timestamp: datetime | None = None


@dataclass
class BracketOrderResult:
    """Bracket order result with parent and child order IDs."""

    parent_id: int
    stop_loss_id: int | None
    take_profit_id: int | None
    symbol: str
    side: OrderSide
    quantity: int


class OrderManager:
    """Order manager with bracket order support."""

    def __init__(self, session, config: dict):
        self.session = session
        self.config = config
        self._lock = threading.Lock()
        self._pending_orders: dict[int, Trade] = {}
        self._bracket_orders: dict[int, BracketOrderResult] = {}  # parent_id -> bracket
        self._events_attached = False
        self._account_id: str | None = None
        self._fill_callback = None  # Callback for fill events
        orders_cfg = config.get("ibkr", {}).get("orders", config.get("orders", {}))
        min_cancel_interval_sec = float(orders_cfg.get("min_cancel_interval_sec", 2.0))
        self._cancel_limiter = CancelRateLimiter(min_cancel_interval_sec)

    def connect(self) -> bool:
        """Ensure session is connected."""
        if not self.session.is_connected():
            if not self.session.connect():
                return False
        self._attach_events()
        self._resolve_account()
        return True

    def _resolve_account(self) -> None:
        """Resolve account ID from IBKR."""
        try:
            accounts = self.session.call(self.session.ib.managedAccounts, timeout=5)
            if accounts:
                self._account_id = accounts[0]
                logger.info(f"Using account: {self._account_id}")
        except Exception as e:
            logger.warning(f"Failed to resolve account: {e}")

    def _attach_events(self) -> None:
        """Attach order event handlers."""
        if self._events_attached:
            return

        def _register():
            self.session.ib.orderStatusEvent += self._on_order_status

        self.session.call_soon(_register)
        self._events_attached = True

    def set_fill_callback(self, callback) -> None:
        """Set callback for fill events: callback(order_id, symbol, side, filled_qty, avg_price, is_entry)."""
        self._fill_callback = callback

    def _on_order_status(self, trade: Trade) -> None:
        """Handle order status updates."""
        order_id = trade.order.orderId
        status = trade.orderStatus.status
        filled = trade.orderStatus.filled
        avg_price = trade.orderStatus.avgFillPrice

        logger.info(f"Order {order_id} status: {status}, filled={filled}, avgPrice={avg_price:.2f}")

        # Fire fill callback on Filled status
        if status == "Filled" and filled > 0 and avg_price > 0 and self._fill_callback:
            with self._lock:
                # Check if this is an entry (parent) or exit (SL/TP) order
                is_entry = order_id in self._bracket_orders
                bracket = self._bracket_orders.get(order_id)
                if bracket:
                    symbol = bracket.symbol
                    side = bracket.side.value
                else:
                    # Check if it's a child order
                    for parent_id, b in self._bracket_orders.items():
                        if order_id in (b.stop_loss_id, b.take_profit_id):
                            symbol = b.symbol
                            side = "SELL" if b.side == OrderSide.BUY else "BUY"
                            is_entry = False
                            break
                    else:
                        # Market exit order
                        symbol = getattr(trade.contract, "symbol", "")
                        side = trade.order.action
                        is_entry = False
            try:
                self._fill_callback(order_id, symbol, side, int(filled), float(avg_price), is_entry)
            except Exception as e:
                logger.error(f"Fill callback error: {e}")

        with self._lock:
            if order_id in self._pending_orders:
                if status in ("Filled", "Cancelled", "ApiCancelled"):
                    del self._pending_orders[order_id]

    def submit_bracket_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> BracketOrderResult | None:
        """Submit bracket order with stop-loss and take-profit."""
        try:
            contract = Stock(symbol, "SMART", "USD")
            self.session.call(self.session.ib.qualifyContracts, contract, timeout=10)

            action = "BUY" if side == OrderSide.BUY else "SELL"
            exit_action = "SELL" if side == OrderSide.BUY else "BUY"

            # Round prices to tick size
            stop_loss_price = round_to_tick_size(stop_loss_price)
            take_profit_price = round_to_tick_size(take_profit_price)

            # Parent order (market)
            parent = MarketOrder(action, quantity)
            parent.transmit = False
            parent.orderRef = f"VWAP_{symbol}_{datetime.now().strftime('%H%M%S')}"
            if self._account_id:
                parent.account = self._account_id

            parent_trade = self.session.call(self.session.ib.placeOrder, contract, parent, timeout=10)
            parent_id = parent_trade.order.orderId

            # Stop-loss order
            stop = Order()
            stop.orderId = self.session.ib.client.getReqId()
            stop.action = exit_action
            stop.orderType = "STP"
            stop.auxPrice = stop_loss_price
            stop.totalQuantity = quantity
            stop.parentId = parent_id
            stop.transmit = False
            stop.orderRef = f"VWAP_SL_{symbol}"
            if self._account_id:
                stop.account = self._account_id

            stop_trade = self.session.call(self.session.ib.placeOrder, contract, stop, timeout=10)
            stop_id = stop_trade.order.orderId

            # Take-profit order (transmit=True to send all)
            target = Order()
            target.orderId = self.session.ib.client.getReqId()
            target.action = exit_action
            target.orderType = "LMT"
            target.lmtPrice = take_profit_price
            target.totalQuantity = quantity
            target.parentId = parent_id
            target.transmit = True  # Transmit entire bracket
            target.orderRef = f"VWAP_TP_{symbol}"
            if self._account_id:
                target.account = self._account_id

            target_trade = self.session.call(self.session.ib.placeOrder, contract, target, timeout=10)
            target_id = target_trade.order.orderId

            result = BracketOrderResult(
                parent_id=parent_id,
                stop_loss_id=stop_id,
                take_profit_id=target_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

            with self._lock:
                self._pending_orders[parent_id] = parent_trade
                self._pending_orders[stop_id] = stop_trade
                self._pending_orders[target_id] = target_trade
                self._bracket_orders[parent_id] = result

            logger.info(
                f"Bracket order: {action} {quantity} {symbol} | "
                f"parent={parent_id}, SL={stop_loss_price:.2f} (id={stop_id}), "
                f"TP={take_profit_price:.2f} (id={target_id})"
            )

            return result

        except Exception as e:
            logger.error(f"Failed to submit bracket order for {symbol}: {e}")
            return None

    def submit_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
    ) -> OrderResult | None:
        """Submit simple market order (for exits)."""
        try:
            contract = Stock(symbol, "SMART", "USD")
            self.session.call(self.session.ib.qualifyContracts, contract, timeout=10)

            action = "BUY" if side == OrderSide.BUY else "SELL"
            order = MarketOrder(action, quantity)
            order.orderRef = f"VWAP_EXIT_{symbol}_{datetime.now().strftime('%H%M%S')}"
            if self._account_id:
                order.account = self._account_id

            trade = self.session.call(self.session.ib.placeOrder, contract, order, timeout=10)

            order_id = trade.order.orderId
            with self._lock:
                self._pending_orders[order_id] = trade

            logger.info(f"Market order: {action} {quantity} {symbol} (id={order_id})")

            return OrderResult(
                order_id=order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                status="Submitted",
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Failed to submit market order for {symbol}: {e}")
            return None

    def cancel_bracket(self, parent_id: int) -> bool:
        """Cancel bracket order and all children."""
        with self._lock:
            bracket = self._bracket_orders.get(parent_id)

        if not bracket:
            return False

        order_ids = [parent_id]
        if bracket.stop_loss_id:
            order_ids.append(bracket.stop_loss_id)
        if bracket.take_profit_id:
            order_ids.append(bracket.take_profit_id)

        for oid in order_ids:
            self.cancel_order(oid)

        return True

    def cancel_order(self, order_id: int) -> bool:
        """Cancel single order."""
        with self._lock:
            trade = self._pending_orders.get(order_id)

        if not trade:
            return False

        try:
            if not self._cancel_limiter.allow(int(order_id)):
                logger.debug("Cancel throttled for order %s", order_id)
                return False
            self.session.call(self.session.ib.cancelOrder, trade.order, timeout=5)
            logger.info(f"Cancelled order {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def cancel_all(self) -> None:
        """Cancel all pending orders."""
        with self._lock:
            order_ids = list(self._pending_orders.keys())

        logger.info(f"Cancelling {len(order_ids)} orders")
        for order_id in order_ids:
            self.cancel_order(order_id)

    def flatten_position(self, symbol: str, quantity: int, side: OrderSide) -> bool:
        """Flatten position with market order."""
        # Cancel any bracket orders for this symbol first
        with self._lock:
            for parent_id, bracket in list(self._bracket_orders.items()):
                if bracket.symbol == symbol:
                    self.cancel_bracket(parent_id)

        # Submit closing order
        close_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        result = self.submit_market_order(symbol, close_side, quantity)
        return result is not None

    def get_pending_count(self) -> int:
        """Get count of pending orders."""
        with self._lock:
            return len(self._pending_orders)
