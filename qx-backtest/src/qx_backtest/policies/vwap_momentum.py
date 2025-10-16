"""VWAP momentum breakout trading policy."""

from typing import Any

from ..order import OrderSide
from ..portfolio import Position
from .base import Policy


class VwapMomentumPolicy(Policy):
    """VWAP momentum breakout trading policy.

    This policy implements a momentum strategy based on VWAP breakouts:
    - Long Entry: Buy when close > VWAP and breakout strength >= minimum
    - Long Exit: Sell when close <= VWAP or timeout after maximum bars
    - Short Entry: Sell when close < VWAP and breakdown strength >= minimum
    - Short Exit: Buy when close >= VWAP or timeout after maximum bars
    """

    def __init__(  # noqa: PLR0913
        self,
        vwap_window: int = 30,
        min_rvol: float = 1.0,
        max_position_bars: int = 50,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        min_breakout_strength: float = 0.5,
        name: str = "VwapMomentum",
    ):
        """Initialize VWAP momentum policy.

        Args:
            vwap_window: VWAP lookback window in minutes
            min_rvol: Minimum relative volume for entry
            max_position_bars: Maximum bars to hold position
            position_size_pct: Position size as percentage of equity
            max_positions: Maximum concurrent positions
            min_breakout_strength: Minimum breakout strength required
                (percentage deviation from VWAP)
            name: Policy name
        """
        super().__init__(name)
        self.vwap_window = vwap_window
        self.min_rvol = min_rvol
        self.max_position_bars = max_position_bars
        self.position_size_pct = position_size_pct
        self.max_positions = max_positions
        self.min_breakout_strength = min_breakout_strength

        # Track position entry times
        self.position_entry_times: dict[str, int] = {}

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single bar of data."""
        symbol = bar["symbol"]
        timestamp = bar["ts"]

        # Check required features
        vwap_col = f"f__ta__vwap_{self.vwap_window}"
        rvol_col = f"f__vol__rel_volume_{self.vwap_window}"

        if vwap_col not in bar or rvol_col not in bar:
            return

        vwap = bar[vwap_col]
        rvol = bar[rvol_col]
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]

        # Get current position
        position = self.get_position(symbol)

        if position is None or position.is_flat:
            # Check for entry signal (both long and short)
            self._check_entry_signal(symbol, bar, close, vwap, rvol, timestamp)
        else:
            # Check for exit signal (both long and short)
            self._check_exit_signal(
                symbol, bar, position, close, vwap, high, low, timestamp
            )

    def _check_entry_signal(  # noqa: PLR0913
        self,
        symbol: str,
        bar: dict[str, Any],
        close: float,
        vwap: float,
        rvol: float,
        timestamp: int,
    ) -> None:
        """Check for momentum entry signal (both long and short)."""
        # Check if we have room for more positions
        if self.engine and self.engine.portfolio:
            current_positions = len(self.engine.portfolio.positions)
            if current_positions >= self.max_positions:
                return
        else:
            return

        # Check if we already have a pending order for this symbol
        pending_orders = self.get_pending_orders(symbol)
        if pending_orders:
            return

        # Calculate VWAP breakout strength
        breakout_strength = (close - vwap) / vwap
        breakout_pct = abs(breakout_strength) * 100

        # Entry criteria for both long and short positions
        if rvol >= self.min_rvol and breakout_pct >= self.min_breakout_strength:
            position_size = self._calculate_position_size(close)

            if position_size > 0:
                if close > vwap:
                    # Long entry: price above VWAP (momentum breakout)
                    if self.engine and self.engine.order_factory:
                        order = self.engine.order_factory.create_market_order(
                            symbol=symbol,
                            side=OrderSide.BUY,
                            quantity=position_size,
                            tags={
                                "policy": self.name,
                                "direction": "LONG",
                                "entry_price": close,
                                "vwap": vwap,
                                "rvol": rvol,
                                "signal_strength": breakout_strength,
                                "breakout_pct": breakout_pct,
                            },
                        )
                        self.submit_order(order)

                elif close < vwap and self.engine and self.engine.order_factory:
                    # Short entry: price below VWAP (momentum breakdown)
                    order = self.engine.order_factory.create_market_order(
                        symbol=symbol,
                        side=OrderSide.SELL,
                        quantity=position_size,
                        tags={
                            "policy": self.name,
                            "direction": "SHORT",
                            "entry_price": close,
                            "vwap": vwap,
                            "rvol": rvol,
                            "signal_strength": abs(breakout_strength),
                            "breakout_pct": breakout_pct,
                        },
                    )
                    self.submit_order(order)

    def _calculate_position_size(self, price: float) -> int:
        """Calculate position size based on risk management."""
        # Placeholder implementation - will be implemented in Task 5
        return 100  # Fixed size for now

    def _check_exit_signal(  # noqa: PLR0913
        self,
        symbol: str,
        bar: dict[str, Any],
        position: Position,
        close: float,
        vwap: float,
        high: float,
        low: float,
        timestamp: int,
    ) -> None:
        """Check for momentum exit signal (both long and short positions)."""
        # Check if position has entry time recorded
        if symbol not in self.position_entry_times:
            self.position_entry_times[symbol] = timestamp

        entry_time = self.position_entry_times[symbol]
        bars_held = self._calculate_bars_held(entry_time, timestamp)

        # Determine position direction from position cost basis
        is_long_position = position.quantity > 0

        exit_reason = None

        if is_long_position:
            # Long position exit criteria (opposite of reversal)
            if close <= vwap:
                exit_reason = "vwap_target_long"
            elif bars_held >= self.max_position_bars:
                exit_reason = "timeout_long"
        # Short position exit criteria (opposite of reversal)
        elif close >= vwap:
            exit_reason = "vwap_target_short"
        elif bars_held >= self.max_position_bars:
            exit_reason = "timeout_short"

        if exit_reason:
            # Check if we already have a pending exit order
            pending_orders = self.get_pending_orders(symbol)
            exit_side = OrderSide.SELL if is_long_position else OrderSide.BUY
            exit_pending = any(order.side == exit_side for order in pending_orders)

            if not exit_pending and self.engine and self.engine.order_factory:
                # Create exit order for entire position
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=exit_side,
                    quantity=abs(position.quantity),
                    tags={
                        "policy": self.name,
                        "direction": "EXIT_"
                        + ("LONG" if is_long_position else "SHORT"),
                        "exit_reason": exit_reason,
                        "bars_held": bars_held,
                        "entry_price": position.avg_cost,
                        "exit_price": close,
                        "vwap": vwap,
                        "position_side": "LONG" if is_long_position else "SHORT",
                    },
                )

                self.submit_order(order)

    def _calculate_bars_held(self, entry_time: int, current_time: int) -> int:
        """Calculate number of bars held since entry.

        This is a simplified calculation - in practice you'd need
        to account for market hours, holidays, etc.
        """
        # Assuming 1-minute bars (1 billion nanoseconds = 1 second)
        # 60 seconds = 1 minute = 60 billion nanoseconds
        minute_ns = 60 * 1_000_000_000
        bars_held = (current_time - entry_time) // minute_ns
        return int(bars_held)
