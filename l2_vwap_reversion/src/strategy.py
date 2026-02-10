"""Core VWAP mean reversion strategy logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Callable
from zoneinfo import ZoneInfo

from vwap import VWAPCalculator
from l2_filter import L2Filter
from data.bar_feed import Bar

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class Side(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Position:
    """Active position state."""

    symbol: str
    side: Side
    entry_price: float
    entry_time: datetime
    shares: int


@dataclass
class Signal:
    """Trade signal."""

    symbol: str
    side: Side
    price: float
    timestamp: datetime
    vwap: float
    l2_ratio: float | None


class Strategy:
    """L2 VWAP Mean Reversion strategy."""

    def __init__(self, config: dict, on_signal: Callable[[Signal], None] | None = None):
        self.config = config
        self.on_signal = on_signal

        # Components
        self.vwap = VWAPCalculator()
        self.l2_filter = L2Filter(config)

        # Strategy parameters
        strat_cfg = config.get("strategy", {})
        vwap_cfg = config.get("vwap", {})
        exits_cfg = config.get("exits", {})
        timing_cfg = config.get("timing", {})
        risk_cfg = config.get("risk", {})

        self.deviation_long = vwap_cfg.get("deviation_long", 0.995)
        self.deviation_short = vwap_cfg.get("deviation_short", 1.005)

        self.mean_reversion_exit = exits_cfg.get("mean_reversion", True)
        self.tp_long = exits_cfg.get("take_profit_long", 1.005)
        self.tp_short = exits_cfg.get("take_profit_short", 0.995)
        self.sl_long = exits_cfg.get("stop_loss_long", 0.9925)
        self.sl_short = exits_cfg.get("stop_loss_short", 1.0075)

        self.entry_start = self._parse_time(timing_cfg.get("entry_start", "09:35"))
        self.entry_end = self._parse_time(timing_cfg.get("entry_end", "15:30"))
        self.forced_exit = self._parse_time(timing_cfg.get("forced_exit", "15:55"))

        self.position_size = risk_cfg.get("position_size", 100)
        self.max_positions = risk_cfg.get("max_positions", 1)

        # State
        self.position: Position | None = None
        self._trade_date: date | None = None

    def _parse_time(self, time_str: str) -> time:
        """Parse HH:MM time string."""
        h, m = map(int, time_str.split(":"))
        return time(h, m)

    def reset_day(self, trade_date: date) -> None:
        """Reset state for new trading day."""
        self.vwap.reset_all()
        self.l2_filter.reset_day()
        self.position = None
        self._trade_date = trade_date
        logger.info(f"Strategy reset for {trade_date}")

    def on_bar(self, bar: Bar) -> Signal | None:
        """Process incoming bar, return signal if generated."""
        now_et = bar.timestamp.astimezone(ET) if bar.timestamp.tzinfo else bar.timestamp.replace(tzinfo=ET)
        current_time = now_et.time()
        trade_date = now_et.date()

        # Reset on new day
        if self._trade_date != trade_date:
            self.reset_day(trade_date)

        # Update VWAP
        vwap_value = self.vwap.update(
            bar.symbol, bar.high, bar.low, bar.close, bar.volume
        )

        # Check for exit first
        if self.position and self.position.symbol == bar.symbol:
            exit_signal = self._check_exit(bar, vwap_value, current_time)
            if exit_signal:
                return exit_signal

        # Check for entry
        if self.position is None:
            entry_signal = self._check_entry(bar, vwap_value, current_time, trade_date)
            if entry_signal:
                return entry_signal

        return None

    def _check_entry(self, bar: Bar, vwap: float, current_time: time, trade_date: date) -> Signal | None:
        """Check entry conditions."""
        # Time window check
        if not (self.entry_start <= current_time <= self.entry_end):
            logger.debug(f"{bar.symbol}: Outside entry window {current_time}")
            return None

        # Already have position
        if self.position is not None:
            return None

        deviation = bar.close / vwap if vwap > 0 else 1.0
        
        logger.info(f"{bar.symbol}: C={bar.close:.2f} VWAP={vwap:.2f} dev={deviation:.4f}")

        # Long entry: close <= VWAP * 0.995
        if deviation <= self.deviation_long:
            if self.l2_filter.check_long(bar.symbol, trade_date):
                l2_ratio = self.l2_filter.get_ratio(bar.symbol, trade_date)
                signal = Signal(
                    symbol=bar.symbol,
                    side=Side.LONG,
                    price=bar.close,
                    timestamp=bar.timestamp,
                    vwap=vwap,
                    l2_ratio=l2_ratio,
                )
                logger.info(f"LONG signal: {bar.symbol} @ {bar.close:.2f}, VWAP={vwap:.2f}, L2={l2_ratio}")
                return signal

        # Short entry: close >= VWAP * 1.005
        if deviation >= self.deviation_short:
            if self.l2_filter.check_short(bar.symbol, trade_date):
                l2_ratio = self.l2_filter.get_ratio(bar.symbol, trade_date)
                signal = Signal(
                    symbol=bar.symbol,
                    side=Side.SHORT,
                    price=bar.close,
                    timestamp=bar.timestamp,
                    vwap=vwap,
                    l2_ratio=l2_ratio,
                )
                logger.info(f"SHORT signal: {bar.symbol} @ {bar.close:.2f}, VWAP={vwap:.2f}, L2={l2_ratio}")
                return signal

        return None

    def _check_exit(self, bar: Bar, vwap: float, current_time: time) -> Signal | None:
        """Check exit conditions for current position."""
        if self.position is None:
            return None

        pos = self.position
        price = bar.close

        # Forced exit at 15:55
        if current_time >= self.forced_exit:
            logger.info(f"FORCED EXIT: {pos.symbol} @ {price:.2f}")
            return self._create_exit_signal(bar, vwap, "forced_exit")

        if pos.side == Side.LONG:
            # Mean reversion: close >= VWAP
            if self.mean_reversion_exit and price >= vwap:
                logger.info(f"LONG EXIT (mean reversion): {pos.symbol} @ {price:.2f}")
                return self._create_exit_signal(bar, vwap, "mean_reversion")

            # Take profit: close >= entry * 1.005
            if price >= pos.entry_price * self.tp_long:
                logger.info(f"LONG EXIT (take profit): {pos.symbol} @ {price:.2f}")
                return self._create_exit_signal(bar, vwap, "take_profit")

            # Stop loss: close <= entry * 0.9925
            if price <= pos.entry_price * self.sl_long:
                logger.info(f"LONG EXIT (stop loss): {pos.symbol} @ {price:.2f}")
                return self._create_exit_signal(bar, vwap, "stop_loss")

        elif pos.side == Side.SHORT:
            # Mean reversion: close <= VWAP
            if self.mean_reversion_exit and price <= vwap:
                logger.info(f"SHORT EXIT (mean reversion): {pos.symbol} @ {price:.2f}")
                return self._create_exit_signal(bar, vwap, "mean_reversion")

            # Take profit: close <= entry * 0.995
            if price <= pos.entry_price * self.tp_short:
                logger.info(f"SHORT EXIT (take profit): {pos.symbol} @ {price:.2f}")
                return self._create_exit_signal(bar, vwap, "take_profit")

            # Stop loss: close >= entry * 1.0075
            if price >= pos.entry_price * self.sl_short:
                logger.info(f"SHORT EXIT (stop loss): {pos.symbol} @ {price:.2f}")
                return self._create_exit_signal(bar, vwap, "stop_loss")

        return None

    def _create_exit_signal(self, bar: Bar, vwap: float, reason: str) -> Signal:
        """Create exit signal (opposite side of position)."""
        pos = self.position
        exit_side = Side.SHORT if pos.side == Side.LONG else Side.LONG
        return Signal(
            symbol=bar.symbol,
            side=exit_side,
            price=bar.close,
            timestamp=bar.timestamp,
            vwap=vwap,
            l2_ratio=None,
        )

    def open_position(
        self,
        symbol: str,
        side: Side,
        entry_price: float,
        entry_time: datetime,
        *,
        shares: int | None = None,
    ) -> None:
        """Record position opened.

        `shares` should reflect the intended order quantity. If fills arrive with
        a different final quantity, the execution callback should update the
        position shares to the actual filled size.
        """
        self.position = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            entry_time=entry_time,
            shares=int(shares) if shares is not None else int(self.position_size),
        )
        logger.info(f"Position opened: {side.value} {symbol} @ {entry_price:.2f}")

    def close_position(self) -> Position | None:
        """Close current position, return closed position."""
        pos = self.position
        self.position = None
        if pos:
            logger.info(f"Position closed: {pos.side.value} {pos.symbol}")
        return pos
