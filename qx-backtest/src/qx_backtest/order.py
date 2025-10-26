"""Order management for backtesting engine."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderType(Enum):
    """Order types supported by the backtesting engine."""

    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP_LMT"


class OrderSide(Enum):
    """Order sides."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order status tracking."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TimeInForce(Enum):
    """Time in force instructions."""

    DAY = "DAY"
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill


@dataclass
class Order:
    """Order representation for backtesting."""

    # Basic order attributes
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int

    # Optional order attributes
    price: float | None = None  # For limit orders
    stop_price: float | None = None  # For stop orders
    time_in_force: TimeInForce = TimeInForce.DAY

    # Metadata
    timestamp: int = field(
        default_factory=lambda: int(datetime.now().timestamp() * 1e9)
    )
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    fills: list = field(default_factory=list)

    # Tags and metadata
    tags: dict[str, Any] = field(default_factory=dict)
    strategy_id: str | None = None
    parent_order_id: str | None = None

    def __post_init__(self):
        """Validate order after creation."""
        if self.quantity <= 0:
            raise ValueError("Order quantity must be positive")

        if self.side == OrderSide.BUY and self.quantity % 100 != 0:
            # Allow odd lots for simplicity, but could enforce round lots
            pass

        # Validate order type specific requirements
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Limit orders must have a price")

        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("Stop orders must have a stop price")

        if self.order_type == OrderType.STOP_LIMIT and (
            self.price is None or self.stop_price is None
        ):
            raise ValueError("Stop limit orders must have both price and stop price")

    @property
    def remaining_quantity(self) -> int:
        """Get remaining unfilled quantity."""
        return self.quantity - self.filled_quantity

    @property
    def is_fully_filled(self) -> bool:
        """Check if order is fully filled."""
        return self.filled_quantity >= self.quantity

    @property
    def is_active(self) -> bool:
        """Check if order is still active."""
        return self.status in [
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIAL_FILLED,
        ]

    def add_fill(self, quantity: int, price: float, timestamp: int) -> None:
        """Add a fill to this order."""
        if quantity <= 0:
            raise ValueError("Fill quantity must be positive")

        if quantity > self.remaining_quantity:
            raise ValueError("Fill quantity exceeds remaining quantity")

        # Update filled quantity and average price
        total_cost = self.filled_quantity * self.avg_fill_price + quantity * price
        self.filled_quantity += quantity
        self.avg_fill_price = (
            total_cost / self.filled_quantity if self.filled_quantity > 0 else 0.0
        )

        # Record fill
        fill_info = {
            "quantity": quantity,
            "price": price,
            "timestamp": timestamp,
            "order_id": self.order_id,
        }
        self.fills.append(fill_info)

        # Update status
        if self.is_fully_filled:
            self.status = OrderStatus.FILLED
        elif self.filled_quantity > 0:
            self.status = OrderStatus.PARTIAL_FILLED

    def cancel(self) -> None:
        """Cancel the order."""
        if self.status in [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        ]:
            raise ValueError(f"Cannot cancel order in status {self.status}")

        self.status = OrderStatus.CANCELLED

    def reject(self, reason: str = "") -> None:
        """Reject the order."""
        if self.status not in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
            raise ValueError(f"Cannot reject order in status {self.status}")

        self.status = OrderStatus.REJECTED
        if reason:
            self.tags["reject_reason"] = reason

    def to_dict(self) -> dict[str, Any]:
        """Convert order to dictionary representation."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force.value,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "avg_fill_price": self.avg_fill_price,
            "is_fully_filled": self.is_fully_filled,
            "is_active": self.is_active,
            "strategy_id": self.strategy_id,
            "parent_order_id": self.parent_order_id,
            "tags": self.tags,
            "fill_count": len(self.fills),
        }


@dataclass
class MarketOrder(Order):
    """Concrete MarketOrder class to align with policy imports and match test stubs."""

    # Override required fields with defaults to make them optional
    order_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: int = 0

    # Required fields for MarketOrder per sprint plan
    ts_submitted: int = field(
        default_factory=lambda: int(datetime.now().timestamp() * 1e9), init=True
    )

    def __post_init__(self):
        """Post-initialization to set order_type and validate."""
        # Ensure order_type is MARKET
        self.order_type = OrderType.MARKET

        # Coerce side to OrderSide enum if provided as string
        if isinstance(self.side, str):
            try:
                self.side = OrderSide[self.side.upper()]
            except KeyError as exc:  # pragma: no cover - defensive guard
                raise ValueError(f"Invalid order side: {self.side}") from exc

        # Ensure quantity stored as integer lots
        if isinstance(self.quantity, float):
            self.quantity = int(self.quantity)
        elif not isinstance(self.quantity, int):
            self.quantity = int(self.quantity)

        # Generate unique order_id if not provided (for direct instantiation)
        if not hasattr(self, "order_id") or self.order_id is None:
            self.order_id = uuid.uuid4().hex

        # Call parent validation
        super().__post_init__()

    @classmethod
    def create(
        cls,
        symbol: str,
        quantity: int,
        side: OrderSide,
        tags: dict[str, Any] | None = None,
        strategy_id: str | None = None,
        ts_submitted: int | None = None,
    ) -> "MarketOrder":
        """Create MarketOrder with required fields."""
        if ts_submitted is None:
            ts_submitted = int(datetime.now().timestamp() * 1e9)

        return cls(
            order_id=uuid.uuid4().hex,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            ts_submitted=ts_submitted,
            tags=tags or {},
            strategy_id=strategy_id,
        )


class OrderFactory:
    """Factory for creating orders with consistent ID generation."""

    def __init__(self):
        self._order_counter = 0

    def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
        strategy_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Order:
        """Create a new order with unique ID."""
        self._order_counter += 1
        order_id = f"order_{self._order_counter:06d}"

        return Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            strategy_id=strategy_id,
            tags=tags or {},
        )

    def create_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        strategy_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Order:
        """Create a market order."""
        return self.create_order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_id=strategy_id,
            tags=tags,
        )

    def create_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        strategy_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Order:
        """Create a limit order."""
        return self.create_order(
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price,
            strategy_id=strategy_id,
            tags=tags,
        )

    def create_stop_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        stop_price: float,
        strategy_id: str | None = None,
        tags: dict[str, Any] | None = None,
    ) -> Order:
        """Create a stop order."""
        return self.create_order(
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP,
            quantity=quantity,
            stop_price=stop_price,
            strategy_id=strategy_id,
            tags=tags,
        )
