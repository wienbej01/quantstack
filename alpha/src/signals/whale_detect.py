"""Whale Detection Signal (Hypothesis 2).

Hypothesis: Large institutional orders signal informed trading.

Entry Conditions (LONG):
- Large bid detected (>5x average size at any level)
- Direction matches recent flow (positive trade_imbalance)
- Stock in play (elevated RVOL)

Entry Conditions (SHORT):
- Large ask detected (>5x average size)
- Direction matches recent flow (negative trade_imbalance)
- Stock in play (elevated RVOL)

Exit:
- Target: +0.8% (LONG) / -0.8% (SHORT)
- Stop: -0.4% (LONG) / +0.4% (SHORT)
- Time limit: 30 minutes

Horizon: 15-30 minutes (follow the institutional flow)
"""

import logging
from typing import Optional

import pandas as pd

from .base import ExitEvent, Position, Signal, SignalEvent, SignalSide

logger = logging.getLogger(__name__)


class WhaleDetectSignal(Signal):
    """H2: Whale Detection Signal.

    Entry when large institutional order detected in order book
    AND direction matches recent trade flow AND stock showing unusual activity.

    Exit on target, stop, or time limit.
    """

    def __init__(self, config: dict):
        """Initialize whale detection signal.

        Config defaults (can be overridden):
            large_order_mult: 5.0 (multiplier for avg size to detect "large")
            min_rvol: 1.5 (minimum relative volume for "in play")
            min_flow_imb: 0.1 (minimum trade imbalance for confirmation)
            target_pct: 0.8
            stop_pct: 0.4
            time_limit_minutes: 30
        """
        super().__init__(config)

        # Entry thresholds
        signals_cfg = config.get("signals", {}).get("whale_detect", {})
        self.large_order_mult = signals_cfg.get("large_order_mult", 5.0)
        self.min_rvol = signals_cfg.get("min_rvol", 1.5)
        self.min_flow_imb = signals_cfg.get("min_flow_imb", 0.1)

        # Exit parameters
        self.target_pct = signals_cfg.get("target_pct", 0.8) / 100
        self.stop_pct = signals_cfg.get("stop_pct", 0.4) / 100
        self.time_limit_minutes = signals_cfg.get("time_limit_minutes", 30)

        logger.info(
            f"WhaleDetectSignal initialized: "
            f"large_order_mult={self.large_order_mult}x, "
            f"min_rvol={self.min_rvol}, "
            f"min_flow_imb={self.min_flow_imb}, "
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
        """Check entry conditions for whale detection signal.

        LONG Entry:
        - has_large_bid == True
        - trade_imbalance > min_flow_imb (flow confirms direction)
        - rvol > min_rvol (stock in play)

        SHORT Entry: Opposite conditions
        """
        # Extract required features
        has_large_bid = features.get("has_large_bid", False)
        has_large_ask = features.get("has_large_ask", False)
        trade_imb = features.get("trade_imbalance_5")
        rvol = features.get("rvol")

        # Check if features are available
        if trade_imb is None or rvol is None:
            return None

        # Check LONG entry
        long_condition = (
            has_large_bid and trade_imb > self.min_flow_imb and rvol > self.min_rvol
        )

        if long_condition:
            # Confidence based on size of order and volume confirmation
            large_bid_count = features.get("large_bid_count", 1)
            confidence = min(1.0, (large_bid_count / 5) + (rvol - 1.0) / 4)

            return SignalEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                side=SignalSide.LONG,
                confidence=confidence,
                features={
                    "has_large_bid": has_large_bid,
                    "trade_imbalance": trade_imb,
                    "rvol": rvol,
                    "large_bid_count": large_bid_count,
                },
                signal_name=self.signal_name,
            )

        # Check SHORT entry
        short_condition = (
            has_large_ask and trade_imb < -self.min_flow_imb and rvol > self.min_rvol
        )

        if short_condition:
            # Confidence based on size of order and volume confirmation
            large_ask_count = features.get("large_ask_count", 1)
            confidence = min(1.0, (large_ask_count / 5) + (rvol - 1.0) / 4)

            return SignalEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                side=SignalSide.SHORT,
                confidence=confidence,
                features={
                    "has_large_ask": has_large_ask,
                    "trade_imbalance": trade_imb,
                    "rvol": rvol,
                    "large_ask_count": large_ask_count,
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
        1. Target hit (price moved in favor)
        2. Stop loss hit (price moved against)
        3. Time limit exceeded
        4. Whale reversal (opposite large order detected)
        """
        # Check target/stop first (most common exits)
        target_stop_exit = self._check_target_stop_exit(position, bar)
        if target_stop_exit:
            return target_stop_exit

        # Check time limit
        time_exit = self._check_time_limit_exit(position, timestamp)
        if time_exit:
            return time_exit

        # Check whale reversal (opposite large order detected)
        reversal_exit = self._check_whale_reversal(features, bar, timestamp)
        if reversal_exit:
            return reversal_exit

        return None

    def _check_whale_reversal(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[ExitEvent]:
        """Check if opposite large order has appeared.

        For LONG position: check if large ask appeared (whale flipping)
        For SHORT position: check if large bid appeared
        """
        has_large_bid = features.get("has_large_bid", False)
        has_large_ask = features.get("has_large_ask", False)

        # Large ask appearing suggests whale flipping to short
        if has_large_ask:
            return ExitEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                reason="signal_reverse",
            )

        # Large bid appearing suggests whale flipping to long
        if has_large_bid:
            return ExitEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                reason="signal_reverse",
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
