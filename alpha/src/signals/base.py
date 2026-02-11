"""Base signal interface for Alpha hypothesis signals.

All signals inherit from Signal and implement:
- check_entry(): Evaluate entry conditions
- check_exit(): Evaluate exit conditions for an open position

Temporal integrity: Signals are evaluated on bar N. If entry conditions are met,
the trade executes at the OPEN of bar N+1 (next bar), with slippage applied.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd


class SignalSide(Enum):
    """Signal direction."""

    LONG = "long"
    SHORT = "short"


@dataclass
class SignalEvent:
    """Entry signal generated at bar close.

    Note: Trade executes at next bar's open with slippage.
    """

    symbol: str
    timestamp: pd.Timestamp
    side: SignalSide
    confidence: float  # 0-1, strength of the signal
    features: dict  # Feature values that triggered the signal
    signal_name: str  # Name of the signal that generated this

    def __post_init__(self):
        """Validate signal event."""
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")

        if self.confidence == 0:
            raise ValueError(
                "Confidence of 0 means no signal - don't create SignalEvent"
            )


@dataclass
class ExitEvent:
    """Exit signal for an open position.

    Note: Trade executes at next bar's open with slippage.
    """

    symbol: str
    timestamp: pd.Timestamp
    reason: str  # "target", "stop", "time_limit", "signal_reverse"
    exit_price: Optional[float] = None  # Reference price for exit (if known)


@dataclass
class Position:
    """Open position tracking.

    Note: Entry price is the actual execution price (next bar open + slippage),
    not the signal bar's close.
    """

    symbol: str
    side: SignalSide
    entry_price: float  # Actual execution price (open of bar after signal)
    entry_time: pd.Timestamp  # Time of entry execution
    quantity: int
    target_price: float  # Profit target
    stop_price: float  # Stop loss
    time_limit_minutes: int  # Max hold time
    signal_name: str  # Which signal created this position

    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized P&L given current price.

        This requires external current price - computed at backtest level.
        """
        raise NotImplementedError("Use backtest engine for P&L calculation")

    def age_minutes(self, current_time: pd.Timestamp) -> float:
        """Calculate position age in minutes."""
        return (current_time - self.entry_time).total_seconds() / 60


class Signal(ABC):
    """Base class for all trading signals.

    Each signal implements entry and exit logic for one hypothesis.
    """

    def __init__(self, config: dict):
        """Initialize signal with configuration.

        Args:
            config: Configuration dict with signal-specific parameters
        """
        self.config = config
        self.signal_name = self.__class__.__name__

    @abstractmethod
    def check_entry(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[SignalEvent]:
        """Check if entry conditions are met.

        Called at bar close. If conditions met, trade executes at NEXT bar open.

        Args:
            features: Dict of computed feature values
            bar: Current bar data (OHLCV)
            timestamp: Current bar timestamp

        Returns:
            SignalEvent if entry conditions met, None otherwise
        """
        pass

    @abstractmethod
    def check_exit(
        self,
        position: Position,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[ExitEvent]:
        """Check if exit conditions are met for an open position.

        Called at bar close. If exit triggered, executes at NEXT bar open.

        Exit conditions:
        - Target hit: price moved in favor by target_pct
        - Stop hit: price moved against by stop_pct
        - Time limit: position held too long
        - Signal reversal: opposite signal detected

        Args:
            position: Open position
            features: Dict of computed feature values
            bar: Current bar data (OHLCV)
            timestamp: Current bar timestamp

        Returns:
            ExitEvent if exit conditions met, None otherwise
        """
        pass

    def _check_target_stop_exit(
        self,
        position: Position,
        bar: pd.Series,
    ) -> Optional[ExitEvent]:
        """Check if target or stop loss is hit.

        Args:
            position: Open position
            bar: Current bar data

        Returns:
            ExitEvent if target/stop hit, None otherwise
        """
        if position.side == SignalSide.LONG:
            # Long position
            if bar["low"] <= position.stop_price:
                return ExitEvent(
                    symbol=position.symbol,
                    timestamp=bar["ts"],
                    reason="stop",
                    exit_price=position.stop_price,
                )
            if bar["high"] >= position.target_price:
                return ExitEvent(
                    symbol=position.symbol,
                    timestamp=bar["ts"],
                    reason="target",
                    exit_price=position.target_price,
                )
        else:
            # Short position
            if bar["high"] >= position.stop_price:
                return ExitEvent(
                    symbol=position.symbol,
                    timestamp=bar["ts"],
                    reason="stop",
                    exit_price=position.stop_price,
                )
            if bar["low"] <= position.target_price:
                return ExitEvent(
                    symbol=position.symbol,
                    timestamp=bar["ts"],
                    reason="target",
                    exit_price=position.target_price,
                )

        return None

    def _check_time_limit_exit(
        self,
        position: Position,
        timestamp: pd.Timestamp,
    ) -> Optional[ExitEvent]:
        """Check if time limit is exceeded.

        Args:
            position: Open position
            timestamp: Current timestamp

        Returns:
            ExitEvent if time limit exceeded, None otherwise
        """
        age_minutes = position.age_minutes(timestamp)

        if age_minutes >= position.time_limit_minutes:
            return ExitEvent(
                symbol=position.symbol,
                timestamp=timestamp,
                reason="time_limit",
            )

        return None
