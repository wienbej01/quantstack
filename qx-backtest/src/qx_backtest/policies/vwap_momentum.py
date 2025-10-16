"""VWAP momentum breakout trading policy."""

from typing import Any

import numpy as np
import pandas as pd

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
        self.engine: Any = None  # Will be set by set_engine() method

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
        # Get current equity
        current_equity = self.engine.portfolio.total_equity
        target_value = current_equity * self.position_size_pct

        # Calculate number of shares
        position_size = int(target_value / price)

        # Ensure minimum position size of 1 share
        if position_size < 1:
            position_size = 0

        return position_size

    def on_start(self) -> None:
        """Called when backtest starts."""
        self.position_entry_times.clear()

    def on_end(self) -> None:
        """Called when backtest ends."""
        # Could log statistics here
        total_positions_held = len(self.position_entry_times)
        if total_positions_held > 0:
            avg_bars_held = (
                np.mean(list(self.position_entry_times.values()))
                if self.position_entry_times
                else 0
            )
            print(
                f"{self.name}: Held {total_positions_held} positions, "
                f"avg bars held: {avg_bars_held:.1f}"
            )

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


class VwapMomentumPolicyEnhanced(VwapMomentumPolicy):
    """Enhanced VWAP momentum policy with ATR-based stops and profit targets."""

    def __init__(
        self,
        vwap_window: int = 30,
        min_rvol: float = 1.0,
        max_position_bars: int = 50,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        min_breakout_strength: float = 0.5,
        atr_window: int = 14,
        atr_multiplier: float = 2.0,
        min_profit_atr: float = 0.5,
        name: str = "VwapMomentumEnhanced",
    ):
        """Initialize enhanced VWAP momentum policy.

        Args:
            vwap_window: VWAP lookback window in minutes
            min_rvol: Minimum relative volume for entry
            max_position_bars: Maximum bars to hold position
            position_size_pct: Position size as percentage of equity
            max_positions: Maximum concurrent positions
            min_breakout_strength: Minimum breakout strength required
            atr_window: ATR lookback window for stop loss
            atr_multiplier: ATR multiplier for stop loss
            min_profit_atr: Minimum profit target in ATR multiples
            name: Policy name
        """
        super().__init__(
            vwap_window,
            min_rvol,
            max_position_bars,
            position_size_pct,
            max_positions,
            min_breakout_strength,
            name,
        )
        self.atr_window = atr_window
        self.atr_multiplier = atr_multiplier
        self.min_profit_atr = min_profit_atr

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single bar of data."""
        symbol = bar["symbol"]
        timestamp = bar["ts"]

        # Check required features
        vwap_col = f"f__ta__vwap_{self.vwap_window}"
        rvol_col = f"f__vol__rel_volume_{self.vwap_window}"
        atr_col = f"f__vol__atr_{self.atr_window}"

        if vwap_col not in bar or rvol_col not in bar or atr_col not in bar:
            return

        vwap = bar[vwap_col]
        rvol = bar[rvol_col]
        atr = bar[atr_col]
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]

        # Get current position
        position = self.get_position(symbol)

        if position is None or position.is_flat:
            # Enhanced entry signal
            self._check_entry_signal_enhanced(
                symbol, bar, close, vwap, rvol, atr, timestamp
            )
        else:
            # Enhanced exit signal
            self._check_exit_signal_enhanced(
                symbol, bar, position, close, vwap, high, low, atr, timestamp
            )

    def _check_entry_signal_enhanced(
        self,
        symbol: str,
        bar: dict[str, Any],
        close: float,
        vwap: float,
        rvol: float,
        atr: float,
        timestamp: int,
    ) -> None:
        """Check for enhanced momentum entry signal."""
        # Entry criteria with additional filters
        breakout_strength = abs(close - vwap) / vwap
        breakout_pct = breakout_strength * 100

        # Entry criteria with additional filters
        if (
            rvol >= self.min_rvol
            and atr > 0
            and breakout_pct >= self.min_breakout_strength
        ):

            # Additional filter: avoid entering during extreme volatility
            volatility_ratio = atr / close
            if volatility_ratio > 0.1:  # More than 10% daily volatility
                return

            # Check position limits
            current_positions = len(self.engine.portfolio.positions)
            if current_positions >= self.max_positions:
                return

            # Check for existing orders
            pending_orders = self.get_pending_orders(symbol)
            if pending_orders:
                return

            # Calculate position size with volatility adjustment
            base_size = self._calculate_position_size(close)
            volatility_adjustment = max(0.5, 1.0 - volatility_ratio * 5)
            position_size = int(base_size * volatility_adjustment)

            if position_size > 0:
                if close > vwap:
                    # Long breakout: need sufficient profit potential
                    if (close - vwap) >= (self.min_profit_atr * atr):
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
                                "atr": atr,
                                "signal_strength": breakout_strength,
                                "volatility_ratio": volatility_ratio,
                            },
                        )
                        self.submit_order(order)
                elif close < vwap:
                    # Short breakdown: need sufficient profit potential
                    if (vwap - close) >= (self.min_profit_atr * atr):
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
                                "atr": atr,
                                "signal_strength": breakout_strength,
                                "volatility_ratio": volatility_ratio,
                            },
                        )
                        self.submit_order(order)

    def _check_exit_signal_enhanced(
        self,
        symbol: str,
        bar: dict[str, Any],
        position: Position,
        close: float,
        vwap: float,
        high: float,
        low: float,
        atr: float,
        timestamp: int,
    ) -> None:
        """Check for enhanced exit signal."""
        if symbol not in self.position_entry_times:
            self.position_entry_times[symbol] = timestamp

        entry_time = self.position_entry_times[symbol]
        bars_held = self._calculate_bars_held(entry_time, timestamp)

        # Calculate stop loss and profit targets
        is_long_position = position.quantity > 0

        if is_long_position:
            stop_loss_price = position.avg_cost - (atr * self.atr_multiplier)
            profit_target_price = position.avg_cost + (atr * self.min_profit_atr)
        else:
            stop_loss_price = position.avg_cost + (atr * self.atr_multiplier)
            profit_target_price = position.avg_cost - (atr * self.min_profit_atr)

        exit_reason = None

        # Enhanced exit criteria - prioritize stop loss and profit targets
        if is_long_position:
            if close <= stop_loss_price:
                exit_reason = "stop_loss"
            elif close >= profit_target_price:
                exit_reason = "profit_target"
            elif close <= vwap:
                exit_reason = "vwap_target"
            elif bars_held >= self.max_position_bars:
                exit_reason = "timeout"
        else:
            if close >= stop_loss_price:
                exit_reason = "stop_loss"
            elif close <= profit_target_price:
                exit_reason = "profit_target"
            elif close >= vwap:
                exit_reason = "vwap_target"
            elif bars_held >= self.max_position_bars:
                exit_reason = "timeout"

        if exit_reason:
            # Check for pending exit orders
            pending_orders = self.get_pending_orders(symbol)
            exit_side = OrderSide.SELL if is_long_position else OrderSide.BUY
            exit_pending = any(order.side == exit_side for order in pending_orders)

            if not exit_pending:
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=exit_side,
                    quantity=abs(position.quantity),
                    tags={
                        "policy": self.name,
                        "exit_reason": exit_reason,
                        "bars_held": bars_held,
                        "entry_price": position.avg_cost,
                        "exit_price": close,
                        "vwap": vwap,
                        "atr": atr,
                        "stop_loss_price": stop_loss_price,
                        "profit_target_price": profit_target_price,
                        "pnl_per_atr": (
                            (close - position.avg_cost) / atr
                            if atr > 0 and is_long_position
                            else (position.avg_cost - close) / atr if atr > 0 else 0
                        ),
                    },
                )

                self.submit_order(order)


# Legacy function for backward compatibility
def generate_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Generate signals for VWAP momentum strategy (legacy function).

    Args:
        df: DataFrame with bars and features
        params: Parameters dict with rvol_min, vwap_col, rvol_col, timeout_bars,
            min_breakout_strength, sip_universe (optional)

    Returns:
        DataFrame with signals: ts, symbol, signal (1=long, 0=flat), and diagnostic columns
    """
    rvol_min = params.get("rvol_min", 1.0)
    vwap_col = params.get("vwap_col", "f__ta__vwap_30")
    rvol_col = params.get("rvol_col", "f__vol__rel_volume_30")
    timeout_bars = params.get("timeout_bars", 10)
    min_breakout_strength = params.get("min_breakout_strength", 0.5)
    sip_universe = params.get("sip_universe")  # Dict[ts, Set[symbols]] or None

    signals = []
    position_tracker = {}  # symbol -> {'entry_ts': ts, 'bars_held': int}

    for _, row in df.iterrows():
        ts = row["ts"]
        symbol = row["symbol"]
        close = row["close"]
        vwap = row[vwap_col]
        rvol = row[rvol_col]
        warmup_ok = row.get("f__warmup_ok", True)

        # Check SIP filter
        in_sip = True
        if sip_universe and ts in sip_universe:
            in_sip = symbol in sip_universe[ts]

        # Get position state from START of bar
        pos_before_decision = position_tracker.get(
            symbol, {"entry_ts": None, "bars_held": 0}
        )

        # Calculate breakout strength
        breakout_strength = (close - vwap) / vwap

        # Decision logic (momentum: buy when above VWAP, sell when below)
        decision = "hold"
        if pos_before_decision["entry_ts"] is not None:
            # In position
            new_bars_held = pos_before_decision["bars_held"] + 1
            if (
                close <= vwap and breakout_strength < -min_breakout_strength / 100
            ) or new_bars_held >= timeout_bars:
                decision = "exit"
                position_tracker[symbol] = {"entry_ts": None, "bars_held": 0}
            else:
                position_tracker[symbol]["bars_held"] = new_bars_held
        # Flat
        elif (
            close > vwap
            and rvol >= rvol_min
            and in_sip
            and warmup_ok
            and breakout_strength > min_breakout_strength / 100
        ):
            decision = "enter"
            position_tracker[symbol] = {"entry_ts": ts, "bars_held": 1}

        # Get position state AFTER decision for the current bar
        pos_after_decision = position_tracker.get(
            symbol, {"entry_ts": None, "bars_held": 0}
        )

        # Generate signal based on the state AFTER the decision
        signal = 1 if pos_after_decision["entry_ts"] is not None else 0

        # Diagnostic columns
        diag = {
            "ts": ts,
            "symbol": symbol,
            "signal": signal,
            "close": close,
            "vwap": vwap,
            "rvol": rvol,
            "breakout_strength": breakout_strength,
            "in_sip": in_sip,
            "warmup_ok": warmup_ok,
            "bars_held": pos_after_decision["bars_held"],
            "decision": decision,
        }
        signals.append(diag)

    return pd.DataFrame(signals)
