"""Liquidity Fade Signal (Hypothesis 3).

Hypothesis: Sudden liquidity withdrawal creates mean-reversion opportunity.

Entry Conditions (LONG):
- Depth drop detected (>50% withdrawal on bid side)
- Price spike downward (opposite direction - panic selling)
- No news (assumed - no news filter in MVP)

Entry Conditions (SHORT):
- Depth drop detected (>50% withdrawal on ask side)
- Price spike upward (opposite direction - panic buying)

Exit:
- Target: +0.3% (LONG) / -0.3% (SHORT)
- Stop: -0.3% (LONG) / +0.3% (SHORT) (tight stop due to volatility)
- Time limit: 5 minutes (quick mean reversion)

Horizon: 3-10 minutes (very short-term liquidity event)
"""

import logging
from typing import Optional

import pandas as pd

from .base import Position, Signal, SignalEvent, SignalSide, ExitEvent

logger = logging.getLogger(__name__)


class LiquidityFadeSignal(Signal):
    """H3: Liquidity Fade / Liquidity Vacuum Signal.

    Entry when sudden depth withdrawal detected AND price moves opposite
    (suggesting panic trading that will revert).

    Exit on target, stop, or time limit (very short duration).
    """

    def __init__(self, config: dict):
        """Initialize liquidity fade signal.

        Config defaults (can be overridden):
            depth_drop_threshold: 0.5 (50% depth drop to trigger)
            price_spike_pct: 0.2 (0.2% price move required)
            target_pct: 0.3
            stop_pct: 0.3
            time_limit_minutes: 5
        """
        super().__init__(config)

        # Entry thresholds
        signals_cfg = config.get("signals", {}).get("liquidity_fade", {})
        self.depth_drop_threshold = signals_cfg.get("depth_drop_threshold", 0.5)
        self.price_spike_pct = signals_cfg.get("price_spike_pct", 0.2) / 100

        # Exit parameters (tighter due to higher volatility)
        self.target_pct = signals_cfg.get("target_pct", 0.3) / 100
        self.stop_pct = signals_cfg.get("stop_pct", 0.3) / 100
        self.time_limit_minutes = signals_cfg.get("time_limit_minutes", 5)

        logger.info(
            f"LiquidityFadeSignal initialized: "
            f"depth_drop_threshold={self.depth_drop_threshold*100}%, "
            f"price_spike_pct={self.price_spike_pct*100}%, "
            f"target={self.target_pct*100}%, "
            f"stop={self.stop_pct*100}%, "
            f"time_limit={self.time_limit_minutes}min"
        )

    def check_entry(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[SignalEvent]:
        """Check entry conditions for liquidity fade signal.

        LONG Entry (fade the panic sell):
        - bid_drop_pct > threshold (liquidity withdrawn on bid side)
        - Price moved down (negative return) indicating panic

        SHORT Entry (fade the panic buy):
        - ask_drop_pct > threshold (liquidity withdrawn on ask side)
        - Price moved up (positive return) indicating panic
        """
        # Extract required features
        depth_drop_detected = features.get("depth_drop_detected", False)
        bid_drop_pct = features.get("bid_drop_pct", 0)
        ask_drop_pct = features.get("ask_drop_pct", 0)

        # Check for price spike (use recent return)
        ret_5 = features.get("ret_5", 0)

        # Check LONG entry (fade panic selling)
        long_condition = (
            depth_drop_detected
            and bid_drop_pct > self.depth_drop_threshold
            and ret_5 < -self.price_spike_pct  # Price dropped (panic sell)
        )

        if long_condition:
            # Confidence based on severity of drop
            confidence = min(1.0, bid_drop_pct / (2 * self.depth_drop_threshold))

            return SignalEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                side=SignalSide.LONG,
                confidence=confidence,
                features={
                    "depth_drop_detected": depth_drop_detected,
                    "bid_drop_pct": bid_drop_pct,
                    "ask_drop_pct": ask_drop_pct,
                    "ret_5": ret_5,
                },
                signal_name=self.signal_name,
            )

        # Check SHORT entry (fade panic buying)
        short_condition = (
            depth_drop_detected
            and ask_drop_pct > self.depth_drop_threshold
            and ret_5 > self.price_spike_pct  # Price rose (panic buy)
        )

        if short_condition:
            # Confidence based on severity of drop
            confidence = min(1.0, ask_drop_pct / (2 * self.depth_drop_threshold))

            return SignalEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                side=SignalSide.SHORT,
                confidence=confidence,
                features={
                    "depth_drop_detected": depth_drop_detected,
                    "bid_drop_pct": bid_drop_pct,
                    "ask_drop_pct": ask_drop_pct,
                    "ret_5": ret_5,
                },
                signal_name=self.signal_name,
            )

        return None

    def check_exit(
        self,
        position: Position,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[ExitEvent]:
        """Check exit conditions for open position.

        Exit triggers:
        1. Target hit (quick mean reversion achieved)
        2. Stop loss hit (fade failed - volatility too high)
        3. Time limit exceeded (very short window for this signal)
        4. Liquidity restored (depth returned, fade condition over)
        """
        # Check target/stop first (most common exits)
        target_stop_exit = self._check_target_stop_exit(position, bar)
        if target_stop_exit:
            return target_stop_exit

        # Check time limit (very important for this signal)
        time_exit = self._check_time_limit_exit(position, timestamp)
        if time_exit:
            return time_exit

        # Check if liquidity restored (fade condition over)
        restoration_exit = self._check_liquidity_restoration(features, bar, timestamp)
        if restoration_exit:
            return restoration_exit

        return None

    def _check_liquidity_restoration(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[ExitEvent]:
        """Check if liquidity has been restored.

        If depth has recovered (no longer dropping), the liquidity vacuum
        condition has ended. Exit to avoid further exposure.
        """
        depth_drop_detected = features.get("depth_drop_detected", False)

        # If depth drop no longer detected, liquidity restored
        if not depth_drop_detected:
            return ExitEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                reason="signal_reverse",  # Use same reason - condition ended
            )

        return None

    def create_position(
        self,
        signal: SignalEvent,
        entry_price: float,
        entry_time: pd.Timestamp,
        quantity: int,
    ) -> Position:
        """Create a Position from a SignalEvent.

        Args:
            signal: The signal event that triggered entry
            entry_price: Actual execution price (next bar open + slippage)
            entry_time: Time of entry execution
            quantity: Position size (shares)

        Returns:
            Position object with target and stop prices set
        """
        if signal.side == SignalSide.LONG:
            target_price = entry_price * (1 + self.target_pct)
            stop_price = entry_price * (1 - self.stop_pct)
        else:
            target_price = entry_price * (1 - self.target_pct)
            stop_price = entry_price * (1 + self.stop_pct)

        return Position(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=entry_price,
            entry_time=entry_time,
            quantity=quantity,
            target_price=target_price,
            stop_price=stop_price,
            time_limit_minutes=self.time_limit_minutes,
            signal_name=self.signal_name,
        )
