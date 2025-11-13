"""Rollback helper stubs for intraday ML deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RollbackPlan:
    """Simple rollback plan."""

    model_id: str
    target_version: str
    reason: str


class RollbackManager:
    """Provide a minimal rollback implementation."""

    def build_plan(self, model_id: str, target_version: str, reason: str) -> RollbackPlan:
        return RollbackPlan(model_id=model_id, target_version=target_version, reason=reason)

    def execute(self, plan: RollbackPlan) -> dict[str, Any]:
        return {
            "model_id": plan.model_id,
            "version": plan.target_version,
            "rolled_back": True,
        }
