#!/usr/bin/env python3
"""
Decision Policy for filtering ML model signals.
"""

class DecisionPolicy:
    """Filters raw model signals based on confidence and trading frequency."""

    def __init__(self, config: dict):
        self.probability_threshold = config.get("probability_threshold", 0.65)
        self.cooldown_minutes = config.get("cooldown_minutes", 15)
        self.last_trade_time = {}
        self._timestamp_unit: int | None = None
        self._cooldown_duration: int | None = None

    @staticmethod
    def _infer_timestamp_unit(timestamp: int) -> int:
        """Infer timestamp unit (seconds multiplier) from raw value magnitude."""
        magnitude = abs(int(timestamp))
        if magnitude >= 10**17:
            return 1_000_000_000  # nanoseconds
        if magnitude >= 10**14:
            return 1_000_000  # microseconds
        if magnitude >= 10**11:
            return 1_000  # milliseconds
        return 1  # seconds

    def should_trade(self, symbol: str, probability: float, timestamp: int) -> bool:
        """Determines if a trade should be executed."""
        # 1. Check probability threshold
        if probability < self.probability_threshold:
            return False

        if self._timestamp_unit is None:
            self._timestamp_unit = self._infer_timestamp_unit(timestamp)
            self._cooldown_duration = (
                self.cooldown_minutes * 60 * self._timestamp_unit
            )

        cooldown_duration = self._cooldown_duration or 0
        # 2. Check cooldown period
        last_trade = self.last_trade_time.get(symbol)
        if last_trade is None:
            return True

        return timestamp - last_trade >= cooldown_duration

    def record_trade(self, symbol: str, timestamp: int):
        """Records the time of a trade to enforce cooldown."""
        self.last_trade_time[symbol] = timestamp
