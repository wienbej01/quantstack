"""Base policy class for trading strategies."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class Policy(ABC):
    """Abstract base class for trading policies."""

    def __init__(self, name: str = "Policy"):
        """Initialize policy.

        Args:
            name: Policy name for identification
        """
        self.name = name
        self.strategy_id = name.lower()
        self.engine = None

    def set_engine(self, engine) -> None:
        """Set the backtest engine reference.

        Args:
            engine: BacktestEngine instance
        """
        self.engine = engine

    @abstractmethod
    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single bar of data.

        Args:
            bar: Bar data dictionary with OHLCV and features
        """
        pass

    def on_start(self) -> None:
        """Called when backtest starts."""
        pass

    def on_end(self) -> None:
        """Called when backtest ends."""
        pass

    def get_position(self, symbol: str) -> Optional["Position"]:
        """Get current position for symbol.

        Args:
            symbol: Symbol to get position for

        Returns:
            Position object or None if no position
        """
        if self.engine is None:
            raise ValueError("Policy must be attached to an engine")
        return self.engine.get_position(symbol)

    def submit_order(self, order) -> None:
        """Submit an order through the engine.

        Args:
            order: Order to submit
        """
        if self.engine is None:
            raise ValueError("Policy must be attached to an engine")
        self.engine.submit_order(order)

    def cancel_order(self, order) -> None:
        """Cancel an order through the engine.

        Args:
            order: Order to cancel
        """
        if self.engine is None:
            raise ValueError("Policy must be attached to an engine")
        self.engine.cancel_order(order)

    def get_pending_orders(self, symbol: str | None = None):
        """Get pending orders through the engine.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of pending orders
        """
        if self.engine is None:
            raise ValueError("Policy must be attached to an engine")
        return self.engine.get_pending_orders(symbol)

    def is_allowed(self) -> bool:
        """Return True if the policy is allowed under the current regime.

        Defaults to True when the engine is not attached or does not implement
        regime gating.
        """
        if self.engine is None:
            return True
        if hasattr(self.engine, "is_strategy_allowed"):
            try:
                return self.engine.is_strategy_allowed(self.strategy_id)
            except Exception:
                return True
        return True
