"""Order Flow Imbalance Signal (Hypothesis 1).

Hypothesis: Order flow imbalance at book and trade levels predicts short-term direction.

Entry Conditions (LONG):
- book_imbalance > 0.35 (strong buying pressure in order book)
- trade_imbalance > 0.25 (buying pressure in trades)
- spread_pct < 0.05% (tight spread, good liquidity)

Entry Conditions (SHORT):
- book_imbalance < -0.35 (strong selling pressure)
- trade_imbalance < -0.25
- spread_pct < 0.05%

Exit:
- Target: +0.4% (LONG) / -0.4% (SHORT)
- Stop: -0.25% (LONG) / +0.25% (SHORT)
- Time limit: 10 minutes

Horizon: 5-15 minutes (intraday mean reversion/momentum)
"""

import logging
from typing import Optional

import pandas as pd

from .base import ExitEvent, Position, Signal, SignalEvent, SignalSide

logger = logging.getLogger(__name__)


class OrderFlowSignal(Signal):
    """H1: Order Flow Imbalance Signal.

    Entry when both book and trade flow show strong directional pressure
    with tight spreads (good execution quality).

    Exit on target, stop, or time limit.
    """

    def __init__(self, config: dict):
        """Initialize order flow signal.

        Config defaults (can be overridden):
            book_imb_threshold: 0.35
            trade_imb_threshold: 0.25
            max_spread_pct: 0.05
            target_pct: 0.4
            stop_pct: 0.25
            time_limit_minutes: 10
        """
        super().__init__(config)

        # Entry thresholds
        signals_cfg = config.get("signals", {}).get("order_flow", {})
        self.book_imb_threshold = signals_cfg.get("book_imbalance_threshold", 0.35)
        self.trade_imb_threshold = signals_cfg.get("trade_imbalance_threshold", 0.25)
        self.max_spread_pct = signals_cfg.get("max_spread_pct", 0.05)

        # Exit parameters
        self.target_pct = signals_cfg.get("target_pct", 0.4) / 100
        self.stop_pct = signals_cfg.get("stop_pct", 0.25) / 100
        self.time_limit_minutes = signals_cfg.get("time_limit_minutes", 10)

        logger.info(
            f"OrderFlowSignal initialized: "
            f"book_imb={self.book_imb_threshold}, "
            f"trade_imb={self.trade_imb_threshold}, "
            f"max_spread={self.max_spread_pct}%, "
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
        """Check entry conditions for order flow signal.

        LONG Entry:
        - book_imbalance_5 > threshold
        - trade_imbalance_5 > threshold
        - spread % < max_spread_pct

        SHORT Entry: Opposite conditions
        """
        # Extract required features
        book_imb = features.get("book_imbalance_5")
        trade_imb = features.get("trade_imbalance_5")
        spread = features.get("spread")

        # Check if features are available
        if book_imb is None or trade_imb is None or spread is None:
            return None

        # Calculate spread percentage
        if bar["close"] > 0:
            spread_pct = (spread / bar["close"]) * 100
        else:
            return None

        # Check LONG entry
        long_condition = (
            book_imb > self.book_imb_threshold
            and trade_imb > self.trade_imb_threshold
            and spread_pct < self.max_spread_pct
        )

        if long_condition:
            # Confidence based on strength of imbalance
            confidence = min(
                1.0,
                (book_imb + trade_imb)
                / (2 * max(self.book_imb_threshold, self.trade_imb_threshold)),
            )

            return SignalEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                side=SignalSide.LONG,
                confidence=confidence,
                features={
                    "book_imbalance": book_imb,
                    "trade_imbalance": trade_imb,
                    "spread_pct": spread_pct,
                },
                signal_name=self.signal_name,
            )

        # Check SHORT entry
        short_condition = (
            book_imb < -self.book_imb_threshold
            and trade_imb < -self.trade_imb_threshold
            and spread_pct < self.max_spread_pct
        )

        if short_condition:
            # Confidence based on strength of imbalance
            confidence = min(
                1.0,
                (abs(book_imb) + abs(trade_imb))
                / (2 * max(self.book_imb_threshold, self.trade_imb_threshold)),
            )

            return SignalEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                side=SignalSide.SHORT,
                confidence=confidence,
                features={
                    "book_imbalance": book_imb,
                    "trade_imbalance": trade_imb,
                    "spread_pct": spread_pct,
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
        4. Signal reversal (opposite signal detected)
        """
        # Check target/stop first (most common exits)
        target_stop_exit = self._check_target_stop_exit(position, bar)
        if target_stop_exit:
            return target_stop_exit

        # Check time limit
        time_exit = self._check_time_limit_exit(position, timestamp)
        if time_exit:
            return time_exit

        # Check signal reversal
        reversal_exit = self._check_signal_reversal(features, bar, timestamp)
        if reversal_exit:
            return reversal_exit

        return None

    def _check_signal_reversal(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[ExitEvent]:
        """Check if opposite signal has appeared.

        For LONG position, check if strong SHORT signal appeared.
        For SHORT position, check if strong LONG signal appeared.
        """
        book_imb = features.get("book_imbalance_5")
        trade_imb = features.get("trade_imbalance_5")

        if book_imb is None or trade_imb is None:
            return None

        # Check for LONG reversal (if we're SHORT)
        reversal_strength = (
            1.5 * self.book_imb_threshold
        )  # Need stronger signal to reverse

        if book_imb > reversal_strength and trade_imb > reversal_strength:
            return ExitEvent(
                symbol=bar.get("symbol", "UNKNOWN"),
                timestamp=timestamp,
                reason="signal_reverse",
            )

        # Check for SHORT reversal (if we're LONG)
        if book_imb < -reversal_strength and trade_imb < -reversal_strength:
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
