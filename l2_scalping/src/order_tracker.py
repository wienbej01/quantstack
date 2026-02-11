"""Order Tracker for L2 Scalping System.

Tracks all orders by order_id, links orders to trade_id, and records order intent.
Maintains order status and fill information from IB callbacks.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TrackedOrder:
    """Represents a tracked order with trade linkage and intent."""

    order_id: int
    trade_id: str
    symbol: str
    intent: str  # ENTRY, TP, SL, FLATTEN
    side: str  # BUY, SELL
    quantity: int
    order_type: str  # MKT, LMT, STP
    limit_price: float = 0.0
    stop_price: float = 0.0
    status: str = "PENDING"  # PENDING, SUBMITTED, FILLED, CANCELLED
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    parent_order_id: int = 0


class OrderTracker:
    """Tracks all orders with trade linkage and intent."""

    def __init__(self):
        # Key: order_id -> TrackedOrder
        self.orders: dict[int, TrackedOrder] = {}
        # Index: trade_id -> list of order_ids
        self.trade_index: dict[str, list[int]] = {}

    def add_order(
        self,
        order_id: int,
        trade_id: str,
        symbol: str,
        intent: str,
        side: str,
        quantity: int,
        order_type: str,
        limit_price: float = 0.0,
        stop_price: float = 0.0,
        parent_order_id: int = 0,
    ) -> TrackedOrder:
        """Add new order to tracking."""
        order = TrackedOrder(
            order_id=order_id,
            trade_id=trade_id,
            symbol=symbol,
            intent=intent,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            parent_order_id=parent_order_id,
        )

        self.orders[order_id] = order

        # Add to trade index
        if trade_id not in self.trade_index:
            self.trade_index[trade_id] = []
        self.trade_index[trade_id].append(order_id)

        return order

    def get_order(self, order_id: int) -> Optional[TrackedOrder]:
        """Get order by order_id."""
        return self.orders.get(order_id)

    def get_orders_for_trade(self, trade_id: str) -> list[TrackedOrder]:
        """Get all orders for a trade_id."""
        order_ids = self.trade_index.get(trade_id, [])
        return [self.orders[oid] for oid in order_ids if oid in self.orders]

    def get_orders_by_intent(self, trade_id: str, intent: str) -> list[TrackedOrder]:
        """Get orders for a trade with specific intent."""
        return [
            order
            for order in self.get_orders_for_trade(trade_id)
            if order.intent == intent
        ]

    def update_status(self, order_id: int, status: str) -> Optional[TrackedOrder]:
        """Update order status."""
        order = self.orders.get(order_id)
        if order:
            order.status = status
        return order

    def update_fill(
        self, order_id: int, filled_qty: int, avg_fill_price: float
    ) -> Optional[TrackedOrder]:
        """Update order fill information."""
        order = self.orders.get(order_id)
        if order:
            order.filled_qty = filled_qty
            order.avg_fill_price = avg_fill_price

            # Update status based on fill
            if filled_qty >= order.quantity:
                order.status = "FILLED"
            elif filled_qty > 0:
                order.status = "PARTIALLY_FILLED"

        return order

    def update_order_id(self, old_order_id: int, new_order_id: int) -> bool:
        """Update order_id (for TP/SL replacement scenarios)."""
        order = self.orders.get(old_order_id)
        if not order:
            return False

        # Update order_id
        order.order_id = new_order_id

        # Move in orders dict
        self.orders[new_order_id] = order
        del self.orders[old_order_id]

        # Update trade index
        trade_orders = self.trade_index.get(order.trade_id, [])
        if old_order_id in trade_orders:
            idx = trade_orders.index(old_order_id)
            trade_orders[idx] = new_order_id

        return True

    def remove_order(self, order_id: int) -> Optional[TrackedOrder]:
        """Remove order from tracking."""
        order = self.orders.get(order_id)
        if not order:
            return None

        # Remove from orders
        del self.orders[order_id]

        # Remove from trade index
        trade_orders = self.trade_index.get(order.trade_id, [])
        if order_id in trade_orders:
            trade_orders.remove(order_id)
            if not trade_orders:
                del self.trade_index[order.trade_id]

        return order

    def is_entry_order(self, order_id: int) -> bool:
        """Check if order is an entry order."""
        order = self.orders.get(order_id)
        return order is not None and order.intent == "ENTRY"

    def is_exit_order(self, order_id: int) -> bool:
        """Check if order is an exit order (TP or SL)."""
        order = self.orders.get(order_id)
        return order is not None and order.intent in ("TP", "SL")

    def get_entry_order_for_trade(self, trade_id: str) -> Optional[TrackedOrder]:
        """Get the entry order for a trade."""
        entry_orders = self.get_orders_by_intent(trade_id, "ENTRY")
        return entry_orders[0] if entry_orders else None

    def get_tp_order_for_trade(self, trade_id: str) -> Optional[TrackedOrder]:
        """Get the TP order for a trade."""
        tp_orders = self.get_orders_by_intent(trade_id, "TP")
        return tp_orders[0] if tp_orders else None

    def get_sl_order_for_trade(self, trade_id: str) -> Optional[TrackedOrder]:
        """Get the SL order for a trade."""
        sl_orders = self.get_orders_by_intent(trade_id, "SL")
        return sl_orders[0] if sl_orders else None

    def __len__(self) -> int:
        """Return number of tracked orders."""
        return len(self.orders)

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"OrderTracker({len(self.orders)} orders, {len(self.trade_index)} trades)"
        )
