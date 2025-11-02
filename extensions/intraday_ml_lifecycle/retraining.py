"""Automated retraining helper stubs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


@dataclass
class RetrainingResult:
    """Result of a retraining cycle."""

    model_id: str
    version: str
    trained_at: datetime
    metadata: dict[str, Any]


class AutoRetrainer:
    """Simple retraining orchestrator used in tests."""

    def __init__(
        self, trainer: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    ):
        self._trainer = trainer

    def run(self, config: dict[str, Any]) -> RetrainingResult:
        """Execute the provided trainer callback."""
        trainer = self._trainer or (lambda cfg: {"status": "success"})
        metadata = trainer(config)
        return RetrainingResult(
            model_id=config.get("model_id", "unknown"),
            version=config.get("next_version", "0.0.1"),
            trained_at=datetime.utcnow(),
            metadata=metadata,
        )
