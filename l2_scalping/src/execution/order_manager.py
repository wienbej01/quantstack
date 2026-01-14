"""
L2 Scalping Order Manager - Platform-based implementation.

Replaces socket-based ib_insync with IBKR API Platform client.
"""

import logging
import queue
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable

sys.path.insert(0, "/home/jacobw/quantstack")
from cpapi.platform_client import IBKRPlatformClient
from cpapi.trading_notifications import send_trade_notification

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Order type."""
    MKT = "MKT"
    LMT = "LMT"


@dataclass
class OrderRequest:
    """Order request."""
    symbol: str
    quantity: int
    side: OrderSide
    order_type: OrderType = OrderType.MKT
    price: float | None = None


@dataclass
class OrderUpdate:
    """Order status update."""
    order_id: str
    symbol: str
    status: str
    filled_qty: int = 0
    avg_price: float = 0.0


class IBKROrderManager:
    """Order manager using IBKR API Platform."""

    def __init__(self, config: dict):
        self.config = config
        self.client = IBKRPlatformClient("l2-scalping-orders", "L2 Scalping Orders")
        self.account_id: str | None = None
        self._fill_callbacks: list[Callable] = []
        self._order_queue: queue.Queue = queue.Queue()
        self._running = False
        self._poll_thread: threading.Thread | None = None

    def connect(self) -> bool:
        """Connect to IBKR API Platform."""
        try:
            success = self.client.register(["orders", "market-data", "positions"])
            if success:
                # Get account
                accounts = self.client.get_accounts()
                if accounts:
                    self.account_id = accounts[0]
                    logger.info(f"Order Manager connected, account: {self.account_id}")
                    self._start_polling()
                    return True
                else:
                    logger.error("No accounts available")
                    return False
            else:
                logger.error("Order Manager failed to register with platform")
                return False
        except Exception as e:
            logger.error(f"Order Manager connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from platform."""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2)
        try:
            self.client.unregister()
            logger.info("Order Manager disconnected from platform")
        except Exception as e:
            logger.error(f"Order Manager disconnect error: {e}")

    def _start_polling(self):
        """Start background polling for order updates."""
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self):
        """Background polling loop for order updates."""
        while self._running:
            try:
                self._poll_orders()
                self.client.heartbeat()
                threading.Event().wait(1)  # 1 Hz polling
            except Exception as e:
                logger.error(f"Order poll error: {e}")
                threading.Event().wait(5)

    def _poll_orders(self):
        """Poll for order updates."""
        try:
            orders = self.client.get_live_orders()
            if orders and isinstance(orders, dict):
                for order in orders.get("orders", []):
                    update = OrderUpdate(
                        order_id=str(order.get("orderId", "")),
                        symbol=order.get("ticker", ""),
                        status=order.get("status", ""),
                        filled_qty=order.get("filledQuantity", 0),
                        avg_price=order.get("avgPrice", 0.0)
                    )
                    self._order_queue.put(update)
        except Exception as e:
            logger.error(f"Poll orders error: {e}")

    def place_order(self, order: OrderRequest) -> str | None:
        """Place an order."""
        try:
            if not self.account_id:
                logger.error("No account ID available")
                return None

            result = self.client.place_order(
                account_id=self.account_id,
                symbol=order.symbol,
                quantity=order.quantity,
                side=order.side.value,
                order_type=order.order_type.value,
                price=order.price
            )

            if result:
                order_id = str(result.get("id", result.get("orderId", "")))
                logger.info(f"Order placed: {order.symbol} {order.side.value} {order.quantity} -> {order_id}")
                
                # Send trade notification
                send_trade_notification(
                    action="ENTRY",
                    symbol=order.symbol,
                    strategy="L2 Scalping",
                    direction=order.side.value,
                    price=order.price or 0.0,
                    quantity=order.quantity
                )
                
                return order_id
            else:
                logger.error(f"Failed to place order: {order}")
                return None

        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            if not self.account_id:
                return False

            result = self.client.cancel_order(self.account_id, order_id)
            if result:
                logger.info(f"Order cancelled: {order_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Cancel order error: {e}")
            return False

    def cancel_all_orders(self):
        """Cancel all open orders."""
        try:
            orders = self.client.get_live_orders()
            if orders and isinstance(orders, dict):
                for order in orders.get("orders", []):
                    order_id = str(order.get("orderId", ""))
                    if order_id:
                        self.cancel_order(order_id)
        except Exception as e:
            logger.error(f"Cancel all orders error: {e}")

    def get_positions(self) -> list[dict]:
        """Get current positions."""
        try:
            if not self.account_id:
                return []
            return self.client.get_positions(self.account_id)
        except Exception as e:
            logger.error(f"Get positions error: {e}")
            return []

    def get_next_order_update(self, timeout: float = 0.1) -> OrderUpdate | None:
        """Get next order update from queue."""
        try:
            return self._order_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def add_fill_callback(self, callback: Callable):
        """Register a callback for order fills."""
        self._fill_callbacks.append(callback)

    def health_check(self) -> dict:
        """Return health status."""
        return {
            "connected": self._running,
            "account": self.account_id,
            "queue_size": self._order_queue.qsize()
        }
