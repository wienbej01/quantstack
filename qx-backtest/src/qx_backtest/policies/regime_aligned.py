from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from qx_core.schemas import RegimeType

from ..order import MarketOrder, OrderSide, OrderType
from .base import Policy


@dataclass
class MomentumParameters:
    """Parameters for AVWAP Momentum strategy."""
    atr_stop_multiple: float = 1.0
    atr_target_multiple: float = 1.5
    max_position_bars: int = 60  # New: timeout exit
    enabled_regimes: list[RegimeType] = field(default_factory=lambda: [RegimeType.BULL, RegimeType.BEAR])


class AVWAPMomentumPolicy(Policy):
    """AVWAP Momentum strategy with correct position sizing and intraday logic."""

    def __init__(self, params: MomentumParameters | None = None):
        super().__init__("AVWAP_Momentum")
        self.params = params or MomentumParameters()
        self.active_orders: dict[str, dict] = {}
        self.trades_today: set[str] = set()
        self.current_day: datetime.date | None = None

    def process_bar(self, bar: dict[str, Any]) -> None:
        # Day tracking for one-trade-per-day rule
        bar_date = datetime.fromtimestamp(bar["ts"] / 1e9).date()
        if self.current_day != bar_date:
            self.current_day = bar_date
            print(f"DEBUG: New day: {bar_date}, clearing trades_today")
            self.trades_today.clear()

        if not self._is_allowed_regime(bar):
            return

        position = self.get_position(bar["symbol"])
        if position and not position.is_flat:
            self._manage_position(bar, position)
        else:
            self._check_entry(bar)

    def _is_allowed_regime(self, bar: dict[str, Any]) -> bool:
        current_regime = bar.get("f__regime__current", RegimeType.OFF)
        return current_regime in self.params.enabled_regimes

    def _check_entry(self, bar: dict[str, Any]) -> None:
        symbol = bar["symbol"]
        # Enforce one trade per day rule
        if symbol in self.trades_today:
            return

        if bar.get("f__regime__current") == RegimeType.BULL:
            self._enter_long(bar)
        elif bar.get("f__regime__current") == RegimeType.BEAR:
            self._enter_short(bar)

    def _enter_long(self, bar: dict[str, Any]) -> None:
        stop_level = bar["low"] * 0.99
        risk_per_share = bar["close"] - stop_level
        if risk_per_share <= 0:
            return

        order = MarketOrder(
            symbol=bar["symbol"],
            quantity=1,
            side=OrderSide.BUY,
            ts_submitted=bar["ts"],
            strategy_id=self.strategy_id,
        )
        self.submit_order(order)
        self.active_orders[bar["symbol"]] = {
            "stop_level": stop_level,
            "entry_bar_ts": bar["ts"],
            "entry_price": bar["close"],
        }
        print(f"DEBUG: Trade initiated for {order.symbol} on {self.current_day}")
        self.trades_today.add(order.symbol)

    def _enter_short(self, bar: dict[str, Any]) -> None:
        stop_level = bar["high"] * 1.01
        risk_per_share = stop_level - bar["close"]
        if risk_per_share <= 0:
            return

        order = MarketOrder(
            symbol=bar["symbol"],
            quantity=1,
            side=OrderSide.SELL,
            ts_submitted=bar["ts"],
            strategy_id=self.strategy_id,
        )
        self.submit_order(order)
        self.active_orders[bar["symbol"]] = {
            "stop_level": stop_level,
            "entry_bar_ts": bar["ts"],
            "entry_price": bar["close"],
        }
        print(f"DEBUG: Trade initiated for {order.symbol} on {self.current_day}")
        self.trades_today.add(order.symbol)

    def _manage_position(self, bar: dict[str, Any], position) -> None:
        symbol = bar["symbol"]
        active_trade = self.active_orders.get(symbol)
        if not active_trade:
            return

        stop_level = active_trade.get("stop_level")
        entry_price = active_trade.get("entry_price")
        atr = bar.get("f__vol__atr_14", 0)  # Assuming ATR is available

        # Calculate bars held
        bars_held = (bar["ts"] - active_trade["entry_bar_ts"]) // (60 * 1e9)

        exit_reason = None

        if position.is_long:
            if bar["low"] <= stop_level:
                exit_reason = "stop_loss"
            elif atr > 0 and bar["high"] >= entry_price + (atr * self.params.atr_target_multiple):
                exit_reason = "take_profit"
            elif bars_held >= self.params.max_position_bars:
                exit_reason = "timeout"
        elif position.is_short:
            if bar["high"] >= stop_level:
                exit_reason = "stop_loss"
            elif atr > 0 and bar["low"] <= entry_price - (atr * self.params.atr_target_multiple):
                exit_reason = "take_profit"
            elif bars_held >= self.params.max_position_bars:
                exit_reason = "timeout"

        if exit_reason:
            self._close_position(bar, position, exit_reason)

    def _close_position(self, bar: dict[str, Any], position, reason: str) -> None:
        symbol = bar["symbol"]
        order = MarketOrder(
            symbol=symbol,
            quantity=abs(position.quantity),
            side=OrderSide.SELL if position.is_long else OrderSide.BUY,
            ts_submitted=bar["ts"],
            strategy_id=self.strategy_id,
            tags={"exit_reason": reason},
        )
        self.submit_order(order)
        
        if symbol in self.active_orders:
            del self.active_orders[symbol]

    def on_end(self) -> None:
        pass

@dataclass
class PullbackParameters:
    """Parameters for AVWAP Pullback strategy."""
    atr_stop_multiple: float = 1.0
    atr_target_multiple: float = 1.5
    max_position_bars: int = 45
    pullback_dev_multiple: float = 0.5  # Deviation from AVWAP for entry
    enabled_regimes: list[RegimeType] = field(default_factory=lambda: [RegimeType.BULL, RegimeType.BEAR])


class AVWAPPullbackPolicy(Policy):
    """AVWAP Pullback strategy for trading reversions to the mean."""

    def __init__(self, params: PullbackParameters | None = None):
        super().__init__("AVWAP_Pullback")
        self.params = params or PullbackParameters()
        self.active_orders: dict[str, dict] = {}
        self.trades_today: set[str] = set()
        self.current_day: datetime.date | None = None

    def process_bar(self, bar: dict[str, Any]) -> None:
        bar_date = datetime.fromtimestamp(bar["ts"] / 1e9).date()
        if self.current_day != bar_date:
            self.current_day = bar_date
            self.trades_today.clear()

        if not self._is_allowed_regime(bar):
            return

        position = self.get_position(bar["symbol"])
        if position and not position.is_flat:
            self._manage_position(bar, position)
        else:
            self._check_entry(bar)

    def _is_allowed_regime(self, bar: dict[str, Any]) -> bool:
        current_regime = bar.get("f__regime__current", RegimeType.OFF)
        return current_regime in self.params.enabled_regimes

    def _check_entry(self, bar: dict[str, Any]) -> None:
        symbol = bar["symbol"]
        if symbol in self.trades_today:
            return

        if bar.get("f__regime__current") == RegimeType.BULL:
            self._enter_long(bar)
        elif bar.get("f__regime__current") == RegimeType.BEAR:
            self._enter_short(bar)

    def _enter_long(self, bar: dict[str, Any]) -> None:
        avwap = bar.get("f__anchor__session_avwap", 0)
        atr = bar.get("f__vol__atr_14", 0)
        if avwap == 0 or atr == 0:
            return

        # Buy pullback to AVWAP in a BULL market
        pullback_level = avwap - (atr * self.params.pullback_dev_multiple)
        if bar["close"] <= pullback_level:
            stop_level = pullback_level - (atr * self.params.atr_stop_multiple)
            risk_per_share = bar["close"] - stop_level
            if risk_per_share <= 0:
                return

            order = MarketOrder(symbol=bar["symbol"], quantity=1, side=OrderSide.BUY, ts_submitted=bar["ts"], strategy_id=self.strategy_id)
            self.submit_order(order)
            self.active_orders[bar["symbol"]] = {"stop_level": stop_level, "entry_bar_ts": bar["ts"], "entry_price": bar["close"]}
            self.trades_today.add(order.symbol)

    def _enter_short(self, bar: dict[str, Any]) -> None:
        avwap = bar.get("f__anchor__session_avwap", 0)
        atr = bar.get("f__vol__atr_14", 0)
        if avwap == 0 or atr == 0:
            return

        # Sell rally to AVWAP in a BEAR market
        rally_level = avwap + (atr * self.params.pullback_dev_multiple)
        if bar["close"] >= rally_level:
            stop_level = rally_level + (atr * self.params.atr_stop_multiple)
            risk_per_share = stop_level - bar["close"]
            if risk_per_share <= 0:
                return

            order = MarketOrder(symbol=bar["symbol"], quantity=1, side=OrderSide.SELL, ts_submitted=bar["ts"], strategy_id=self.strategy_id)
            self.submit_order(order)
            self.active_orders[bar["symbol"]] = {"stop_level": stop_level, "entry_bar_ts": bar["ts"], "entry_price": bar["close"]}
            self.trades_today.add(order.symbol)

    def _manage_position(self, bar: dict[str, Any], position) -> None:
        symbol = bar["symbol"]
        active_trade = self.active_orders.get(symbol)
        if not active_trade:
            return

        stop_level = active_trade.get("stop_level")
        entry_price = active_trade.get("entry_price")
        atr = bar.get("f__vol__atr_14", 0)
        bars_held = (bar["ts"] - active_trade["entry_bar_ts"]) // (60 * 1e9)

        exit_reason = None
        if position.is_long:
            if bar["low"] <= stop_level:
                exit_reason = "stop_loss"
            elif atr > 0 and bar["high"] >= entry_price + (atr * self.params.atr_target_multiple):
                exit_reason = "take_profit"
            elif bars_held >= self.params.max_position_bars:
                exit_reason = "timeout"
        elif position.is_short:
            if bar["high"] >= stop_level:
                exit_reason = "stop_loss"
            elif atr > 0 and bar["low"] <= entry_price - (atr * self.params.atr_target_multiple):
                exit_reason = "take_profit"
            elif bars_held >= self.params.max_position_bars:
                exit_reason = "timeout"

        if exit_reason:
            self._close_position(bar, position, exit_reason)

    def _close_position(self, bar: dict[str, Any], position, reason: str) -> None:
        symbol = bar["symbol"]
        order = MarketOrder(symbol=symbol, quantity=abs(position.quantity), side=OrderSide.SELL if position.is_long else OrderSide.BUY, ts_submitted=bar["ts"], strategy_id=self.strategy_id, tags={"exit_reason": reason})
        self.submit_order(order)
        if symbol in self.active_orders:
            del self.active_orders[symbol]

    def on_end(self) -> None:
        pass

@dataclass
class ValueRotationParameters:
    """Parameters for Value Rotation strategy."""
    atr_stop_multiple: float = 1.2
    max_position_bars: int = 90
    entry_dev_multiple: float = 0.1  # % deviation outside value area for entry
    enabled_regimes: list[RegimeType] = field(default_factory=lambda: [RegimeType.SIDEWAYS])


class ValueRotationPolicy(Policy):
    """Value Rotation strategy for trading mean reversion in sideways markets."""

    def __init__(self, params: ValueRotationParameters | None = None):
        super().__init__("Value_Rotation")
        self.params = params or ValueRotationParameters()
        self.active_orders: dict[str, dict] = {}
        self.trades_today: set[str] = set()
        self.current_day: datetime.date | None = None

    def process_bar(self, bar: dict[str, Any]) -> None:
        bar_date = datetime.fromtimestamp(bar["ts"] / 1e9).date()
        if self.current_day != bar_date:
            self.current_day = bar_date
            self.trades_today.clear()

        if not self._is_allowed_regime(bar):
            return

        position = self.get_position(bar["symbol"])
        if position and not position.is_flat:
            self._manage_position(bar, position)
        else:
            self._check_entry(bar)

    def _is_allowed_regime(self, bar: dict[str, Any]) -> bool:
        current_regime = bar.get("f__regime__current", RegimeType.OFF)
        return current_regime in self.params.enabled_regimes

    def _check_entry(self, bar: dict[str, Any]) -> None:
        symbol = bar["symbol"]
        if symbol in self.trades_today:
            return

        self._enter_long(bar)
        self._enter_short(bar)

    def _enter_long(self, bar: dict[str, Any]) -> None:
        val = bar.get("f__profile__val", 0)
        atr = bar.get("f__vol__atr_14", 0)
        if val == 0 or atr == 0:
            return

        entry_level = val * (1 - self.params.entry_dev_multiple / 100)
        if bar["close"] <= entry_level:
            stop_level = entry_level - (atr * self.params.atr_stop_multiple)
            risk_per_share = bar["close"] - stop_level
            if risk_per_share <= 0:
                return

            order = MarketOrder(symbol=bar["symbol"], quantity=1, side=OrderSide.BUY, ts_submitted=bar["ts"], strategy_id=self.strategy_id)
            self.submit_order(order)
            self.active_orders[bar["symbol"]] = {"stop_level": stop_level, "entry_bar_ts": bar["ts"], "entry_price": bar["close"]}
            self.trades_today.add(order.symbol)

    def _enter_short(self, bar: dict[str, Any]) -> None:
        vah = bar.get("f__profile__vah", 0)
        atr = bar.get("f__vol__atr_14", 0)
        if vah == 0 or atr == 0:
            return

        entry_level = vah * (1 + self.params.entry_dev_multiple / 100)
        if bar["close"] >= entry_level:
            stop_level = entry_level + (atr * self.params.atr_stop_multiple)
            risk_per_share = stop_level - bar["close"]
            if risk_per_share <= 0:
                return

            order = MarketOrder(symbol=bar["symbol"], quantity=1, side=OrderSide.SELL, ts_submitted=bar["ts"], strategy_id=self.strategy_id)
            self.submit_order(order)
            self.active_orders[bar["symbol"]] = {"stop_level": stop_level, "entry_bar_ts": bar["ts"], "entry_price": bar["close"]}
            self.trades_today.add(order.symbol)

    def _manage_position(self, bar: dict[str, Any], position) -> None:
        symbol = bar["symbol"]
        active_trade = self.active_orders.get(symbol)
        if not active_trade:
            return

        stop_level = active_trade.get("stop_level")
        poc = bar.get("f__profile__poc", 0)
        bars_held = (bar["ts"] - active_trade["entry_bar_ts"]) // (60 * 1e9)

        exit_reason = None
        if position.is_long:
            if bar["low"] <= stop_level:
                exit_reason = "stop_loss"
            elif poc > 0 and bar["high"] >= poc:  # Take profit at Point of Control
                exit_reason = "take_profit"
            elif bars_held >= self.params.max_position_bars:
                exit_reason = "timeout"
        elif position.is_short:
            if bar["high"] >= stop_level:
                exit_reason = "stop_loss"
            elif poc > 0 and bar["low"] <= poc:
                exit_reason = "take_profit"
            elif bars_held >= self.params.max_position_bars:
                exit_reason = "timeout"

        if exit_reason:
            self._close_position(bar, position, exit_reason)

    def _close_position(self, bar: dict[str, Any], position, reason: str) -> None:
        symbol = bar["symbol"]
        order = MarketOrder(symbol=symbol, quantity=abs(position.quantity), side=OrderSide.SELL if position.is_long else OrderSide.BUY, ts_submitted=bar["ts"], strategy_id=self.strategy_id, tags={"exit_reason": reason})
        self.submit_order(order)
        if symbol in self.active_orders:
            del self.active_orders[symbol]

    def on_end(self) -> None:
        pass