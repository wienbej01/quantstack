"""Deployment pipeline stubs for intraday ML models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class DeploymentResult:
    """Outcome of a deployment run."""

    model_id: str
    version: str
    succeeded: bool
    message: str = ""


class DeploymentPipeline:
    """Minimal deployment pipeline placeholder used by tests."""

    def __init__(self, notifier: Callable[[str], None] | None = None):
        self._notifier = notifier

    def deploy(
        self, model_id: str, version: str, metadata: dict[str, Any] | None = None
    ) -> DeploymentResult:
        """Pretend to deploy a model and return a structured result."""
        message = "Deployment completed"
        if self._notifier:
            self._notifier(f"Deploying {model_id}:{version}")
        return DeploymentResult(
            model_id=model_id, version=version, succeeded=True, message=message
        )
