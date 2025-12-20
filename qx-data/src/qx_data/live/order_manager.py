"""Enhanced order management with system tagging and bracket orders."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from ib_insync import IB, LimitOrder, MarketOrder, Stock, StopOrder

logger = logging.getLogger(__name__)


@dataclass
class OrderIntent:
    """Order intent from ML strategy."""

    symbol: str
    direction: str  # 'long' or 'short'
    quantity: int
    entry_price: float
    stop_price: float
    target_price: float
    strategy: str = "regime_aware"
    signal_id: str = ""
    confidence: float = 0.0


class EnhancedPaperTrader:
    """Enhanced paper trader with order tagging and bracket orders."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        system_name: str = "QUANTSTACK",
        client_id: int = 999,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.system_name = system_name
        self.order_ref_prefix = f"{system_name}_{client_id}"
        self.ib = None
        self._contracts: Dict[str, Stock] = {}
        self._orders: Dict[int, dict] = {}
        self.active_trades: Dict[int, dict] = {}
        self.order_to_trade: Dict[int, int] = {}
        self.logger = logging.getLogger(__name__)

    def connect(self) -> bool:
        """Connect to IBKR with enhanced error handling."""
        try:
            from ib_insync import IB

            self.ib = IB()
            self.ib.connect(
                self.host, self.port, clientId=self.client_id, readonly=False
            )

            # Set up fill callback
            self.ib.execDetailsEvent += self._on_fill

            self.logger.info(
                f"Connected to IBKR for {self.system_name} (client_id={self.client_id})"
            )
            return True
        except Exception as e:
            self.logger.error(f"IBKR connection failed: {e}")
            return False

    def _get_contract(self, symbol: str) -> Stock:
        """Get or create qualified contract."""
        if symbol not in self._contracts:
            contract = Stock(symbol, "NYSE", "USD")  # NYSE-only routing
            self.ib.qualifyContracts(contract)
            self._contracts[symbol] = contract
        return self._contracts[symbol]

    def place_bracket_order(self, intent: OrderIntent) -> Optional[List[int]]:
        """Place bracket order with system tagging."""
        if not self.ib or not self.ib.isConnected():
            self.logger.error("Not connected to IBKR")
            return None

        try:
            contract = self._get_contract(intent.symbol)
            action = "BUY" if intent.direction == "long" else "SELL"
            reverse_action = "SELL" if intent.direction == "long" else "BUY"

            # Order reference for system identification
            order_ref = f"{self.order_ref_prefix}_{intent.strategy}_{intent.symbol}"

            # Get next order IDs
            parent_id = self.ib.client.getReqId()
            tp_id = self.ib.client.getReqId()
            sl_id = self.ib.client.getReqId()

            # Parent: Market order for entry
            parent = MarketOrder(action, intent.quantity)
            parent.orderId = parent_id
            parent.orderRef = order_ref
            parent.transmit = False

            # Take profit: Limit order
            take_profit = LimitOrder(
                reverse_action, intent.quantity, round(float(intent.target_price), 2)
            )
            take_profit.orderId = tp_id
            take_profit.parentId = parent_id
            take_profit.orderRef = f"{order_ref}_TP"
            take_profit.transmit = False

            # Stop loss: Stop order
            stop_loss = StopOrder(
                reverse_action, intent.quantity, round(float(intent.stop_price), 2)
            )
            stop_loss.orderId = sl_id
            stop_loss.parentId = parent_id
            stop_loss.orderRef = f"{order_ref}_SL"
            stop_loss.transmit = True

            # Place all orders
            order_ids = []
            for order in [parent, take_profit, stop_loss]:
                trade = self.ib.placeOrder(contract, order)
                self._orders[order.orderId] = {
                    "trade": trade,
                    "symbol": intent.symbol,
                    "action": order.action,
                }
                order_ids.append(order.orderId)

            # Track active trade
            self.active_trades[parent_id] = {
                "symbol": intent.symbol,
                "direction": intent.direction,
                "entry_qty": intent.quantity,
                "stop_id": sl_id,
                "target_id": tp_id,
                "confidence": intent.confidence,
                "timestamp": datetime.now(),
            }

            # Map child orders to parent
            self.order_to_trade[tp_id] = parent_id
            self.order_to_trade[sl_id] = parent_id

            self.logger.info(
                f"[{self.system_name}] Bracket: {action} {intent.quantity} {intent.symbol} "
                f"(conf={intent.confidence:.3f}, stop={intent.stop_price:.2f}, "
                f"target={intent.target_price:.2f})"
            )

            return order_ids

        except Exception as e:
            self.logger.error(f"Bracket order placement failed: {e}")
            return None

    def place_simple_order(self, symbol: str, action: str, quantity: int = 100) -> bool:
        """Place simple market order (legacy compatibility)."""
        # Calculate stop/target based on current price
        contract = self._get_contract(symbol)
        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(1)  # Wait for price

        current_price = ticker.last or ticker.close or 0
        if current_price <= 0:
            self.logger.error(f"No price data for {symbol}")
            return False

        # Simple 2% stop, 4% target
        if action == "BUY":
            stop_price = current_price * 0.98
            target_price = current_price * 1.04
            direction = "long"
        else:
            stop_price = current_price * 1.02
            target_price = current_price * 0.96
            direction = "short"

        intent = OrderIntent(
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            entry_price=current_price,
            stop_price=stop_price,
            target_price=target_price,
            strategy="simple",
            confidence=0.5,
        )

        return self.place_bracket_order(intent) is not None

    def _on_fill(self, trade, fill):
        """Handle fill events and detect trade exits."""
        order_id = fill.execution.orderId
        symbol = fill.contract.symbol
        side = fill.execution.side
        quantity = fill.execution.shares
        price = fill.execution.price

        self.logger.info(f"FILL: {symbol} {side} {quantity}@{price:.4f}")

        # Check if this is an exit order
        parent_id = self.order_to_trade.get(order_id)
        if parent_id and parent_id in self.active_trades:
            trade_info = self.active_trades[parent_id]

            # Determine exit reason
            if order_id == trade_info["stop_id"]:
                exit_reason = "STOP"
            elif order_id == trade_info["target_id"]:
                exit_reason = "TARGET"
            else:
                exit_reason = "EXIT"

            self.logger.info(f"Trade closed: {symbol} {exit_reason} @ {price:.4f}")
            del self.active_trades[parent_id]

    def get_positions(self) -> Dict[str, float]:
        """Get current positions."""
        if not self.ib or not self.ib.isConnected():
            return {}

        try:
            positions = self.ib.positions()
            return {pos.contract.symbol: pos.position for pos in positions}
        except Exception as e:
            self.logger.error(f"Failed to get positions: {e}")
            return {}

    def get_system_trades(self) -> List[dict]:
        """Get only trades belonging to this system."""
        if not self.ib or not self.ib.isConnected():
            return []

        all_trades = self.ib.trades()
        system_trades = []

        for trade in all_trades:
            ref = trade.order.orderRef or ""
            if ref.startswith(self.order_ref_prefix):
                system_trades.append(
                    {
                        "symbol": trade.contract.symbol,
                        "action": trade.order.action,
                        "qty": trade.order.totalQuantity,
                        "status": trade.orderStatus.status,
                        "ref": ref,
                    }
                )

        return system_trades

    def disconnect(self):
        """Disconnect from IBKR."""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            self.logger.info(f"Disconnected {self.system_name} from IBKR")
