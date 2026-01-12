"""Enhanced IBKR Data Manager with System Identification."""

import logging

from ib_insync import IB, MarketOrder, Stock

logger = logging.getLogger(__name__)


class TaggedIBKRManager:
    """IBKR Manager with system identification and tagging."""

    def __init__(
        self,
        system_name: str,
        client_id: int,
        host: str = "127.0.0.1",
        port: int = 7497,
    ):
        """Initialize with system identification."""
        self.system_name = system_name
        self.client_id = client_id
        self.host = host
        self.port = port
        self.ib = IB()
        self.subscribed_symbols: dict[str, object] = {}
        self.order_ref_prefix = f"{system_name}_{client_id}"

    def connect(self) -> bool:
        """Connect with unique client ID."""
        if self.ib.isConnected():
            return True
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            logger.info(
                f"System '{self.system_name}' connected with client ID {self.client_id}"
            )
            return self.ib.isConnected()
        except Exception as e:
            logger.error(f"System '{self.system_name}' failed to connect: {e}")
            return False

    def place_tagged_order(
        self, symbol: str, action: str, quantity: int, strategy_tag: str = ""
    ):
        """Place order with system and strategy tags."""
        if not self.ib or not self.ib.isConnected():
            logger.error(f"System '{self.system_name}' not connected")
            return False

        try:
            contract = Stock(symbol, "NYSE", "USD")
            order = MarketOrder(action, quantity)
            order.orderRef = f"{self.order_ref_prefix}_{strategy_tag}_{symbol}"
            order.account = ""

            trade = self.ib.placeOrder(contract, order)

            logger.info(
                f"[{self.system_name}] Order placed: {action} {quantity} {symbol} "
                f"(ref: {order.orderRef})"
            )
            return trade

        except Exception as e:
            logger.error(f"[{self.system_name}] Order failed: {e}")
            return False

    def get_system_positions(self):
        """Get positions for this system only."""
        if not self.ib.isConnected():
            return []
        return self.ib.positions()

    def get_system_trades(self):
        """Get trades for this system (by order reference)."""
        if not self.ib.isConnected():
            return []

        all_trades = self.ib.trades()
        system_trades = [
            trade
            for trade in all_trades
            if trade.order.orderRef
            and trade.order.orderRef.startswith(self.order_ref_prefix)
        ]
        return system_trades


def create_quantstack_manager():
    """Create manager for Quantstack system."""
    return TaggedIBKRManager(system_name="QUANTSTACK", client_id=999)


def create_system2_manager():
    """Create manager for second system."""
    return TaggedIBKRManager(system_name="SYSTEM2", client_id=998)
