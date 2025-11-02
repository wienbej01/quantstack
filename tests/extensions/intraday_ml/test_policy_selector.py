"""Tests for policy selector."""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from extensions.intraday_ml_policies.base import BaseMLPolicy, PolicySignal
from extensions.intraday_ml_policies.performance_tracker import (
    PerformanceMetrics,
    PolicyPerformanceTracker,
)
from extensions.intraday_ml_policies.policy_selector import (
    PolicySelector,
    SelectionCriteria,
    SelectionMethod,
    SelectionScore,
)


class MockPolicy(BaseMLPolicy):
    """Mock policy for testing."""

    def __init__(self, policy_id: str, performance_score: float = 0.5):
        super().__init__(policy_id, None, None, {})
        self._performance_score = performance_score
        self.execution_count = 0

    def generate_signal(self, features, current_position, market_data):
        return PolicySignal.NEUTRAL

    def calculate_position_size(self, signal, confidence, volatility, account_value):
        return 0.1

    def decide(self, bar, portfolio):
        self.execution_count += 1
        return Mock()  # Mock order

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Return mock performance metrics."""
        return PerformanceMetrics(
            total_executions=100,
            successful_executions=int(100 * self._performance_score),
            failed_executions=int(100 * (1 - self._performance_score)),
            avg_execution_time_ms=50.0,
            success_rate=self._performance_score,
            avg_return=0.001 * self._performance_score,
            sharpe_ratio=0.5 * self._performance_score,
            max_drawdown=0.02,
            volatility=0.01,
            total_pnl=1000.0 * self._performance_score,
            last_updated=datetime.now(),
        )


class TestPolicySelector:
    """Test policy selector functionality."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock policies with different performance levels
        self.policies = {
            "policy1": MockPolicy("policy1", 0.8),
            "policy2": MockPolicy("policy2", 0.6),
            "policy3": MockPolicy("policy3", 0.4),
        }

        # Create performance tracker
        self.performance_tracker = PolicyPerformanceTracker()

        # Create selector
        self.selector = PolicySelector(self.performance_tracker)

        # Add some performance data
        for policy_id, policy in self.policies.items():
            metrics = policy.get_performance_metrics()
            self.performance_tracker.policy_metrics[policy_id] = metrics

    def test_selector_initialization(self):
        """Test selector initialization."""
        assert self.selector.performance_tracker is not None
        assert self.selector.selection_weights is not None
        assert "success_rate" in self.selector.selection_weights
        assert "sharpe_ratio" in self.selector.selection_weights

    def test_select_best_policy(self):
        """Test basic best policy selection."""
        criteria = SelectionCriteria(
            method=SelectionMethod.BEST_PERFORMANCE,
            min_executions=10,
            weight_success_rate=0.4,
            weight_sharpe_ratio=0.3,
            weight_return=0.3,
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        # Should select policy1 (highest performance score)
        assert best_policy == "policy1"

    def test_select_policy_by_regime(self):
        """Test regime-based policy selection."""
        from extensions.intraday_ml_policies.adaptive_policy import MarketRegime

        # Add regime-specific performance
        self.performance_tracker.regime_performance = {
            "policy1": {MarketRegime.TRENDING_UP: SelectionScore(0.9, 0.7, 0.8)},
            "policy2": {MarketRegime.TRENDING_UP: SelectionScore(0.7, 0.5, 0.6)},
            "policy3": {MarketRegime.TRENDING_UP: SelectionScore(0.5, 0.3, 0.4)},
        }

        criteria = SelectionCriteria(
            method=SelectionMethod.REGIME_BASED, current_regime=MarketRegime.TRENDING_UP
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        # Should select policy1 (best in trending regime)
        assert best_policy == "policy1"

    def test_select_policy_ensemble(self):
        """Test ensemble policy selection."""
        criteria = SelectionCriteria(
            method=SelectionMethod.ENSEMBLE,
            top_k=2,
            ensemble_weights={"success_rate": 0.5, "sharpe_ratio": 0.5},
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        # Should return an ensemble identifier
        assert best_policy is not None
        assert "ensemble" in best_policy

    def test_select_policy_with_insufficient_data(self):
        """Test selection when policies have insufficient data."""
        # Create policy with low execution count
        low_data_policy = MockPolicy("low_data", 0.9)
        low_data_metrics = low_data_policy.get_performance_metrics()
        low_data_metrics.total_executions = 5  # Below threshold

        self.policies["low_data"] = low_data_policy
        self.performance_tracker.policy_metrics["low_data"] = low_data_metrics

        criteria = SelectionCriteria(
            method=SelectionMethod.BEST_PERFORMANCE, min_executions=10
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        # Should not select low_data policy
        assert best_policy != "low_data"
        # Should select policy1 (best among qualified policies)
        assert best_policy == "policy1"

    def test_select_policy_no_qualified_policies(self):
        """Test selection when no policies meet criteria."""
        # Set all policies to have insufficient data
        for policy_id in self.policies:
            metrics = self.performance_tracker.policy_metrics[policy_id]
            metrics.total_executions = 5

        criteria = SelectionCriteria(
            method=SelectionMethod.BEST_PERFORMANCE, min_executions=10
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        # Should return None when no policies qualify
        assert best_policy is None

    def test_calculate_selection_score(self):
        """Test selection score calculation."""
        metrics = self.policies["policy1"].get_performance_metrics()

        criteria = SelectionCriteria(
            weight_success_rate=0.4, weight_sharpe_ratio=0.3, weight_return=0.3
        )

        score = self.selector._calculate_selection_score(metrics, criteria)

        # Score should be between 0 and 1
        assert 0 <= score <= 1

        # Higher performing policy should have higher score
        low_metrics = self.policies["policy3"].get_performance_metrics()
        low_score = self.selector._calculate_selection_score(low_metrics, criteria)

        assert score > low_score

    def test_get_policy_rankings(self):
        """Test policy ranking functionality."""
        criteria = SelectionCriteria(
            method=SelectionMethod.BEST_PERFORMANCE, min_executions=10
        )

        rankings = self.selector.get_policy_rankings(self.policies, criteria)

        # Should return rankings for all policies
        assert len(rankings) == 3

        # Should be sorted by score (descending)
        assert rankings[0][0] == "policy1"  # Highest score
        assert rankings[1][0] == "policy2"
        assert rankings[2][0] == "policy3"

        # Scores should be in descending order
        assert rankings[0][1] >= rankings[1][1] >= rankings[2][1]

    def test_update_selection_weights(self):
        """Test updating selection weights."""
        new_weights = {"success_rate": 0.6, "sharpe_ratio": 0.2, "return": 0.2}

        self.selector.update_selection_weights(new_weights)

        assert self.selector.selection_weights["success_rate"] == 0.6
        assert self.selector.selection_weights["sharpe_ratio"] == 0.2
        assert self.selector.selection_weights["return"] == 0.2

    def test_get_selection_weights(self):
        """Test getting selection weights."""
        weights = self.selector.get_selection_weights()

        assert "success_rate" in weights
        assert "sharpe_ratio" in weights
        assert "return" in weights

        # Weights should sum to 1.0
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_filter_policies_by_criteria(self):
        """Test filtering policies by criteria."""
        # Add a policy with custom tags
        custom_policy = MockPolicy("custom_policy", 0.7)
        custom_policy.tags = {"momentum", "short_term"}
        self.policies["custom_policy"] = custom_policy

        criteria = SelectionCriteria(
            method=SelectionMethod.BEST_PERFORMANCE, required_tags={"momentum"}
        )

        filtered_policies = self.selector._filter_policies_by_criteria(
            self.policies, criteria
        )

        # Should only include policies with required tags
        assert "custom_policy" in filtered_policies
        assert "policy1" not in filtered_policies  # No required tags

    def test_regime_specific_selection(self):
        """Test regime-specific selection logic."""
        from extensions.intraday_ml_policies.adaptive_policy import MarketRegime

        # Set up regime performance data
        self.performance_tracker.regime_performance = {
            "policy1": {
                MarketRegime.TRENDING_UP: SelectionScore(0.9, 0.7, 0.8),
                MarketRegime.SIDEWAYS: SelectionScore(0.5, 0.3, 0.4),
            },
            "policy2": {
                MarketRegime.TRENDING_UP: SelectionScore(0.6, 0.4, 0.5),
                MarketRegime.SIDEWAYS: SelectionScore(0.8, 0.6, 0.7),
            },
        }

        # Test trending regime
        criteria = SelectionCriteria(
            method=SelectionMethod.REGIME_BASED, current_regime=MarketRegime.TRENDING_UP
        )

        best_policy = self.selector.select_best_policy(
            {"policy1": self.policies["policy1"], "policy2": self.policies["policy2"]},
            criteria,
        )

        assert best_policy == "policy1"  # Better in trending

        # Test sideways regime
        criteria.current_regime = MarketRegime.SIDEWAYS
        best_policy = self.selector.select_best_policy(
            {"policy1": self.policies["policy1"], "policy2": self.policies["policy2"]},
            criteria,
        )

        assert best_policy == "policy2"  # Better in sideways

    def test_ensemble_selection_weights(self):
        """Test ensemble selection with custom weights."""
        criteria = SelectionCriteria(
            method=SelectionMethod.ENSEMBLE,
            top_k=2,
            ensemble_weights={"success_rate": 0.8, "sharpe_ratio": 0.2},
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        assert best_policy is not None
        assert "ensemble" in best_policy

    def test_selection_with_missing_regime_data(self):
        """Test selection when regime data is missing for some policies."""
        from extensions.intraday_ml_policies.adaptive_policy import MarketRegime

        # Add regime data for only some policies
        self.performance_tracker.regime_performance = {
            "policy1": {MarketRegime.TRENDING_UP: SelectionScore(0.9, 0.7, 0.8)},
            # policy2 and policy3 missing regime data
        }

        criteria = SelectionCriteria(
            method=SelectionMethod.REGIME_BASED,
            current_regime=MarketRegime.TRENDING_UP,
            fallback_to_overall=True,
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        # Should select policy1 (has regime data) or fallback to overall best
        assert best_policy in ["policy1", "policy1"]

    def test_performance_decay_factor(self):
        """Test selection with performance decay factor."""
        # Add old performance data
        old_metrics = self.policies["policy2"].get_performance_metrics()
        old_metrics.last_updated = datetime.now() - timedelta(days=10)
        self.performance_tracker.policy_metrics["policy2"] = old_metrics

        criteria = SelectionCriteria(
            method=SelectionMethod.BEST_PERFORMANCE, performance_decay_half_life_days=5
        )

        best_policy = self.selector.select_best_policy(self.policies, criteria)

        # Should prefer newer high-performance data
        assert best_policy == "policy1"

    def test_criteria_validation(self):
        """Test criteria validation."""
        # Test invalid weights sum
        with pytest.raises(ValueError):
            SelectionCriteria(
                weight_success_rate=0.8,
                weight_sharpe_ratio=0.8,  # Sum > 1.0
                weight_return=0.1,
            )

        # Test negative weights
        with pytest.raises(ValueError):
            SelectionCriteria(
                weight_success_rate=-0.1, weight_sharpe_ratio=0.6, weight_return=0.5
            )

    def test_edge_cases(self):
        """Test edge cases in selection."""
        # Empty policies dict
        criteria = SelectionCriteria(method=SelectionMethod.BEST_PERFORMANCE)
        result = self.selector.select_best_policy({}, criteria)
        assert result is None

        # Single policy
        single_policy = {"policy1": self.policies["policy1"]}
        result = self.selector.select_best_policy(single_policy, criteria)
        assert result == "policy1"


if __name__ == "__main__":
    pytest.main([__file__])
