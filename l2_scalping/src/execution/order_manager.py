"""IBKR Order Management for L2 Scalping System

Handles order placement, tracking, and execution via IBKR API.
Based on ~/intraday_stack/docs/PAPER_TRADING_GUIDE.md patterns.
"""

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from queue import Queue
from typing import Callable, Dict, List, Optional

from ib_insync import IB, Fill, LimitOrder, Order, Stock, Trade
from ib_insync.objects import OrderStatus

logger = logging.getLogger(__name__)


class OrderType(Enum):
    LIMIT = "LMT"
    MARKET = "MKT"
    IOC = "IOC"  # Immediate or Cancel


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class OrderRequest:
    """Order request from strategy"""

    symbol: str
    side: OrderSide
    quantity: int
    price: Optional[float] = None
    order_type: OrderType = OrderType.LIMIT
    time_in_force: str = "DAY"
    client_order_id: Optional[str] = None


@dataclass
class OrderUpdate:
    """Order status update"""

    order_id: int
    client_order_id: Optional[str]
    symbol: str
    status: str
    filled_qty: int
    remaining_qty: int
    avg_fill_price: float
    timestamp: float


class IBKROrderManager:
    """IBKR order management with error handling and reconnection"""

    def __init__(self, config: Dict):
        self.config = config
        self.ib: Optional[IB] = None
        self.is_connected = False

        # Connection parameters
        self.host = config.get("ibkr_host", "127.0.0.1")
        self.port = config.get("ibkr_port", 7497)  # Paper trading port
        self.client_id = config.get("client_id", 1)

        # Order tracking
        self.active_orders: Dict[int, Trade] = {}
        self.order_updates: Queue = Queue()
        self.fill_callbacks: List[Callable] = []

        # Reconnection handling
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = config.get("max_reconnect_attempts", 5)
        self.reconnect_delay = config.get("reconnect_delay", 5)

        # Error handling
        self.error_callbacks: List[Callable] = []

        logger.info(
            f"IBKR Order Manager initialized: {self.host}:{self.port}, client_id={self.client_id}"
        )

    def connect(self) -> bool:
        """Connect to IBKR with error handling"""
        try:
            if self.ib and self.ib.isConnected():
                return True

            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=30)

            # Set up event handlers
            self.ib.orderStatusEvent += self._on_order_status
            self.ib.fillEvent += self._on_fill
            self.ib.errorEvent += self._on_error
            self.ib.disconnectedEvent += self._on_disconnect

            self.is_connected = True
            self.reconnect_attempts = 0

            logger.info(f"Connected to IBKR: {self.host}:{self.port}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from IBKR"""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
        self.is_connected = False
        logger.info("Disconnected from IBKR")

    def place_order(self, order_request: OrderRequest) -> Optional[int]:
        """Place order and return order ID"""
        if not self.is_connected:
            logger.error("Cannot place order: not connected to IBKR")
            return None

        try:
            # Create contract
            contract = Stock(order_request.symbol, "SMART", "USD")

            # Create order
            if order_request.order_type == OrderType.LIMIT:
                if order_request.price is None:
                    logger.error("Limit order requires price")
                    return None
                order = LimitOrder(
                    action=order_request.side.value,
                    totalQuantity=order_request.quantity,
                    lmtPrice=order_request.price,
                    tif=order_request.time_in_force,
                )
            elif order_request.order_type == OrderType.IOC:
                order = LimitOrder(
                    action=order_request.side.value,
                    totalQuantity=order_request.quantity,
                    lmtPrice=order_request.price,
                    tif="IOC",
                )
            else:
                logger.error(f"Unsupported order type: {order_request.order_type}")
                return None

            # Add client order ID if provided
            if order_request.client_order_id:
                order.orderRef = order_request.client_order_id

            # Place order
            trade = self.ib.placeOrder(contract, order)

            if trade and trade.order.orderId:
                self.active_orders[trade.order.orderId] = trade
                logger.info(
                    f"Placed order: {order_request.symbol} {order_request.side.value} "
                    f"{order_request.quantity}@{order_request.price} ID={trade.order.orderId}"
                )
                return trade.order.orderId
            else:
                logger.error("Failed to place order: no order ID returned")
                return None

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def cancel_order(self, order_id: int) -> bool:
        """Cancel order by ID"""
        if not self.is_connected:
            logger.error("Cannot cancel order: not connected to IBKR")
            return False

        try:
            if order_id in self.active_orders:
                trade = self.active_orders[order_id]
                self.ib.cancelOrder(trade.order)
                logger.info(f"Cancelled order ID: {order_id}")
                return True
            else:
                logger.warning(f"Order ID {order_id} not found in active orders")
                return False

        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    def cancel_all_orders(self) -> int:
        """Cancel all active orders"""
        cancelled_count = 0
        for order_id in list(self.active_orders.keys()):
            if self.cancel_order(order_id):
                cancelled_count += 1

        logger.info(f"Cancelled {cancelled_count} orders")
        return cancelled_count

    def get_order_status(self, order_id: int) -> Optional[OrderUpdate]:
        """Get current order status"""
        if order_id not in self.active_orders:
            return None

        trade = self.active_orders[order_id]
        order_status = trade.orderStatus

        return OrderUpdate(
            order_id=order_id,
            client_order_id=trade.order.orderRef,
            symbol=trade.contract.symbol,
            status=order_status.status,
            filled_qty=order_status.filled,
            remaining_qty=order_status.remaining,
            avg_fill_price=order_status.avgFillPrice,
            timestamp=time.time(),
        )

    def get_active_orders(self) -> List[OrderUpdate]:
        """Get all active order statuses"""
        return [self.get_order_status(oid) for oid in self.active_orders.keys()]

    def add_fill_callback(self, callback: Callable) -> None:
        """Add callback for order fills"""
        self.fill_callbacks.append(callback)

    def add_error_callback(self, callback: Callable) -> None:
        """Add callback for errors"""
        self.error_callbacks.append(callback)

    def _on_order_status(self, trade: Trade) -> None:
        """Handle order status updates"""
        order_id = trade.order.orderId
        status = trade.orderStatus.status

        # Create order update
        update = OrderUpdate(
            order_id=order_id,
            client_order_id=trade.order.orderRef,
            symbol=trade.contract.symbol,
            status=status,
            filled_qty=trade.orderStatus.filled,
            remaining_qty=trade.orderStatus.remaining,
            avg_fill_price=trade.orderStatus.avgFillPrice,
            timestamp=time.time(),
        )

        # Queue update for processing
        self.order_updates.put(update)

        # Remove from active orders if done
        if status in ["Filled", "Cancelled", "ApiCancelled"]:
            if order_id in self.active_orders:
                del self.active_orders[order_id]

        logger.debug(f"Order status update: {order_id} -> {status}")

    def _on_fill(self, trade: Trade, fill: Fill) -> None:
        """Handle order fills"""
        logger.info(
            f"Order filled: {trade.contract.symbol} "
            f"{fill.execution.shares}@{fill.execution.price}"
        )

        # Notify callbacks
        for callback in self.fill_callbacks:
            try:
                callback(trade, fill)
            except Exception as e:
                logger.error(f"Error in fill callback: {e}")

    def _on_error(
        self, reqId: int, errorCode: int, errorString: str, contract=None
    ) -> None:
        """Handle IBKR errors"""
        logger.error(f"IBKR Error {errorCode}: {errorString} (reqId={reqId})")

        # Critical errors that require reconnection
        critical_errors = [1100, 1101, 1102, 2104, 2106, 2108]
        if errorCode in critical_errors:
            logger.critical(
                f"Critical IBKR error {errorCode}, will attempt reconnection"
            )
            self.is_connected = False
            threading.Thread(target=self._attempt_reconnect, daemon=True).start()

        # Notify error callbacks
        for callback in self.error_callbacks:
            try:
                callback(reqId, errorCode, errorString, contract)
            except Exception as e:
                logger.error(f"Error in error callback: {e}")

    def _on_disconnect(self) -> None:
        """Handle disconnection"""
        logger.warning("IBKR connection lost")
        self.is_connected = False
        threading.Thread(target=self._attempt_reconnect, daemon=True).start()

    def _attempt_reconnect(self) -> None:
        """Attempt to reconnect to IBKR"""
        while (
            not self.is_connected
            and self.reconnect_attempts < self.max_reconnect_attempts
        ):

            self.reconnect_attempts += 1
            logger.info(
                f"Reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}"
            )

            time.sleep(self.reconnect_delay)

            if self.connect():
                logger.info("Reconnection successful")
                return

        logger.critical("Failed to reconnect to IBKR after maximum attempts")

    def get_next_order_update(self, timeout: float = 1.0) -> Optional[OrderUpdate]:
        """Get next order update from queue"""
        try:
            return self.order_updates.get(timeout=timeout)
        except:
            return None

    def health_check(self) -> Dict[str, any]:
        """Get connection health status"""
        return {
            "connected": self.is_connected,
            "active_orders": len(self.active_orders),
            "reconnect_attempts": self.reconnect_attempts,
            "pending_updates": self.order_updates.qsize(),
            "timestamp": time.time(),
        }
