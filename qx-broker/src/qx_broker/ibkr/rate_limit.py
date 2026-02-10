"""Lightweight rate limit utilities for IBKR calls."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class CancelRateLimiter:
    """Per-order cancel throttling to avoid repeated IBKR calls."""

    min_interval_sec: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _last_call: dict[int, float] = field(default_factory=dict, init=False)

    def allow(self, order_id: int) -> bool:
        """Return True if a cancel should be issued for order_id."""
        if self.min_interval_sec <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            last = self._last_call.get(order_id)
            if last is not None and (now - last) < self.min_interval_sec:
                return False
            self._last_call[order_id] = now
            return True
