"""Lightweight heartbeat logger for long-running CLI tasks."""

from __future__ import annotations

import logging
import threading
from typing import Final


class HeartbeatLogger:
    """Emit periodic log messages so operators know a command is still alive."""

    def __init__(self, label: str, interval_seconds: float = 60.0) -> None:
        self.label: Final[str] = label
        self.interval: Final[float] = max(5.0, float(interval_seconds))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{label}", daemon=True)

    def start(self) -> None:
        logging.getLogger(__name__).info("[heartbeat] started (%s)", self.label)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval)
        logging.getLogger(__name__).info("[heartbeat] stopped (%s)", self.label)

    def _run(self) -> None:
        logger = logging.getLogger(__name__)
        while not self._stop.wait(self.interval):
            logger.info("[heartbeat] %s still running...", self.label)

    def __enter__(self) -> HeartbeatLogger:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001 - standard context signature
        self.stop()


__all__ = ["HeartbeatLogger"]
