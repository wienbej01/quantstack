"""Fill simulation for backtesting engine."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


def log_debug(msg):
    logging.debug(msg)


from .order import Order, OrderSide, OrderType


@dataclass
class Fill:
    """Fill representation for backtesting."""

    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: int
    commission: float = 0.0
    fees: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        """Validate fill after creation."""
        if self.quantity <= 0:
            raise ValueError("Fill quantity must be positive")

        if self.price <= 0:
            raise ValueError("Fill price must be positive")

    @property
    def total_cost(self) -> float:
        """Get total cost including commission and fees."""
        base_cost = self.quantity * self.price
        if self.side == OrderSide.BUY:
            return base_cost + self.commission + sum(self.fees.values())
        else:
            return base_cost - self.commission - sum(self.fees.values())

    def to_dict(self) -> dict[str, Any]:
        """Convert fill to dictionary representation."""
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "timestamp": self.timestamp,
            "commission": self.commission,
            "fees": self.fees,
            "total_cost": self.total_cost,
        }


class Filler(ABC):
    """Abstract base class for fill simulation."""

    @abstractmethod
    def simulate_fill(
        self, order: Order, bar_data: dict[str, Any], timestamp: int
    ) -> list[Fill]:
        """Simulate fills for an order against bar data.

        Args:
            order: The order to fill
            bar_data: Bar data for the symbol (OHLCV)
            timestamp: Current timestamp

        Returns:
            List of fills generated for this order
        """
        pass


class DefaultFiller(Filler):
    """Default fill simulation with realistic slippage and commission."""

    def __init__(
        self,
        commission_per_share: float = 0.0035,  # $0.0035 per share
        commission_min: float = 0.35,  # $0.35 minimum commission
        slippage_bps: int = 5,  # 5 basis points slippage
        partial_fill_probability: float = 0.3,  # 30% chance of partial fill
        max_partial_fill_ratio: float = 0.5,  # Maximum 50% fill for partial fills
        fill_probability: float = 0.95,  # 95% chance of fill for market orders
    ):
        """Initialize default filler with realistic parameters.

        Args:
            commission_per_share: Commission per share traded
            commission_min: Minimum commission per trade
            slippage_bps: Slippage in basis points
            partial_fill_probability: Probability of partial fill
            max_partial_fill_ratio: Maximum ratio for partial fills
            fill_probability: Probability of fill for marketable orders
        """
        self.commission_per_share = commission_per_share
        self.commission_min = commission_min
        self.slippage_bps = slippage_bps
        self.partial_fill_probability = partial_fill_probability
        self.max_partial_fill_ratio = max_partial_fill_ratio
        self.fill_probability = fill_probability
        self._fill_counter = 0

    def simulate_fill(
        self, order: Order, bar_data: dict[str, Any], timestamp: int
    ) -> list[Fill]:
        log_debug(f"Simulating fill for order {order.order_id}")
        fills = []

        if not order.is_active:
            return fills

        # Check if order can be filled based on price and type
        fill_price = self._get_fill_price(order, bar_data)
        if fill_price is None:
            return fills

        # Determine fill quantity
        fill_quantity = self._get_fill_quantity(order, bar_data)
        if fill_quantity <= 0:
            return fills

        # Apply commission
        commission = max(fill_quantity * self.commission_per_share, self.commission_min)

        # Create fill
        self._fill_counter += 1
        fill = Fill(
            fill_id=f"fill_{self._fill_counter:06d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_quantity,
            price=fill_price,
            timestamp=timestamp,
            commission=commission,
        )

        fills.append(fill)

        return fills

    def _get_fill_price(self, order: Order, bar_data: dict[str, Any]) -> float | None:
        """Get fill price for an order."""
        bar_data.get("open", 0)
        high_price = bar_data.get("high", 0)
        low_price = bar_data.get("low", 0)
        close_price = bar_data.get("close", 0)

        if order.order_type == OrderType.MARKET:
            # Market orders fill at current price with slippage
            base_price = close_price
            slippage_factor = 1 + (self.slippage_bps / 10000)

            # Buy orders fill higher (worse), sell orders fill lower (worse)
            if order.side == OrderSide.BUY:
                return base_price * slippage_factor
            else:
                return base_price / slippage_factor

        elif order.order_type == OrderType.LIMIT:
            # Limit orders fill only if price is favorable
            limit_price = order.price

            if order.side == OrderSide.BUY:
                # Buy order fills if bar's low price is <= limit price
                if low_price <= limit_price:
                    return min(limit_price, close_price)
            # Sell order fills if bar's high price is >= limit price
            elif high_price >= limit_price:
                return max(limit_price, close_price)

            return None

        elif order.order_type == OrderType.STOP:
            # Stop orders trigger if price crosses stop price
            stop_price = order.stop_price

            if order.side == OrderSide.BUY:
                # Buy stop triggers if high price >= stop price
                if high_price >= stop_price:
                    slippage_factor = 1 + (self.slippage_bps / 10000)
                    return max(stop_price, close_price) * slippage_factor
            # Sell stop triggers if low price <= stop price
            elif low_price <= stop_price:
                slippage_factor = 1 + (self.slippage_bps / 10000)
                return min(stop_price, close_price) / slippage_factor

            return None

        return None

    def _get_fill_quantity(self, order: Order, bar_data: dict[str, Any]) -> int:
        """Get fill quantity for an order."""
        return 1


class PerfectFiller(Filler):
    """Perfect fill simulation with no slippage or commission (for testing)."""

    def __init__(self):
        """Initialize perfect filler."""
        self._fill_counter = 0

    def simulate_fill(
        self, order: Order, bar_data: dict[str, Any], timestamp: int
    ) -> list[Fill]:
        """Simulate perfect fills."""
        fills = []

        if not order.is_active:
            return fills

        # Get fill price (no slippage)
        fill_price = self._get_fill_price(order, bar_data)
        if fill_price is None:
            return fills

        # Fill entire remaining quantity
        fill_quantity = order.remaining_quantity

        # Create fill
        self._fill_counter += 1
        fill = Fill(
            fill_id=f"fill_{self._fill_counter:06d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_quantity,
            price=fill_price,
            timestamp=timestamp,
            commission=0.0,
        )

        fills.append(fill)

        return fills

    def _get_fill_price(self, order: Order, bar_data: dict[str, Any]) -> float | None:
        """Get perfect fill price."""
        close_price = bar_data.get("close", 0)

        if order.order_type == OrderType.MARKET:
            return close_price

        elif order.order_type == OrderType.LIMIT:
            limit_price = order.price
            high_price = bar_data.get("high", 0)
            low_price = bar_data.get("low", 0)

            if order.side == OrderSide.BUY:
                if low_price <= limit_price:
                    return min(limit_price, close_price)
            elif high_price >= limit_price:
                return max(limit_price, close_price)

            return None

        elif order.order_type == OrderType.STOP:
            stop_price = order.stop_price
            high_price = bar_data.get("high", 0)
            low_price = bar_data.get("low", 0)

            if order.side == OrderSide.BUY:
                if high_price >= stop_price:
                    return max(stop_price, close_price)
            elif low_price <= stop_price:
                return min(stop_price, close_price)

            return None

        return None
