"""Decision Policy Module for Intraday ML

Implements probability gates, expected move thresholds, volatility-aware
cooldowns, and time-of-day filters to reduce micro-trades.
"""

from datetime import datetime, time
from typing import Any, Dict, Optional, Tuple

import pandas as pd


class DecisionPolicy:
    """Decision policy to reduce micro-trades through soft constraints."""

    def __init__(self, decision_config: Dict[str, Any]):
        """Initialize decision policy with configuration.

        Args:
            decision_config: Decision policy configuration
        """
        self.config = decision_config
        self.probability_threshold = decision_config.get("probability_threshold", 0.65)
        self.expected_move_multiplier = decision_config.get(
            "expected_move_multiplier", 0.8
        )
        self.cooldown_config = decision_config.get("cooldown", {})
        self.time_filter_config = decision_config.get("time_filter", {})

        # Track cooldown state
        self.cooldown_tracker: Dict[str, Dict[str, datetime]] = {}

    def should_trade(
        self,
        symbol: str,
        probabilities: Dict[int, float],
        atr: float,
        current_time: datetime,
        last_entry_time: Optional[datetime] = None,
        last_exit_time: Optional[datetime] = None,
    ) -> Tuple[bool, int, str]:
        """Determine if trade should be taken.

        Args:
            symbol: Symbol to evaluate
            probabilities: Dict of class probabilities {-1: prob, 1: prob}
            atr: Current ATR value
            current_time: Current timestamp
            last_entry_time: Last entry time for cooldown
            last_exit_time: Last exit time for cooldown

        Returns:
            Tuple of (should_trade, direction, reason)
        """
        # Check probability gate
        max_prob = max(probabilities.values()) if probabilities else 0.0
        if max_prob < self.probability_threshold:
            return (
                False,
                0,
                f"Probability gate: {max_prob:.3f} < {self.probability_threshold}",
            )

        # Determine direction
        direction = max(probabilities, key=probabilities.get)
        if direction == 0:  # Neutral class
            return False, 0, "Neutral prediction"

        # Check expected move threshold
        expected_move = self._calculate_expected_move(probabilities, atr)
        min_expected_move = self.expected_move_multiplier * atr
        if expected_move < min_expected_move:
            return (
                False,
                direction,
                f"Expected move too small: {expected_move:.4f} < {min_expected_move:.4f}",
            )

        # Check cooldown
        if self._is_in_cooldown(symbol, current_time, last_entry_time, last_exit_time):
            return False, direction, "In cooldown period"

        # Check time-of-day filter
        if self._is_time_restricted(current_time):
            return False, direction, "Time-of-day restriction"

        # All checks passed
        return True, direction, "All conditions met"

    def update_cooldown(self, symbol: str, timestamp: datetime, action: str = "entry"):
        """Update cooldown state for a symbol.

        Args:
            symbol: Symbol to update
            timestamp: Timestamp of action
            action: Type of action ("entry" or "exit")
        """
        if symbol not in self.cooldown_tracker:
            self.cooldown_tracker[symbol] = {}

        self.cooldown_tracker[symbol][action] = timestamp

    def _calculate_expected_move(
        self, probabilities: Dict[int, float], atr: float
    ) -> float:
        """Calculate expected absolute move based on probabilities and ATR."""
        # Expected move = |P(+1) - P(-1)| * atr_multiplier * atr
        pos_prob = probabilities.get(1, 0.0)
        neg_prob = probabilities.get(-1, 0.0)
        prob_diff = abs(pos_prob - neg_prob)

        return prob_diff * atr

    def _is_in_cooldown(
        self,
        symbol: str,
        current_time: datetime,
        last_entry_time: Optional[datetime],
        last_exit_time: Optional[datetime],
    ) -> bool:
        """Check if symbol is in cooldown period."""
        base_minutes = self.cooldown_config.get("base_minutes", 15)
        atr_multiplier = self.cooldown_config.get("atr_multiplier", 0.5)
        max_minutes = self.cooldown_config.get("max_minutes", 60)

        # Get the most recent action time
        last_action_time = None
        if last_entry_time and last_exit_time:
            last_action_time = max(last_entry_time, last_exit_time)
        elif last_entry_time:
            last_action_time = last_entry_time
        elif last_exit_time:
            last_action_time = last_exit_time

        if last_action_time is None:
            return False

        # Calculate cooldown period (simplified - would need ATR value in practice)
        cooldown_minutes = min(base_minutes, max_minutes)

        # Check if still in cooldown
        time_diff = (current_time - last_action_time).total_seconds() / 60
        return time_diff < cooldown_minutes

    def _is_time_restricted(self, current_time: datetime) -> bool:
        """Check if current time is restricted."""
        # First minutes after open restriction
        first_minutes = self.time_filter_config.get("first_minutes_after_open", 3)
        market_open = time(9, 30)  # NYSE open time

        current_time_only = current_time.time()

        # Check if it's in the first minutes after open
        if (
            current_time_only.hour == market_open.hour
            and current_time_only.minute < first_minutes
        ):
            return True

        # Check EOD restriction
        force_flat_time_str = self.config.get("force_flat_before_close", "15:59:59")
        force_flat_time = datetime.strptime(force_flat_time_str, "%H:%M:%S").time()

        if current_time_only >= force_flat_time:
            return True

        return False

    def get_cooldown_status(
        self, symbol: str, current_time: datetime
    ) -> Dict[str, Any]:
        """Get current cooldown status for a symbol.

        Args:
            symbol: Symbol to check
            current_time: Current timestamp

        Returns:
            Dictionary with cooldown status
        """
        if symbol not in self.cooldown_tracker:
            return {"in_cooldown": False}

        status = {"in_cooldown": False, "actions": {}}

        for action, timestamp in self.cooldown_tracker[symbol].items():
            time_diff = (current_time - timestamp).total_seconds() / 60
            base_minutes = self.cooldown_config.get("base_minutes", 15)

            status["actions"][action] = {
                "last_action": timestamp.isoformat(),
                "minutes_elapsed": time_diff,
                "cooldown_remaining": max(0, base_minutes - time_diff),
            }

            if time_diff < base_minutes:
                status["in_cooldown"] = True

        return status

    def reset_cooldowns(self):
        """Reset all cooldown states."""
        self.cooldown_tracker.clear()
