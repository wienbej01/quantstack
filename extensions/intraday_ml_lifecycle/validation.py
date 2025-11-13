"""Lifecycle validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class ValidationResult:
    """Lifecycle validation result."""

    is_valid: bool
    issues: list[str]


class ModelValidator:
    """Validate that a model is ready for promotion."""

    def validate_metrics(
        self, metrics: dict[str, Any], thresholds: dict[str, float]
    ) -> ValidationResult:
        """Ensure metrics meet provided thresholds."""
        issues: list[str] = []
        for key, threshold in thresholds.items():
            value = metrics.get(key)
            if value is None or value < threshold:
                issues.append(f"{key} below threshold ({value} < {threshold})")
        return ValidationResult(is_valid=not issues, issues=issues)

    def validate_features(self, features: Iterable[str]) -> ValidationResult:
        """Ensure feature list is non-empty and unique."""
        feature_list = list(features)
        if not feature_list:
            return ValidationResult(is_valid=False, issues=["No features provided"])
        if len(set(feature_list)) != len(feature_list):
            return ValidationResult(is_valid=False, issues=["Duplicate features present"])
        return ValidationResult(is_valid=True, issues=[])
