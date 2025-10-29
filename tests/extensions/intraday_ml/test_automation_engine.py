"""Tests for policy automation engine."""

import time
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import MagicMock, Mock, patch

import pytest

from extensions.intraday_ml_policies.automation_engine import (
    AutomationConfig,
    AutomationState,
    ExecutionMode,
    ExecutionResult,
    PolicyAutomationEngine,
)
from extensions.intraday_ml_policies.base import (
    BaseMLPolicy,
    PolicyAction,
    PolicyDecision,
    PolicySignal,
)


class MockPolicy(BaseMLPolicy):
    """Mock policy for testing."""

    def __init__(self, policy_id: str):
        super().__init__(policy_id, None, None, {})
        self.policy_id = policy_id  # Ensure policy_id is set
        self.execution_count = 0
        self.should_fail = False

    def generate_signal(self, features, current_position, market_data):
        return PolicySignal.NEUTRAL

    def calculate_position_size(self, signal, confidence, volatility, account_value):
        return 0.1

    def decide(self, bar, portfolio):
        self.execution_count += 1

        if self.should_fail:
            raise Exception("Mock policy execution failed")

        # Return a mock PolicyDecision
        return PolicyDecision(
            action=PolicyAction.BUY,
            confidence=0.7,
            signal_strength=0.5,
            metadata={"policy_id": self.policy_id},
        )


class TestPolicyAutomationEngine:
    """Test policy automation engine functionality."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock policies
        self.policies = {
            "policy1": MockPolicy("policy1"),
            "policy2": MockPolicy("policy2"),
            "policy3": MockPolicy("policy3"),
        }

        # Create automation config
        self.config = AutomationConfig(
            execution_mode=ExecutionMode.PARALLEL,
            update_interval_seconds=1,  # Short interval for testing
            max_concurrent_policies=3,
        )

        # Create engine
        with patch("extensions.intraday_ml_policies.automation_engine.PolicySelector"):
            with patch(
                "extensions.intraday_ml_policies.automation_engine.PolicyPerformanceTracker"
            ):
                self.engine = PolicyAutomationEngine(
                    policies=self.policies, config=self.config
                )

    def teardown_method(self):
        """Clean up after tests."""
        if self.engine.state != AutomationState.STOPPED:
            self.engine.stop()

    def test_engine_initialization(self):
        """Test engine initialization."""
        assert self.engine.state == AutomationState.STOPPED
        assert len(self.engine.policies) == 3
        assert self.engine.config.execution_mode == ExecutionMode.PARALLEL
        assert self.engine.config.max_concurrent_policies == 3

    def test_engine_start_stop(self):
        """Test engine start and stop functionality."""
        # Start engine
        self.engine.start()

        # Wait a bit for startup
        time.sleep(0.1)
        assert self.engine.state == AutomationState.RUNNING

        # Stop engine
        self.engine.stop()
        assert self.engine.state == AutomationState.STOPPED

    def test_engine_pause_resume(self):
        """Test engine pause and resume functionality."""
        self.engine.start()
        time.sleep(0.1)

        # Pause engine
        self.engine.pause()
        assert self.engine.state == AutomationState.PAUSED

        # Resume engine
        self.engine.resume()
        assert self.engine.state == AutomationState.RUNNING

        self.engine.stop()

    def test_single_policy_execution(self):
        """Test execution of single policy."""
        config = AutomationConfig(
            execution_mode=ExecutionMode.SINGLE,
            update_interval_seconds=1,
            max_concurrent_policies=1,
        )

        with patch("extensions.intraday_ml_policies.automation_engine.PolicySelector"):
            with patch(
                "extensions.intraday_ml_policies.automation_engine.PolicyPerformanceTracker"
            ):
                engine = PolicyAutomationEngine(self.policies, config)

                result = engine._execute_single_policy("policy1")

                assert result.policy_id == "policy1"
                assert result.success is True
                assert result.decision is not None
                assert result.execution_time_ms >= 0

                engine.stop()

    def test_parallel_policy_execution(self):
        """Test parallel execution of multiple policies."""
        results = self.engine._execute_parallel(["policy1", "policy2", "policy3"])

        assert len(results) == 3
        assert all(result.success for result in results)
        assert all(result.policy_id in self.policies for result in results)

    def test_ensemble_policy_execution(self):
        """Test ensemble execution of policies."""
        results = self.engine._execute_ensemble(["policy1", "policy2"])

        assert len(results) == 1
        result = results[0]
        assert result.policy_id == "ensemble"
        assert result.success is True
        assert "ensemble_policies" in result.metadata

    def test_execution_with_failures(self):
        """Test execution handling when policies fail."""
        # Make one policy fail
        self.policies["policy2"].should_fail = True

        results = self.engine._execute_parallel(["policy1", "policy2", "policy3"])

        assert len(results) == 3
        successful_results = [r for r in results if r.success]
        failed_results = [r for r in results if not r.success]

        assert len(successful_results) == 2
        assert len(failed_results) == 1
        assert failed_results[0].policy_id == "policy2"

    def test_policy_selection_single_mode(self):
        """Test policy selection for single execution mode."""
        config = AutomationConfig(
            execution_mode=ExecutionMode.SINGLE, update_interval_seconds=1
        )

        with patch(
            "extensions.intraday_ml_policies.automation_engine.PolicySelector"
        ) as mock_selector:
            mock_selector_instance = Mock()
            mock_selector_instance.select_best_policy.return_value = "policy1"
            mock_selector.return_value = mock_selector_instance

            engine = PolicyAutomationEngine(self.policies, config)
            selected = engine._select_policies_for_execution()

            assert selected == ["policy1"]
            mock_selector_instance.select_best_policy.assert_called_once()

            engine.stop()

    def test_policy_selection_parallel_mode(self):
        """Test policy selection for parallel execution mode."""
        config = AutomationConfig(
            execution_mode=ExecutionMode.PARALLEL, update_interval_seconds=1
        )

        with patch("extensions.intraday_ml_policies.automation_engine.PolicySelector"):
            engine = PolicyAutomationEngine(self.policies, config)
            selected = engine._select_policies_for_execution()

            assert set(selected) == set(self.policies.keys())

            engine.stop()

    def test_execution_result_processing(self):
        """Test processing of execution results."""
        results = [
            ExecutionResult("policy1", Mock(), 100, True),
            ExecutionResult("policy2", Mock(), 150, True),
            ExecutionResult("policy3", None, 50, False, "Test error"),
        ]

        self.engine._process_execution_results(results)

        # Check statistics are updated
        assert "policy1" in self.engine.execution_statistics
        assert "policy2" in self.engine.execution_statistics
        assert "policy3" in self.engine.execution_statistics

        stats1 = self.engine.execution_statistics["policy1"]
        assert stats1["total_executions"] == 1
        assert stats1["successful_executions"] == 1
        assert stats1["failed_executions"] == 0

        stats3 = self.engine.execution_statistics["policy3"]
        assert stats3["total_executions"] == 1
        assert stats3["successful_executions"] == 0
        assert stats3["failed_executions"] == 1

    def test_engine_status_reporting(self):
        """Test engine status reporting."""
        status = self.engine.get_engine_status()

        assert "state" in status
        assert "execution_mode" in status
        assert "total_policies" in status
        assert status["total_policies"] == 3
        assert status["state"] == AutomationState.STOPPED.value

    def test_policy_addition_removal(self):
        """Test adding and removing policies."""
        # Add new policy
        new_policy = MockPolicy("policy4")
        self.engine.add_policy("policy4", new_policy)

        assert "policy4" in self.engine.policies
        assert len(self.engine.policies) == 4

        # Remove policy
        self.engine.remove_policy("policy4")
        assert "policy4" not in self.engine.policies
        assert len(self.engine.policies) == 3

    def test_config_update(self):
        """Test configuration updates."""
        new_config = AutomationConfig(
            execution_mode=ExecutionMode.SINGLE,
            update_interval_seconds=5,
            max_concurrent_policies=1,
        )

        self.engine.update_config(new_config)

        assert self.engine.config.execution_mode == ExecutionMode.SINGLE
        assert self.engine.config.update_interval_seconds == 5
        assert self.engine.config.max_concurrent_policies == 1

    def test_execution_cycle_timeout(self):
        """Test execution cycle with timeout handling."""
        # This test checks that the engine doesn't hang on execution
        start_time = time.time()

        # Execute with very short timeout
        self.engine._execute_policies_cycle()

        execution_time = time.time() - start_time
        assert execution_time < 2.0  # Should complete quickly

    def test_ensemble_decision_creation(self):
        """Test ensemble decision creation from multiple decisions."""
        decisions = [
            PolicyDecision(PolicyAction.BUY, 0.7, 0.8),
            PolicyDecision(PolicyAction.BUY, 0.6, 0.5),
            PolicyDecision(PolicyAction.HOLD, 0.5, 0.0),
        ]

        ensemble_decision = self.engine._create_ensemble_decision(decisions)

        assert ensemble_decision.action == PolicyAction.BUY  # Majority
        assert ensemble_decision.confidence == pytest.approx(0.6, rel=0.1)  # Average
        assert "ensemble_size" in ensemble_decision.metadata
        assert ensemble_decision.metadata["ensemble_size"] == 3

    def test_concurrent_execution_limits(self):
        """Test concurrent execution limits."""
        config = AutomationConfig(
            execution_mode=ExecutionMode.PARALLEL, max_concurrent_policies=2
        )

        with patch("extensions.intraday_ml_policies.automation_engine.PolicySelector"):
            with patch(
                "extensions.intraday_ml_policies.automation_engine.PolicyPerformanceTracker"
            ):
                engine = PolicyAutomationEngine(self.policies, config)

                # Should limit to 2 concurrent policies
                assert engine.executor._max_workers == 2

                engine.stop()


if __name__ == "__main__":
    pytest.main([__file__])
