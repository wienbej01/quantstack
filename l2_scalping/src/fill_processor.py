"""Fill Processor for L2 Scalping System.

Processes IB fill callbacks, updates position/order state, and triggers TP/SL
placement and adjustment with time buffer logic.
"""

import logging
import time
from typing import Optional

from ib_insync import LimitOrder, StopOrder

from qx_broker.ibkr.rate_limit import CancelRateLimiter

from position_manager import PositionManager, ManagedPosition
from order_tracker import OrderTracker, TrackedOrder

logger = logging.getLogger(__name__)


class FillProcessor:
    """Processes fills and manages TP/SL order lifecycle."""
    
    TP_SL_UPDATE_BUFFER = 2.0  # seconds between TP/SL adjustments
    
    def __init__(
        self,
        position_manager: PositionManager,
        order_tracker: OrderTracker,
        ib_client,
        contracts: dict,
        tp_pct: float = 0.002,  # 0.2% TP
        sl_pct: float = 0.001,  # 0.1% SL
        min_cancel_interval_sec: float = 2.0,
    ):
        self.position_manager = position_manager
        self.order_tracker = order_tracker
        self.ib = ib_client
        self.contracts = contracts
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self._cancel_limiter = CancelRateLimiter(min_cancel_interval_sec)
    
    def process_fill(
        self,
        order_id: int,
        trade_id: str,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        is_partial: bool
    ) -> None:
        """Process a fill from IB callback."""
        # Update order tracker
        tracked_order = self.order_tracker.get_order(order_id)
        if not tracked_order:
            logger.warning(f"Fill for untracked order {order_id}")
            return
        
        # Update fill info
        self.order_tracker.update_fill(order_id, qty, price)
        
        # Route based on order intent
        if tracked_order.intent == "ENTRY":
            self._process_entry_fill(tracked_order, qty, price, is_partial)
        elif tracked_order.intent in ("TP", "SL"):
            self._process_exit_fill(tracked_order, qty, price, is_partial)
        else:
            logger.info(f"Fill for {tracked_order.intent} order {order_id}: {qty}@{price}")
    
    def _process_entry_fill(
        self, 
        order: TrackedOrder, 
        fill_qty: int, 
        fill_price: float,
        is_partial: bool
    ) -> None:
        """Process fill for entry order, manage TP/SL."""
        position = self.position_manager.get_position_by_order(order.order_id)
        if not position:
            logger.error(f"No position found for entry order {order.order_id}")
            return
        
        # Update position with fill
        old_qty = position.filled_qty
        self.position_manager.update_fill(order.order_id, fill_qty, fill_price)
        
        logger.info(
            f"Entry fill {order.symbol} trade={order.trade_id[:8]}: "
            f"{fill_qty}@{fill_price} (total: {position.filled_qty}/{position.target_qty})"
        )
        
        # Handle TP/SL placement/adjustment
        now = time.time()
        
        if not position.tp_sl_placed:
            # First fill - place TP/SL
            self._place_tp_sl(position)
            position.tp_sl_placed = True
            position.last_tp_sl_update = now
            logger.info(f"TP/SL placed for {position.symbol} trade={position.trade_id[:8]}")
        elif self.position_manager.can_update_tp_sl(order.order_id):
            # Subsequent fill with buffer elapsed - adjust TP/SL
            self._adjust_tp_sl(position)
            self.position_manager.mark_tp_sl_updated(order.order_id)
            logger.info(f"TP/SL adjusted for {position.symbol} trade={position.trade_id[:8]}")
        else:
            logger.debug(
                f"TP/SL adjustment skipped for {position.symbol} - buffer not elapsed"
            )
    
    def _process_exit_fill(
        self, 
        order: TrackedOrder, 
        fill_qty: int, 
        fill_price: float,
        is_partial: bool
    ) -> None:
        """Process fill for exit order (TP/SL)."""
        logger.info(
            f"Exit fill {order.symbol} trade={order.trade_id[:8]}: "
            f"{order.intent} {fill_qty}@{fill_price}"
        )
        
        # Find the position
        entry_order = self.order_tracker.get_entry_order_for_trade(order.trade_id)
        if not entry_order:
            logger.error(f"No entry order found for trade {order.trade_id}")
            return
        
        position = self.position_manager.get_position_by_order(entry_order.order_id)
        if not position:
            logger.error(f"No position found for trade {order.trade_id}")
            return
        
        # Update position status
        position.status = "CLOSING" if is_partial else "CLOSED"
        position.exit_fills.append({
            'qty': fill_qty,
            'price': fill_price,
            'reason': order.intent
        })
        
        # If fully closed, clean up
        if not is_partial:
            self._cleanup_position(position, order.intent)
    
    def _place_tp_sl(self, position: ManagedPosition) -> None:
        """Place initial TP/SL orders for position."""
        tp_price, sl_price, exit_side = self._calc_tp_sl_prices(position)
        
        # Create OCA group unique to this position
        oca_group = f"OCA_{position.trade_id[:8]}"
        
        try:
            # Place TP (limit order)
            tp_order = LimitOrder(exit_side, position.filled_qty, tp_price)
            tp_order.ocaGroup = oca_group
            tp_order.ocaType = 1  # Cancel other on fill
            tp_trade = self.ib.placeOrder(self.contracts[position.symbol], tp_order)
            
            # Place SL (stop order)
            sl_order = StopOrder(exit_side, position.filled_qty, sl_price)
            sl_order.ocaGroup = oca_group
            sl_order.ocaType = 1
            sl_trade = self.ib.placeOrder(self.contracts[position.symbol], sl_order)
            
            # Update position
            position.tp_order_id = tp_trade.order.orderId
            position.sl_order_id = sl_trade.order.orderId
            position.tp_price = tp_price
            position.sl_price = sl_price
            
            # Track orders
            self.order_tracker.add_order(
                position.tp_order_id, position.trade_id, position.symbol,
                "TP", exit_side, position.filled_qty, "LMT", limit_price=tp_price
            )
            self.order_tracker.add_order(
                position.sl_order_id, position.trade_id, position.symbol,
                "SL", exit_side, position.filled_qty, "STP", stop_price=sl_price
            )
            
            logger.info(
                f"TP/SL placed for {position.symbol} trade={position.trade_id[:8]}: "
                f"qty={position.filled_qty}, TP={tp_price:.4f}, SL={sl_price:.4f}"
            )
            
        except Exception as e:
            logger.error(f"Failed to place TP/SL for {position.symbol}: {e}")
    
    def _adjust_tp_sl(self, position: ManagedPosition) -> None:
        """Adjust existing TP/SL orders for new avg price and qty."""
        new_tp, new_sl, exit_side = self._calc_tp_sl_prices(position)
        
        try:
            # Cancel existing orders
            if position.tp_order_id:
                tp_order = self._get_order_by_id(position.tp_order_id)
                if tp_order:
                    self._cancel_order_if_allowed(tp_order)
            
            if position.sl_order_id:
                sl_order = self._get_order_by_id(position.sl_order_id)
                if sl_order:
                    self._cancel_order_if_allowed(sl_order)
            
            # Place new orders with updated qty and prices
            oca_group = f"OCA_{position.trade_id[:8]}"
            
            tp_order = LimitOrder(exit_side, position.filled_qty, new_tp)
            tp_order.ocaGroup = oca_group
            tp_order.ocaType = 1
            tp_trade = self.ib.placeOrder(self.contracts[position.symbol], tp_order)
            
            sl_order = StopOrder(exit_side, position.filled_qty, new_sl)
            sl_order.ocaGroup = oca_group
            sl_order.ocaType = 1
            sl_trade = self.ib.placeOrder(self.contracts[position.symbol], sl_order)
            
            # Update position
            old_tp_id, old_sl_id = position.tp_order_id, position.sl_order_id
            position.tp_order_id = tp_trade.order.orderId
            position.sl_order_id = sl_trade.order.orderId
            position.tp_price = new_tp
            position.sl_price = new_sl
            
            # Update tracker
            if old_tp_id:
                self.order_tracker.update_order_id(old_tp_id, position.tp_order_id)
            if old_sl_id:
                self.order_tracker.update_order_id(old_sl_id, position.sl_order_id)
            
            logger.info(
                f"TP/SL adjusted for {position.symbol} trade={position.trade_id[:8]}: "
                f"qty={position.filled_qty}, TP={new_tp:.4f}, SL={new_sl:.4f}"
            )
            
        except Exception as e:
            logger.error(f"Failed to adjust TP/SL for {position.symbol}: {e}")
    
    def _calc_tp_sl_prices(self, position: ManagedPosition) -> tuple[float, float, str]:
        """Calculate TP/SL prices from current avg fill price."""
        if position.direction == "long":
            tp = self._round_to_tick(position.avg_fill_price * (1 + self.tp_pct))
            sl = self._round_to_tick(position.avg_fill_price * (1 - self.sl_pct))
            side = "SELL"
        else:
            tp = self._round_to_tick(position.avg_fill_price * (1 - self.tp_pct))
            sl = self._round_to_tick(position.avg_fill_price * (1 + self.sl_pct))
            side = "BUY"
        return tp, sl, side
    
    def _round_to_tick(self, price: float) -> float:
        """Round price to tick size (0.01 for stocks)."""
        return round(price, 2)
    
    def _get_order_by_id(self, order_id: int):
        """Get IB order object by order_id."""
        for trade in self.ib.trades():
            if trade.order.orderId == order_id:
                return trade.order
        return None

    def _cancel_order_if_allowed(self, order) -> None:
        """Cancel order with per-order throttling."""
        if not order:
            return
        order_id = getattr(order, "orderId", None)
        if order_id is not None and not self._cancel_limiter.allow(int(order_id)):
            logger.debug("Cancel throttled for order %s", order_id)
            return
        self.ib.cancelOrder(order)
    
    def _cleanup_position(self, position: ManagedPosition, exit_reason: str) -> None:
        """Clean up position after full exit."""
        logger.info(
            f"Position closed {position.symbol} trade={position.trade_id[:8]}: "
            f"reason={exit_reason}, qty={position.filled_qty}@{position.avg_fill_price:.4f}"
        )
        
        # Cancel any remaining orders
        if exit_reason == "TP" and position.sl_order_id:
            sl_order = self._get_order_by_id(position.sl_order_id)
            if sl_order:
                self._cancel_order_if_allowed(sl_order)
        elif exit_reason == "SL" and position.tp_order_id:
            tp_order = self._get_order_by_id(position.tp_order_id)
            if tp_order:
                self._cancel_order_if_allowed(tp_order)
        
        # Remove from position manager
        self.position_manager.close_position(position.entry_order_id)
