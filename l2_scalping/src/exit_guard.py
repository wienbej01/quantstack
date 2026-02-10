"""Exit retry circuit breaker for L2 scalping.

Prevents the 100Hz cancel/resubmit death loop that caused the Feb 9 CPU spike.
Tracks per-symbol exit attempts and enforces backoff + hard stop.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_EXIT_ATTEMPTS = 3
BASE_BACKOFF_SEC = 5.0
MAX_BACKOFF_SEC = 60.0


@dataclass
class ExitAttempt:
    """Tracks exit attempts for a single symbol."""

    symbol: str
    attempts: int = 0
    last_attempt_time: float = 0.0
    failed: bool = False
    last_rejection_reason: str = ""


class ExitGuard:
    """Circuit breaker for exit order retries.

    After MAX_EXIT_ATTEMPTS consecutive failures, marks the position as
    EXIT_FAILED and stops retrying. Uses exponential backoff between attempts.
    """

    def __init__(
        self,
        max_attempts: int = MAX_EXIT_ATTEMPTS,
        base_backoff: float = BASE_BACKOFF_SEC,
        max_backoff: float = MAX_BACKOFF_SEC,
        alert_fn=None,
    ):
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.alert_fn = alert_fn
        self._state: dict[str, ExitAttempt] = {}

    def can_attempt_exit(self, symbol: str) -> tuple[bool, str]:
        """Check if an exit attempt is allowed for this symbol.

        Returns (allowed, reason).
        """
        state = self._state.get(symbol)
        if state is None:
            return True, "first attempt"

        if state.failed:
            return False, f"EXIT_FAILED after {state.attempts} attempts: {state.last_rejection_reason}"

        # Check backoff
        now = time.time()
        backoff = min(self.base_backoff * (2 ** (state.attempts - 1)), self.max_backoff)
        elapsed = now - state.last_attempt_time
        if elapsed < backoff:
            remaining = backoff - elapsed
            return False, f"backoff: {remaining:.1f}s remaining (attempt {state.attempts}/{self.max_attempts})"

        return True, f"attempt {state.attempts + 1}/{self.max_attempts}"

    def record_attempt(self, symbol: str, success: bool, rejection_reason: str = "") -> None:
        """Record an exit attempt result.

        Args:
            symbol: The symbol being exited.
            success: True if order was placed (not necessarily filled).
            rejection_reason: Why the order was rejected (if not success).
        """
        if symbol not in self._state:
            self._state[symbol] = ExitAttempt(symbol=symbol)

        state = self._state[symbol]
        state.last_attempt_time = time.time()

        if success:
            # Order placed — reset state (fill tracking is separate)
            state.attempts = 0
            state.failed = False
            state.last_rejection_reason = ""
            return

        state.attempts += 1
        state.last_rejection_reason = rejection_reason

        if state.attempts >= self.max_attempts:
            state.failed = True
            logger.critical(
                "EXIT_FAILED: %s — %d attempts exhausted. Last rejection: %s",
                symbol,
                state.attempts,
                rejection_reason,
            )
            if self.alert_fn:
                try:
                    self.alert_fn(symbol, state.attempts, rejection_reason)
                except Exception as e:
                    logger.error("Alert callback failed: %s", e)
        else:
            backoff = min(self.base_backoff * (2 ** (state.attempts - 1)), self.max_backoff)
            logger.warning(
                "Exit attempt %d/%d failed for %s: %s (next retry in %.0fs)",
                state.attempts,
                self.max_attempts,
                symbol,
                rejection_reason,
                backoff,
            )

    def reset(self, symbol: str) -> None:
        """Reset state for a symbol (e.g., after successful fill)."""
        self._state.pop(symbol, None)

    def get_failed_symbols(self) -> list[str]:
        """Get list of symbols in EXIT_FAILED state."""
        return [s for s, state in self._state.items() if state.failed]

    def get_state(self, symbol: str) -> ExitAttempt | None:
        """Get current state for a symbol."""
        return self._state.get(symbol)

    def reset_all(self) -> None:
        """Reset all state."""
        self._state.clear()
