"""Model monitoring validators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


@dataclass
class ValidationIssue:
    """Simple structure describing a validation issue."""

    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


class ModelValidator:
    """Validate model metadata against runtime configuration."""

    def __init__(self) -> None:
        self._drift_detector = DriftDetector()

    def validate_model_consistency(
        self,
        metadata: Any,
        current_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Confirm features and hyperparameters match expectations."""
        issues: list[ValidationIssue] = []

        expected_features = set(getattr(metadata, "features", []))
        configured_features = set(current_config.get("features", []))
        if expected_features != configured_features:
            missing = expected_features - configured_features
            unexpected = configured_features - expected_features
            if missing:
                issues.append(
                    ValidationIssue(
                        field="features", message=f"Missing features: {sorted(missing)}"
                    )
                )
            if unexpected:
                issues.append(
                    ValidationIssue(
                        field="features",
                        message=f"Unexpected features: {sorted(unexpected)}",
                    )
                )

        expected_hp = getattr(metadata, "hyperparameters", {}) or {}
        current_hp = current_config.get("hyperparameters", {}) or {}
        if expected_hp != current_hp:
            issues.append(
                ValidationIssue(
                    field="hyperparameters",
                    message="Hyperparameters do not match metadata.",
                )
            )

        return {
            "is_valid": not issues,
            "issues": [issue.to_dict() for issue in issues],
        }

    def validate_feature_importance(self, feature_importance: dict[str, float]) -> dict[str, Any]:
        """Ensure feature importance sums to ~1 and identify top features."""
        total_importance = float(sum(feature_importance.values()))
        if total_importance == 0.0:
            normalized = {feature: 0.0 for feature in feature_importance}
        else:
            normalized = {
                feature: value / total_importance for feature, value in feature_importance.items()
            }

        top_features = sorted(normalized.items(), key=lambda item: item[1], reverse=True)
        return {
            "total_importance": total_importance,
            "importance_distribution": normalized,
            "top_features": [feature for feature, _ in top_features],
        }

    def validate_prediction_distribution(self, predictions: Iterable[float]) -> dict[str, Any]:
        """Return distribution summary of model predictions."""
        preds = np.asarray(list(predictions), dtype=float)
        if preds.size == 0:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "outliers": []}

        mean = float(np.mean(preds))
        std = float(np.std(preds))
        if std == 0:
            outliers: list[float] = []
        else:
            z_scores = (preds - mean) / std
            outliers = preds[np.abs(z_scores) > 3]

        return {
            "mean": mean,
            "std": std,
            "min": float(np.min(preds)),
            "max": float(np.max(preds)),
            "outliers": outliers.tolist(),
        }

    # Drift detector convenience wrappers ---------------------------------

    def detect_feature_drift(
        self,
        reference_data: pd.DataFrame,
        current_data: pd.DataFrame,
        features: list[str],
        threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Delegate to DriftDetector for feature drift checks."""
        return self._drift_detector.detect_feature_drift(
            reference_data=reference_data,
            current_data=current_data,
            features=features,
            threshold=threshold,
        )

    def detect_target_drift(
        self,
        reference_targets: Iterable[float],
        current_targets: Iterable[float],
        threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Delegate to DriftDetector for target drift checks."""
        return self._drift_detector.detect_target_drift(
            reference_targets=reference_targets,
            current_targets=current_targets,
            threshold=threshold,
        )

    def calculate_population_stability_index(
        self,
        reference_data: Iterable[float],
        current_data: Iterable[float],
        bins: int = 10,
    ) -> float:
        """Delegate PSI computation."""
        return self._drift_detector.calculate_population_stability_index(
            reference_data=reference_data,
            current_data=current_data,
            bins=bins,
        )

    def detect_concept_drift(
        self,
        predictions: Iterable[float],
        actuals: Iterable[float],
        window: int = 50,
        threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Delegate concept drift detection."""
        return self._drift_detector.detect_concept_drift(
            predictions=predictions,
            actuals=actuals,
            window=window,
            threshold=threshold,
        )


class DriftDetector:
    """Detect data and concept drift using simple statistical heuristics."""

    def detect_feature_drift(
        self,
        reference_data: pd.DataFrame,
        current_data: pd.DataFrame,
        features: list[str],
        threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Check for feature drift via relative mean shift."""
        drift_summary: dict[str, dict[str, Any]] = {}
        overall_drift = False

        for feature in features:
            ref = reference_data.get(feature, pd.Series(dtype=float)).dropna()
            cur = current_data.get(feature, pd.Series(dtype=float)).dropna()
            if ref.empty or cur.empty:
                drift_summary[feature] = {
                    "drift_detected": False,
                    "mean_reference": None,
                    "mean_current": None,
                    "relative_shift": None,
                }
                continue

            mean_ref = float(ref.mean())
            mean_cur = float(cur.mean())
            pooled_std = float(np.sqrt(np.var(np.concatenate([ref.values, cur.values]))))
            pooled_std = max(pooled_std, 1e-9)
            relative_shift = abs(mean_cur - mean_ref) / pooled_std
            drift_detected = relative_shift > (threshold * 10)

            overall_drift |= drift_detected
            drift_summary[feature] = {
                "drift_detected": drift_detected,
                "mean_reference": mean_ref,
                "mean_current": mean_cur,
                "relative_shift": relative_shift,
            }

        return {"drift_detected": overall_drift, "feature_drift": drift_summary}

    def detect_target_drift(
        self,
        reference_targets: Iterable[float],
        current_targets: Iterable[float],
        threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Detect drift in target distribution using mean shift."""
        ref = np.asarray(list(reference_targets), dtype=float)
        cur = np.asarray(list(current_targets), dtype=float)
        if ref.size == 0 or cur.size == 0:
            return {
                "drift_detected": False,
                "p_value": 1.0,
                "effect_size": 0.0,
                "test_statistic": 0.0,
            }

        mean_diff = float(abs(ref.mean() - cur.mean()))
        pooled_std = float(np.sqrt((ref.var() + cur.var()) / 2))
        pooled_std = max(pooled_std, 1e-9)
        effect_size = mean_diff / pooled_std
        drift_detected = effect_size > threshold

        return {
            "drift_detected": drift_detected,
            "p_value": 0.0 if drift_detected else 1.0,
            "effect_size": effect_size,
            "test_statistic": mean_diff,
        }

    def calculate_population_stability_index(
        self,
        reference_data: Iterable[float],
        current_data: Iterable[float],
        bins: int = 10,
    ) -> float:
        """Compute PSI between two distributions."""
        ref = np.asarray(list(reference_data), dtype=float)
        cur = np.asarray(list(current_data), dtype=float)
        if ref.size == 0 or cur.size == 0:
            return 0.0

        quantiles = np.linspace(0, 1, bins + 1)
        ref_bins = np.quantile(ref, quantiles)
        ref_bins[0] -= 1e-9
        ref_bins[-1] += 1e-9
        ref_hist, _ = np.histogram(ref, bins=ref_bins)
        cur_hist, _ = np.histogram(cur, bins=ref_bins)

        ref_ratio = ref_hist / ref_hist.sum() + 1e-9
        cur_ratio = cur_hist / cur_hist.sum() + 1e-9
        psi = np.sum((cur_ratio - ref_ratio) * np.log(cur_ratio / ref_ratio))
        return float(psi)

    def detect_concept_drift(
        self,
        predictions: Iterable[float],
        actuals: Iterable[float],
        window: int = 50,
        threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Detect concept drift by tracking rolling error changes."""
        preds = np.asarray(list(predictions), dtype=float)
        acts = np.asarray(list(actuals), dtype=float)
        if preds.size == 0 or acts.size == 0:
            return {
                "drift_detected": False,
                "drift_points": [],
                "performance_degradation": 0.0,
            }

        errors = np.abs(preds - acts)
        if errors.size < window:
            return {
                "drift_detected": False,
                "drift_points": [],
                "performance_degradation": 0.0,
            }

        rolling = pd.Series(errors).rolling(window=window)
        mean_errors = rolling.mean().dropna().values
        drift_points: list[int] = []
        for idx in range(1, len(mean_errors)):
            delta = mean_errors[idx] - mean_errors[idx - 1]
            if delta > threshold:
                drift_points.append(idx + window - 1)

        drift_detected = bool(drift_points)
        performance_degradation = (
            float(mean_errors[-1] - mean_errors[0]) if len(mean_errors) else 0.0
        )
        return {
            "drift_detected": drift_detected,
            "drift_points": drift_points,
            "performance_degradation": performance_degradation,
        }
