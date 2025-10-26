"""VWAP revert trading policy."""

from typing import Any

import pandas as pd

from qx_risk.atr_stop import set_stops, size_order

from ..order import OrderSide
from ..portfolio import Position
from .base import Policy


class VwapRevertPolicy(Policy):
    """VWAP reversion trading policy.

    This policy implements a bidirectional mean reversion strategy based on VWAP:
    - Long Entry: Buy when close < VWAP and relative volume >= minimum
    - Long Exit: Sell when close >= VWAP or timeout after maximum bars
    - Short Entry: Sell when close > VWAP and relative volume >= minimum
    - Short Exit: Buy when close <= VWAP or timeout after maximum bars
    """

    def __init__(
        self,
        vwap_window: int = 30,
        min_rvol: float = 1.0,
        max_position_bars: int = 50,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        min_deviation_pct: float = 0.5,
        name: str = "VwapRevert",
        risk_params: dict[str, Any] | None = None,
        atr_col: str = "f__vol__atr_14",
    ):
        """Initialize VWAP revert policy.

        Args:
            vwap_window: VWAP lookback window in minutes
            min_rvol: Minimum relative volume for entry
            max_position_bars: Maximum bars to hold position
            position_size_pct: Position size as percentage of equity
            max_positions: Maximum concurrent positions
            min_deviation_pct: Minimum absolute deviation from VWAP (percentage) required to enter
            name: Policy name
        """
        super().__init__(name)
        self.vwap_window = vwap_window
        self.min_rvol = min_rvol
        self.max_position_bars = max_position_bars
        self.position_size_pct = position_size_pct
        self.max_positions = max_positions
        self.min_deviation_pct = min_deviation_pct
        self.risk_params = risk_params or {}
        self.atr_col = atr_col

        # Track position entry times
        self.position_entry_times: dict[str, int] = {}
        self.position_stop_prices: dict[str, float] = {}
        self.position_targets: dict[str, float] = {}

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

        # If regime gating disables the strategy, only manage open positions
        if not self.is_allowed():
            if position is not None and not position.is_flat:
                self._check_exit_signal(
                    symbol, bar, position, close, vwap, high, low, timestamp
                )
            return

        if position is None or position.is_flat:
            # Check for entry signal (both long and short)
            self._check_entry_signal(symbol, bar, close, vwap, rvol, timestamp)
        else:
            # Check for exit signal (both long and short)
            self._check_exit_signal(
                symbol, bar, position, close, vwap, high, low, timestamp
            )

    def _check_entry_signal(
        self,
        symbol: str,
        bar: dict[str, Any],
        close: float,
        vwap: float,
        rvol: float,
        timestamp: int,
    ) -> None:
        """Check for entry signal (both long and short)."""
        # Check if we have room for more positions
        current_positions = len(self.engine.portfolio.positions)
        if current_positions >= self.max_positions:
            return

        # Check if we already have a pending order for this symbol
        pending_orders = self.get_pending_orders(symbol)
        if pending_orders:
            return

        # Calculate VWAP deviation
        vwap_deviation = (close - vwap) / vwap
        deviation_pct = abs(vwap_deviation) * 100

        # Entry criteria for both long and short positions
        if rvol >= self.min_rvol and deviation_pct >= self.min_deviation_pct:
            position_size, stop_price, target_price = self._calculate_position_size(
                close, bar
            )

            if position_size > 0:
                if close < vwap:
                    # Long entry: price below VWAP (buy the dip)
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
                            "signal_strength": abs(vwap_deviation),
                            "deviation_pct": deviation_pct,
                            "stop_price": stop_price,
                            "target_price": target_price,
                        },
                    )
                    self.submit_order(order)
                    if stop_price is not None:
                        self.position_stop_prices[symbol] = stop_price
                    if target_price is not None:
                        self.position_targets[symbol] = target_price

                elif close > vwap:
                    # Short entry: price above VWAP (sell the rally)
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
                            "signal_strength": abs(vwap_deviation),
                            "deviation_pct": deviation_pct,
                            "stop_price": stop_price,
                            "target_price": target_price,
                        },
                    )
                    self.submit_order(order)
                    if stop_price is not None:
                        self.position_stop_prices[symbol] = stop_price
                    if target_price is not None:
                        self.position_targets[symbol] = target_price

    def _check_exit_signal(
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
        """Check for exit signal (both long and short positions)."""
        # Check if position has entry time recorded
        if symbol not in self.position_entry_times:
            self.position_entry_times[symbol] = timestamp

        entry_time = self.position_entry_times[symbol]
        bars_held = self._calculate_bars_held(entry_time, timestamp)

        # Determine position direction from position cost basis
        is_long_position = position.quantity > 0

        exit_reason = None

        if is_long_position:
            # Long position exit criteria
            if close >= vwap:
                exit_reason = "vwap_target_long"
            elif bars_held >= self.max_position_bars:
                exit_reason = "timeout_long"
        # Short position exit criteria
        elif close <= vwap:
            exit_reason = "vwap_target_short"
        elif bars_held >= self.max_position_bars:
            exit_reason = "timeout_short"

        stop_price = self.position_stop_prices.get(symbol)
        target_price = self.position_targets.get(symbol)

        if stop_price is not None:
            if is_long_position and low <= stop_price:
                exit_reason = "risk_stop_long"
            elif not is_long_position and high >= stop_price:
                exit_reason = "risk_stop_short"

        if target_price is not None and exit_reason is None:
            if is_long_position and high >= target_price:
                exit_reason = "risk_target_long"
            elif not is_long_position and low <= target_price:
                exit_reason = "risk_target_short"

        if exit_reason:
            # Check if we already have a pending exit order
            pending_orders = self.get_pending_orders(symbol)
            exit_side = OrderSide.SELL if is_long_position else OrderSide.BUY
            exit_pending = any(order.side == exit_side for order in pending_orders)

            if not exit_pending:
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
                self.position_stop_prices.pop(symbol, None)
                self.position_targets.pop(symbol, None)

    def _calculate_position_size(
        self, price: float, bar: dict[str, Any]
    ) -> tuple[int, float | None, float | None]:
        """Calculate position size and optional risk targets."""
        current_equity = self.engine.portfolio.total_equity
        target_value = current_equity * self.position_size_pct
        base_size = int(target_value / price)
        stop_price = None
        target_price = None

        if self.risk_params and self.atr_col in bar:
            atr = bar.get(self.atr_col)
            if atr and atr > 0:
                signal_dict = {
                    "entry_hint": price,
                    "stop_hint": price - atr * self.risk_params.get("atr_mult", 1.0),
                }
                risk_qty = size_order(
                    signal_dict, current_equity, atr, self.risk_params
                )
                if risk_qty:
                    base_size = risk_qty
                    stop_price, target_price = set_stops(
                        signal_dict, risk_qty, atr, self.risk_params
                    )

        if base_size < 1:
            return 0, None, None

        return base_size, stop_price, target_price

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

    def on_start(self) -> None:
        """Called when backtest starts."""
        self.position_entry_times.clear()
        self.position_stop_prices.clear()
        self.position_targets.clear()

    def on_end(self) -> None:
        """Called when backtest ends."""
        pass


class VwapRevertPolicyEnhanced(VwapRevertPolicy):
    """Enhanced VWAP revert policy with additional features."""

    def __init__(
        self,
        vwap_window: int = 30,
        min_rvol: float = 1.0,
        max_position_bars: int = 50,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        atr_window: int = 14,
        atr_multiplier: float = 2.0,
        min_profit_atr: float = 0.5,
        name: str = "VwapRevertEnhanced",
    ):
        """Initialize enhanced VWAP revert policy.

        Args:
            vwap_window: VWAP lookback window in minutes
            min_rvol: Minimum relative volume for entry
            max_position_bars: Maximum bars to hold position
            position_size_pct: Position size as percentage of equity
            max_positions: Maximum concurrent positions
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
        """Check for enhanced entry signal."""
        # Entry criteria with additional filters
        if (
            close < vwap
            and rvol >= self.min_rvol
            and atr > 0  # Valid ATR
            and (vwap - close) >= (self.min_profit_atr * atr)
        ):  # Sufficient profit potential

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
            base_size_tuple = self._calculate_position_size(close, bar)
            base_size = base_size_tuple[0]  # Extract just the position size from tuple
            volatility_adjustment = max(
                0.5, 1.0 - volatility_ratio * 5
            )  # Reduce size in high volatility
            position_size = int(base_size * volatility_adjustment)

            if position_size > 0:
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=position_size,
                    tags={
                        "policy": self.name,
                        "entry_price": close,
                        "vwap": vwap,
                        "rvol": rvol,
                        "atr": atr,
                        "signal_strength": (vwap - close) / vwap,
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

        # Calculate stop loss price
        stop_loss_price = position.avg_cost - (atr * self.atr_multiplier)
        profit_target_price = position.avg_cost + (atr * self.min_profit_atr)

        exit_reason = None

        # Enhanced exit criteria
        if close >= vwap:
            exit_reason = "vwap_target"
        elif close <= stop_loss_price:
            exit_reason = "stop_loss"
        elif close >= profit_target_price:
            exit_reason = "profit_target"
        elif bars_held >= self.max_position_bars:
            exit_reason = "timeout"
        # Could add trailing stop here

        if exit_reason:
            # Check for pending sell orders
            pending_orders = self.get_pending_orders(symbol)
            sell_pending = any(order.side == OrderSide.SELL for order in pending_orders)

            if not sell_pending:
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=position.quantity,
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
                            (close - position.avg_cost) / atr if atr > 0 else 0
                        ),
                    },
                )

                self.submit_order(order)


# Legacy function for backward compatibility
def generate_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Generate signals for VWAP reversion strategy (legacy function).

    Args:
        df: DataFrame with bars and features
        params: Parameters dict with rvol_min, vwap_col, rvol_col, timeout_bars, sip_universe (optional)

    Returns:
        DataFrame with signals: ts, symbol, signal (1=long, 0=flat), and diagnostic columns
    """
    rvol_min = params.get("rvol_min", 1.0)
    vwap_col = params.get("vwap_col", "f__ta__vwap_30")
    rvol_col = params.get("rvol_col", "f__vol__rel_volume_30")
    timeout_bars = params.get("timeout_bars", 10)
    sip_universe = params.get("sip_universe")  # Dict[ts, Set[symbols]] or None

    signals = []
    position_tracker = {}  # symbol -> {'entry_ts': ts, 'bars_held': int}

    for idx, row in df.iterrows():
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

        # Decision logic
        decision = "hold"
        if pos_before_decision["entry_ts"] is not None:
            # In position
            new_bars_held = pos_before_decision["bars_held"] + 1
            if close >= vwap or new_bars_held >= timeout_bars:
                decision = "exit"
                position_tracker[symbol] = {"entry_ts": None, "bars_held": 0}
            else:
                position_tracker[symbol]["bars_held"] = new_bars_held
        # Flat
        elif close < vwap and rvol >= rvol_min and in_sip and warmup_ok:
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
            "in_sip": in_sip,
            "warmup_ok": warmup_ok,
            "bars_held": pos_after_decision["bars_held"],
            "decision": decision,
        }
        signals.append(diag)

    return pd.DataFrame(signals)
