"""
L2 Scalping Order Manager - Platform-based implementation.

Replaces socket-based ib_insync with IBKR API Platform client.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from cpapi.platform_client import IBKRPlatformClient

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
    price: Optional[float] = None


class IBKROrderManager:
    """Order manager using IBKR API Platform."""

    def __init__(self, config: Dict):
        self.config = config
        self.client = IBKRPlatformClient("l2-scalping-orders", "L2 Scalping Orders")
        self.account_id = None

    def connect(self) -> bool:
        """Connect to IBKR API Platform."""
        try:
            success = self.client.register(["orders", "market-data", "positions"])
            if success and self.client.check_auth_status():
                # Get account
                accounts = self.client.get_accounts()
                if accounts:
                    self.account_id = accounts[0]
                    logger.info(f"Connected to platform, account: {self.account_id}")
                    return True
                else:
                    logger.error("No accounts available")
                    return False
            else:
                logger.error("Platform not authenticated")
                return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from platform."""
        try:
            self.client.unregister()
            logger.info("Disconnected from platform")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")

    def place_order(self, order: OrderRequest) -> Optional[str]:
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
                price=order.price,
            )

            if result:
                logger.info(
                    f"Order placed: {order.symbol} {order.side.value} {order.quantity}"
                )
                return str(result.get("id", "unknown"))
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
                logger.error("No account ID available")
                return False

            result = self.client.cancel_order(self.account_id, order_id)
            if result:
                logger.info(f"Order cancelled: {order_id}")
                return True
            else:
                logger.error(f"Failed to cancel order: {order_id}")
                return False

        except Exception as e:
            logger.error(f"Order cancellation error: {e}")
            return False

    def get_positions(self) -> List[Dict]:
        """Get current positions."""
        try:
            if not self.account_id:
                return []

            positions = self.client.get_positions(self.account_id)
            return positions

        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def get_orders(self) -> List[Dict]:
        """Get live orders."""
        try:
            orders = self.client.get_live_orders()
            return orders.get("orders", [])

        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []

    def heartbeat(self):
        """Send heartbeat to platform."""
        try:
            self.client.heartbeat()
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
