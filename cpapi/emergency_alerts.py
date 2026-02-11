"""Emergency alerts for trading system failures.

Sends NTFY notifications when critical failures occur (margin breach,
exit failures, CPU spikes). Rate-limited to avoid spam.
"""

import logging
import time
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

NTFY_EMERGENCY = "https://ntfy.sh/jacobw-trading-status"
RATE_LIMIT_SEC = 300  # 5 minutes between alerts per key


class EmergencyAlerts:
    """Rate-limited emergency alert sender."""

    def __init__(
        self, ntfy_url: str = NTFY_EMERGENCY, rate_limit_sec: float = RATE_LIMIT_SEC
    ):
        self._url = ntfy_url
        self._rate_limit = rate_limit_sec
        self._last_sent: dict[str, float] = {}

    def _should_send(self, key: str) -> bool:
        now = time.time()
        last = self._last_sent.get(key, 0)
        if now - last < self._rate_limit:
            return False
        self._last_sent[key] = now
        return True

    def _send(
        self,
        title: str,
        message: str,
        priority: str = "5",
        tags: str = "rotating_light",
    ) -> bool:
        try:
            resp = requests.post(
                self._url,
                data=message.encode("utf-8"),
                headers={"Title": title, "Priority": priority, "Tags": tags},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("Failed to send emergency alert: %s", e)
            return False

    def exit_failed(self, symbol: str, attempts: int, rejection_reason: str) -> bool:
        """Alert when exit orders are permanently failing."""
        key = f"exit_failed_{symbol}"
        if not self._should_send(key):
            return False

        now_str = datetime.now().strftime("%H:%M:%S")
        title = f"🚨 EXIT FAILED: {symbol}"
        message = (
            f"⏰ {now_str}\n"
            f"❌ {attempts} exit attempts exhausted\n"
            f"📋 Reason: {rejection_reason}\n"
            f"⚠️ Position is STUCK — manual intervention needed"
        )
        return self._send(title, message)

    def margin_breach(self, symbol: str, available: float, required: float) -> bool:
        """Alert when margin is insufficient for entry."""
        key = f"margin_{symbol}"
        if not self._should_send(key):
            return False

        title = f"🚨 MARGIN BREACH: {symbol}"
        message = (
            f"Available: ${available:,.2f}\n"
            f"Required: ${required:,.2f}\n"
            f"Shortfall: ${required - available:,.2f}\n"
            f"⚠️ Entry blocked"
        )
        return self._send(title, message)

    def cpu_spike(self, cpu_pct: float, duration_sec: float, process: str = "") -> bool:
        """Alert on sustained CPU spike."""
        key = "cpu_spike"
        if not self._should_send(key):
            return False

        title = "🔥 CPU SPIKE"
        message = (
            f"CPU: {cpu_pct:.0f}%\n"
            f"Duration: {duration_sec:.0f}s\n"
            f"Process: {process or 'unknown'}"
        )
        return self._send(title, message)
