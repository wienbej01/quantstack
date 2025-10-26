"""ATR Stop Manager for risk management in trading policies."""

from typing import Any


class ATRStopManager:
    """ATR-based stop loss and target management for trading policies.

    Provides minimal interface used by policies with configurable ATR multiples
    for stop loss and target levels.
    """

    def __init__(
        self,
        stop_atr_multiple: float = 1.0,
        target_atr_multiple: float = 1.0,
        trailing_stop_enabled: bool = False,
        trailing_atr_multiple: float = 1.0,
        trailing_activation_atr: float = 0.8,
        **kwargs: Any,
    ):
        """Initialize ATR Stop Manager.

        Args:
            stop_atr_multiple: ATR multiple for stop loss distance
            target_atr_multiple: ATR multiple for profit target distance
            trailing_stop_enabled: Whether to enable trailing stops
            trailing_atr_multiple: ATR distance for trailing stop
            trailing_activation_atr: ATR profit level before trailing activates
            **kwargs: Additional configuration parameters
        """
        self.stop_atr_multiple = stop_atr_multiple
        self.target_atr_multiple = target_atr_multiple
        self.trailing_stop_enabled = trailing_stop_enabled
        self.trailing_atr_multiple = trailing_atr_multiple
        self.trailing_activation_atr = trailing_activation_atr
        self.config = kwargs

        # State tracking for trailing stops
        self._highest_price = None
        self._lowest_price = None
        self._trailing_activated = False
        self._current_stop = None
        self._entry_price = None
        self._position_side = None

    def configure(self, **kwargs: Any) -> None:
        """Update configuration parameters.

        Args:
            **kwargs: Configuration parameters to update
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                self.config[key] = value

    def compute_stop(self, entry_price: float, atr: float, side: str) -> float:
        """Compute stop loss price based on ATR.

        Args:
            entry_price: Entry price of position
            atr: ATR value
            side: Position side ('long' or 'short')

        Returns:
            Stop loss price
        """
        if side.lower() == "long":
            return entry_price - (atr * self.stop_atr_multiple)
        else:
            return entry_price + (atr * self.stop_atr_multiple)

    def compute_target(self, entry_price: float, atr: float, side: str) -> float:
        """Compute profit target price based on ATR.

        Args:
            entry_price: Entry price of position
            atr: ATR value
            side: Position side ('long' or 'short')

        Returns:
            Profit target price
        """
        if side.lower() == "long":
            return entry_price + (atr * self.target_atr_multiple)
        else:
            return entry_price - (atr * self.target_atr_multiple)

    def compute_trailing_stop(
        self, current_price: float, atr: float, entry_price: float, side: str
    ) -> float | None:
        """Compute trailing stop price if enabled.

        Args:
            current_price: Current market price
            atr: ATR value
            entry_price: Original entry price
            side: Position side ('long' or 'short')

        Returns:
            Trailing stop price or None if trailing not enabled
        """
        if not self.trailing_stop_enabled:
            return None

        # Initialize state on first call
        if self._entry_price is None:
            self._entry_price = entry_price
            self._position_side = side.lower()
            self._highest_price = current_price if side.lower() == "long" else None
            self._lowest_price = current_price if side.lower() == "short" else None
            self._current_stop = self.compute_stop(entry_price, atr, side)
            return self._current_stop

        # Update tracking
        if side.lower() == "long":
            self._highest_price = max(self._highest_price, current_price)
            profit_atr = (current_price - entry_price) / atr

            # Check if trailing should activate
            if (
                not self._trailing_activated
                and profit_atr >= self.trailing_activation_atr
            ):
                self._trailing_activated = True

            # Update trailing stop if activated
            if self._trailing_activated:
                new_stop = self._highest_price - (atr * self.trailing_atr_multiple)
                self._current_stop = max(self._current_stop, new_stop)

        else:  # short position
            self._lowest_price = min(self._lowest_price, current_price)
            profit_atr = (entry_price - current_price) / atr

            # Check if trailing should activate
            if (
                not self._trailing_activated
                and profit_atr >= self.trailing_activation_atr
            ):
                self._trailing_activated = True

            # Update trailing stop if activated
            if self._trailing_activated:
                new_stop = self._lowest_price + (atr * self.trailing_atr_multiple)
                self._current_stop = min(self._current_stop, new_stop)

        return self._current_stop

    def reset(self) -> None:
        """Reset internal state for new position."""
        self._highest_price = None
        self._lowest_price = None
        self._trailing_activated = False
        self._current_stop = None
        self._entry_price = None
        self._position_side = None

    def get_default_config(self) -> dict[str, Any]:
        """Get default configuration for ATR Stop Manager.

        Returns:
            Dictionary with default configuration
        """
        return {
            "stop_atr_multiple": 1.0,
            "target_atr_multiple": 1.0,
            "trailing_stop_enabled": False,
            "trailing_atr_multiple": 1.0,
            "trailing_activation_atr": 0.8,
        }
