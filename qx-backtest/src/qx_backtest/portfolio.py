"""Portfolio management for backtesting engine."""

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


def log_debug(msg):
    logging.debug(msg)


from .fill import Fill
from .order import Order, OrderSide, OrderStatus


@dataclass
class Position:
    """Position representation for a single symbol."""

    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_cost: float = 0.0
    commissions: float = 0.0

    def __post_init__(self):
        """Initialize position after creation."""
        if self.quantity != 0 and self.avg_cost == 0.0:
            self.avg_cost = (
                self.total_cost / abs(self.quantity) if self.quantity != 0 else 0.0
            )

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        """Check if position is flat."""
        return self.quantity == 0

    @property
    def market_price(self) -> float:
        """Get current market price for position."""
        if self.quantity == 0:
            return 0.0
        return self.market_value / abs(self.quantity) if self.quantity != 0 else 0.0

    def apply_fill(self, fill: Fill) -> None:
        import logging

        logging.debug(
            f"Before apply_fill: self.quantity={self.quantity}, fill.quantity={fill.quantity}"
        )
        fill_cost = fill.total_cost

        if fill.side == OrderSide.BUY:
            if self.quantity > 0:
                logging.debug(
                    f"BUY order for {self.symbol} received while already long. Position not increased."
                )
                return

            if self.quantity >= 0:
                new_total_cost = self.total_cost + fill_cost
                new_quantity = self.quantity + fill.quantity
                logging.debug(
                    f"BUY LONG: new_quantity={new_quantity}, new_total_cost={new_total_cost}"
                )
                if new_quantity != 0:
                    self.avg_cost = new_total_cost / new_quantity
                else:
                    self.avg_cost = 0.0
                self.total_cost = new_total_cost
                self.quantity = new_quantity
            else:
                # Covering short position
                cover_quantity = min(fill.quantity, abs(self.quantity))
                realized_pnl = cover_quantity * (self.avg_cost - fill.price)
                self.realized_pnl += realized_pnl
                self.quantity += fill.quantity
                if self.quantity > 0:
                    remaining_qty = fill.quantity - cover_quantity
                    self.total_cost = remaining_qty * fill.price
                    self.avg_cost = fill.price
                else:
                    self.total_cost = 0.0
                    self.avg_cost = 0.0
        elif self.quantity > 0:
            # Selling from long position
            sell_quantity = min(fill.quantity, self.quantity)
            realized_pnl = sell_quantity * (fill.price - self.avg_cost)
            self.realized_pnl += realized_pnl
            self.quantity -= fill.quantity
            if self.quantity < 0:
                remaining_qty = fill.quantity - sell_quantity
                self.total_cost = remaining_qty * fill.price
                self.avg_cost = fill.price
            else:
                self.total_cost = self.quantity * self.avg_cost
                if self.quantity == 0:
                    self.avg_cost = 0.0
        else:
            if self.quantity < 0:
                logging.debug(
                    f"SELL order for {self.symbol} received while already short. Position not increased."
                )
                return

            # Adding to short position
            new_total_cost = self.total_cost + fill_cost
            new_quantity = self.quantity - fill.quantity
            logging.debug(
                f"SELL SHORT: new_quantity={new_quantity}, new_total_cost={new_total_cost}"
            )
            if new_quantity != 0:
                self.avg_cost = new_total_cost / abs(new_quantity)
            else:
                self.avg_cost = 0.0
            self.total_cost = new_total_cost
            self.quantity = new_quantity

        self.commissions += fill.commission
        logging.debug(f"After apply_fill: self.quantity={self.quantity}")

        if abs(self.quantity) > 0:
            print(
                f"[TRACE] Position {self.symbol} quantity={self.quantity} "
                f"after fill {fill.order_id} side={fill.side.value} "
                f"fill_qty={fill.quantity}"
            )

        if abs(self.quantity) > 0:
            print(
                f"[TRACE] Position {self.symbol} quantity={self.quantity} "
                f"after fill {fill.order_id} side={fill.side.value} "
                f"fill_qty={fill.quantity}"
            )

    def update_market_value(self, current_price: float) -> None:
        """Update market value and unrealized P&L."""
        if self.quantity == 0:
            self.market_value = 0.0
            self.unrealized_pnl = 0.0
        else:
            self.market_value = self.quantity * current_price
            if self.quantity > 0:
                self.unrealized_pnl = (current_price - self.avg_cost) * self.quantity
            else:
                self.unrealized_pnl = (self.avg_cost - current_price) * abs(
                    self.quantity
                )

    def get_total_pnl(self) -> float:
        """Get total P&L (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl

    def to_dict(self) -> dict[str, Any]:
        """Convert position to dictionary representation."""
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "total_pnl": self.get_total_pnl(),
            "total_cost": self.total_cost,
            "commissions": self.commissions,
            "market_price": self.market_price,
            "is_long": self.is_long,
            "is_short": self.is_short,
            "is_flat": self.is_flat,
        }


@dataclass
class Portfolio:
    """Portfolio representation for backtesting."""

    cash: float = 1_000_000.0  # Starting cash
    positions: dict[str, Position] = field(default_factory=dict)
    pending_orders: list[Order] = field(default_factory=list)
    filled_orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)

    # Performance tracking
    equity_high_water_mark: float = 1_000_000.0
    max_drawdown: float = 0.0
    total_commissions: float = 0.0
    total_slippage: float = 0.0

    def __post_init__(self):
        """Initialize portfolio after creation."""
        self.equity_high_water_mark = self.cash

    @property
    def total_market_value(self) -> float:
        """Get total market value of all positions."""
        return sum(pos.market_value for pos in self.positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        """Get total unrealized P&L."""
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    @property
    def total_realized_pnl(self) -> float:
        """Get total realized P&L."""
        return sum(pos.realized_pnl for pos in self.positions.values())

    @property
    def total_pnl(self) -> float:
        """Get total P&L."""
        return self.total_unrealized_pnl + self.total_realized_pnl

    @property
    def total_equity(self) -> float:
        """Get total equity (cash + market value)."""
        return self.cash + self.total_market_value

    @property
    def total_leverage(self) -> float:
        """Get total leverage (market value / equity)."""
        if self.total_equity == 0:
            return 0.0
        return abs(self.total_market_value) / self.total_equity

    def get_position(self, symbol: str) -> Position:
        """Get or create position for symbol."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def add_order(self, order: Order) -> None:
        """Add order to pending orders."""
        if order.status == OrderStatus.PENDING:
            self.pending_orders.append(order)

    def remove_order(self, order: Order) -> None:
        """Remove order from pending orders."""
        if order in self.pending_orders:
            self.pending_orders.remove(order)

    def add_filled_order(self, order: Order) -> None:
        """Add order to filled orders."""
        if order not in self.filled_orders:
            self.filled_orders.append(order)

    def apply_fill(self, fill: Fill) -> None:
        log_debug(f"Applying fill {fill.fill_id} for order {fill.order_id}")
        """Apply a fill to the portfolio."""
        # Update cash with side-aware flow
        if fill.side == OrderSide.BUY:
            self.cash -= fill.total_cost
        else:
            self.cash += fill.total_cost

        # Update position
        position = self.get_position(fill.symbol)
        position.apply_fill(fill)

        # Track fill
        self.fills.append(fill)

        # Update totals
        self.total_commissions += fill.commission

        # Clean up flat positions
        if position.is_flat:
            del self.positions[fill.symbol]

    def update_market_values(self, market_data: dict[str, float]) -> None:
        """Update market values for all positions."""
        for symbol, position in self.positions.items():
            if symbol in market_data:
                position.update_market_value(market_data[symbol])

        # Update high water mark and drawdown
        current_equity = self.total_equity
        self.equity_high_water_mark = max(self.equity_high_water_mark, current_equity)

        current_drawdown = (
            self.equity_high_water_mark - current_equity
        ) / self.equity_high_water_mark
        self.max_drawdown = max(self.max_drawdown, current_drawdown)

    def get_portfolio_summary(self) -> dict[str, Any]:
        """Get comprehensive portfolio summary."""
        return {
            "cash": self.cash,
            "total_market_value": self.total_market_value,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "total_realized_pnl": self.total_realized_pnl,
            "total_pnl": self.total_pnl,
            "total_equity": self.total_equity,
            "total_leverage": self.total_leverage,
            "equity_high_water_mark": self.equity_high_water_mark,
            "max_drawdown": self.max_drawdown,
            "total_commissions": self.total_commissions,
            "total_slippage": self.total_slippage,
            "position_count": len(self.positions),
            "pending_order_count": len(self.pending_orders),
            "filled_order_count": len(self.filled_orders),
            "fill_count": len(self.fills),
            "positions": {
                symbol: pos.to_dict() for symbol, pos in self.positions.items()
            },
        }

    def get_positions_df(self) -> pd.DataFrame:
        """Get positions as pandas DataFrame."""
        if not self.positions:
            return pd.DataFrame()

        positions_data = [pos.to_dict() for pos in self.positions.values()]
        return pd.DataFrame(positions_data).sort_values("market_value", ascending=False)

    def get_fills_df(self) -> pd.DataFrame:
        """Get fills as pandas DataFrame."""
        if not self.fills:
            return pd.DataFrame()

        fills_data = [fill.to_dict() for fill in self.fills]
        return pd.DataFrame(fills_data).sort_values("timestamp")

    def reset(self, initial_cash: float = 1_000_000.0) -> None:
        """Reset portfolio to initial state."""
        self.cash = initial_cash
        self.positions.clear()
        self.pending_orders.clear()
        self.filled_orders.clear()
        self.fills.clear()
        self.equity_high_water_mark = initial_cash
        self.max_drawdown = 0.0
        self.total_commissions = 0.0
        self.total_slippage = 0.0
