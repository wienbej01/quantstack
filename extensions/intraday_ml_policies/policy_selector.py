"""Policy selector for adaptive policy selection.

This module provides intelligent policy selection based on performance metrics,
market conditions, and other criteria.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

from extensions.intraday_ml_policies.base import BaseMLPolicy
from extensions.intraday_ml_policies.performance_tracker import (
    PolicyPerformanceTracker, PerformanceMetrics
)
from extensions.intraday_ml_policies.adaptive_policy import MarketRegime


class SelectionMethod(Enum):
    """Policy selection methods."""
    BEST_PERFORMANCE = "best_performance"
    REGIME_BASED = "regime_based"
    ENSEMBLE = "ensemble"
    WEIGHTED_SCORE = "weighted_score"
    ADAPTIVE = "adaptive"


@dataclass
class SelectionCriteria:
    """Criteria for policy selection."""
    method: SelectionMethod = SelectionMethod.BEST_PERFORMANCE
    min_executions: int = 10
    min_success_rate: float = 0.5
    max_execution_time_ms: float = 1000.0
    weight_success_rate: float = 0.4
    weight_sharpe_ratio: float = 0.3
    weight_return: float = 0.3
    required_tags: Set[str] = field(default_factory=set)
    excluded_tags: Set[str] = field(default_factory=set)
    current_regime: Optional[MarketRegime] = None
    top_k: int = 3
    ensemble_weights: Dict[str, float] = field(default_factory=dict)
    performance_decay_half_life_days: float = 30.0
    fallback_to_overall: bool = True

    def __post_init__(self):
        """Validate criteria after initialization."""
        total_weight = (
            self.weight_success_rate +
            self.weight_sharpe_ratio +
            self.weight_return
        )
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")

        if any(w < 0 for w in [self.weight_success_rate, self.weight_sharpe_ratio, self.weight_return]):
            raise ValueError("Weights must be non-negative")


@dataclass
class SelectionScore:
    """Score for policy selection."""
    success_rate: float
    sharpe_ratio: float
    return_score: float

    def calculate_total_score(self, weights: Dict[str, float]) -> float:
        """Calculate total weighted score."""
        return (
            weights.get("success_rate", 0.4) * self.success_rate +
            weights.get("sharpe_ratio", 0.3) * self.sharpe_ratio +
            weights.get("return", 0.3) * self.return_score
        )


class PolicySelector:
    """Intelligent policy selector for ML trading policies.

    Provides various selection methods including performance-based, regime-based,
    ensemble, and adaptive selection strategies.
    """

    def __init__(
        self,
        performance_tracker: Optional[PolicyPerformanceTracker] = None,
        selection_weights: Optional[Dict[str, float]] = None
    ):
        """
        Initialize policy selector.

        Args:
            performance_tracker: Optional performance tracker
            selection_weights: Default weights for selection scoring
        """
        self.performance_tracker = performance_tracker or PolicyPerformanceTracker()
        self.selection_weights = selection_weights or {
            "success_rate": 0.4,
            "sharpe_ratio": 0.3,
            "return": 0.3
        }

        self.logger = logging.getLogger(__name__)

    def select_best_policy(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> Optional[str]:
        """
        Select the best policy based on criteria.

        Args:
            policies: Dictionary of policy ID to policy instances
            criteria: Selection criteria

        Returns:
            Selected policy ID or None if no policy meets criteria
        """
        if not policies:
            return None

        # Filter policies by basic criteria
        qualified_policies = self._filter_policies_by_criteria(policies, criteria)

        if not qualified_policies:
            if criteria.fallback_to_overall:
                # Fallback to overall best performance
                qualified_policies = policies
            else:
                return None

        # Select based on method
        if criteria.method == SelectionMethod.BEST_PERFORMANCE:
            return self._select_by_best_performance(qualified_policies, criteria)
        elif criteria.method == SelectionMethod.REGIME_BASED:
            return self._select_by_regime(qualified_policies, criteria)
        elif criteria.method == SelectionMethod.ENSEMBLE:
            return self._select_ensemble(qualified_policies, criteria)
        elif criteria.method == SelectionMethod.WEIGHTED_SCORE:
            return self._select_by_weighted_score(qualified_policies, criteria)
        elif criteria.method == SelectionMethod.ADAPTIVE:
            return self._select_adaptive(qualified_policies, criteria)
        else:
            raise ValueError(f"Unknown selection method: {criteria.method}")

    def get_policy_rankings(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> List[tuple[str, float]]:
        """
        Get ranked list of policies by score.

        Args:
            policies: Dictionary of policy ID to policy instances
            criteria: Selection criteria

        Returns:
            List of (policy_id, score) tuples sorted by score (descending)
        """
        qualified_policies = self._filter_policies_by_criteria(policies, criteria)

        if not qualified_policies:
            return []

        scores = []
        for policy_id, policy in qualified_policies.items():
            metrics = self.performance_tracker.get_policy_metrics(policy_id)
            if metrics:
                score = self._calculate_selection_score(metrics, criteria)
                scores.append((policy_id, score))

        # Sort by score (descending)
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def update_selection_weights(self, weights: Dict[str, float]) -> None:
        """Update default selection weights."""
        total_weight = sum(weights.values())
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")

        self.selection_weights = weights.copy()
        self.logger.info(f"Updated selection weights: {weights}")

    def get_selection_weights(self) -> Dict[str, float]:
        """Get current selection weights."""
        return self.selection_weights.copy()

    def _filter_policies_by_criteria(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> Dict[str, BaseMLPolicy]:
        """Filter policies based on basic criteria."""
        qualified = {}

        for policy_id, policy in policies.items():
            metrics = self.performance_tracker.get_policy_metrics(policy_id)

            if not metrics:
                continue

            # Check minimum executions
            if metrics.total_executions < criteria.min_executions:
                continue

            # Check success rate
            if metrics.success_rate < criteria.min_success_rate:
                continue

            # Check execution time
            if metrics.avg_execution_time_ms > criteria.max_execution_time_ms:
                continue

            # Check required tags
            if criteria.required_tags:
                policy_tags = getattr(policy, 'tags', set())
                if not criteria.required_tags.issubset(policy_tags):
                    continue

            # Check excluded tags
            if criteria.excluded_tags:
                policy_tags = getattr(policy, 'tags', set())
                if criteria.excluded_tags.intersection(policy_tags):
                    continue

            qualified[policy_id] = policy

        return qualified

    def _select_by_best_performance(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> Optional[str]:
        """Select policy with best overall performance."""
        best_policy_id = None
        best_score = -float('inf')

        for policy_id, policy in policies.items():
            metrics = self.performance_tracker.get_policy_metrics(policy_id)
            if not metrics:
                continue

            score = self._calculate_selection_score(metrics, criteria)
            if score > best_score:
                best_score = score
                best_policy_id = policy_id

        return best_policy_id

    def _select_by_regime(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> Optional[str]:
        """Select policy based on regime-specific performance."""
        if not criteria.current_regime:
            # Fallback to overall performance if no regime specified
            return self._select_by_best_performance(policies, criteria)

        best_policy_id = None
        best_score = -float('inf')

        for policy_id, policy in policies.items():
            # Check if we have regime-specific performance
            regime_perf = self.performance_tracker.get_regime_performance(
                policy_id, criteria.current_regime
            )

            if regime_perf:
                # Use regime-specific score
                weights = criteria.ensemble_weights or self.selection_weights
                score = regime_perf.calculate_total_score(weights)
            else:
                # Fallback to overall performance if regime data missing
                if criteria.fallback_to_overall:
                    metrics = self.performance_tracker.get_policy_metrics(policy_id)
                    if metrics:
                        score = self._calculate_selection_score(metrics, criteria)
                    else:
                        continue
                else:
                    continue

            if score > best_score:
                best_score = score
                best_policy_id = policy_id

        return best_policy_id

    def _select_ensemble(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> Optional[str]:
        """Select ensemble of top policies."""
        rankings = self.get_policy_rankings(policies, criteria)

        if not rankings:
            return None

        # Take top k policies
        top_policies = [policy_id for policy_id, _ in rankings[:criteria.top_k]]

        # Return ensemble identifier
        ensemble_id = f"ensemble_{','.join(top_policies)}"
        return ensemble_id

    def _select_by_weighted_score(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> Optional[str]:
        """Select policy using custom weighted scoring."""
        return self._select_by_best_performance(policies, criteria)

    def _select_adaptive(
        self,
        policies: Dict[str, BaseMLPolicy],
        criteria: SelectionCriteria
    ) -> Optional[str]:
        """Adaptively select policy based on multiple factors."""
        # For now, use best performance
        # In a full implementation, this would consider recent performance trends,
        # market volatility, risk appetite, etc.
        return self._select_by_best_performance(policies, criteria)

    def _calculate_selection_score(
        self,
        metrics: PerformanceMetrics,
        criteria: SelectionCriteria
    ) -> float:
        """Calculate selection score for policy metrics."""
        # Normalize metrics to 0-1 range
        success_rate_score = min(1.0, max(0.0, metrics.success_rate))

        # Normalize Sharpe ratio (assuming reasonable range of -2 to 2)
        sharpe_ratio_score = min(1.0, max(0.0, (metrics.sharpe_ratio + 2) / 4))

        # Normalize return (assuming reasonable range of -10% to 10% daily)
        return_score = min(1.0, max(0.0, (metrics.avg_return + 0.1) / 0.2))

        # Apply performance decay if specified
        if criteria.performance_decay_half_life_days > 0 and metrics.last_updated:
            days_since_update = (datetime.now() - metrics.last_updated).days
            decay_factor = 0.5 ** (days_since_update / criteria.performance_decay_half_life_days)

            # Apply decay to all scores
            success_rate_score *= decay_factor
            sharpe_ratio_score *= decay_factor
            return_score *= decay_factor

        # Calculate weighted score
        weights = {
            "success_rate": criteria.weight_success_rate,
            "sharpe_ratio": criteria.weight_sharpe_ratio,
            "return": criteria.weight_return
        }

        total_score = (
            weights["success_rate"] * success_rate_score +
            weights["sharpe_ratio"] * sharpe_ratio_score +
            weights["return"] * return_score
        )

        return total_score