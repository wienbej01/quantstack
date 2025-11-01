"""Policy automation engine for advanced ML policy management.

This module provides automated execution, monitoring, and management of ML trading policies
with support for multiple execution modes and real-time adaptation.
"""

import asyncio
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from extensions.intraday_ml_policies.base import BaseMLPolicy, PolicyDecision
from extensions.intraday_ml_policies.performance_tracker import PolicyPerformanceTracker
from extensions.intraday_ml_policies.policy_selector import (
    PolicySelector,
    SelectionCriteria,
)


class AutomationState(Enum):
    """Automation engine states."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


class ExecutionMode(Enum):
    """Policy execution modes."""

    SINGLE = "single"  # Execute single best policy
    PARALLEL = "parallel"  # Execute all policies in parallel
    ENSEMBLE = "ensemble"  # Execute ensemble of policies
    ADAPTIVE = "adaptive"  # Adaptively select based on conditions


@dataclass
class AutomationConfig:
    """Configuration for policy automation engine."""

    execution_mode: ExecutionMode = ExecutionMode.PARALLEL
    update_interval_seconds: int = 60
    max_concurrent_policies: int = 5
    enable_monitoring: bool = True
    enable_auto_rebalance: bool = True
    performance_lookback_days: int = 30
    min_execution_confidence: float = 0.6
    max_execution_time_ms: float = 5000.0
    error_retry_attempts: int = 3
    error_retry_delay_seconds: float = 5.0


@dataclass
class ExecutionResult:
    """Result of policy execution."""

    policy_id: str
    decision: PolicyDecision | None
    execution_time_ms: float
    success: bool
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutomationMetrics:
    """Automation engine performance metrics."""

    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    avg_execution_time_ms: float = 0.0
    policies_executed: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_execution_time: datetime | None = None
    uptime_seconds: float = 0.0
    error_rate: float = 0.0


class PolicyAutomationEngine:
    """Advanced policy automation engine for ML trading policies.

    Provides automated execution, monitoring, and management of ML trading policies
    with support for multiple execution modes and real-time adaptation.
    """

    def __init__(
        self,
        policies: dict[str, BaseMLPolicy],
        config: AutomationConfig,
        policy_selector: PolicySelector | None = None,
        performance_tracker: PolicyPerformanceTracker | None = None,
    ):
        """
        Initialize policy automation engine.

        Args:
            policies: Dictionary of policy ID to policy instances
            config: Automation configuration
            policy_selector: Optional policy selector for adaptive execution
            performance_tracker: Optional performance tracker
        """
        self.policies = policies
        self.config = config
        self.policy_selector = policy_selector or PolicySelector()
        self.performance_tracker = performance_tracker or PolicyPerformanceTracker()

        # Engine state
        self.state = AutomationState.STOPPED
        self.execution_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

        # Execution management
        self.executor = ThreadPoolExecutor(max_workers=config.max_concurrent_policies)
        self.execution_queue = asyncio.Queue()
        self.result_queue = asyncio.Queue()

        # Metrics and monitoring
        self.metrics = AutomationMetrics()
        self.execution_statistics: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "avg_execution_time_ms": 0.0,
                "last_execution": None,
            }
        )

        # Callbacks
        self.execution_callbacks: list[Callable[[ExecutionResult], None]] = []
        self.error_callbacks: list[Callable[[str, Exception], None]] = []

        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        """Start the automation engine."""
        if self.state != AutomationState.STOPPED:
            raise RuntimeError(f"Engine already running (state: {self.state})")

        self.state = AutomationState.STARTING
        self.stop_event.clear()
        self.pause_event.clear()

        self.execution_thread = threading.Thread(
            target=self._execution_loop, daemon=True
        )
        self.execution_thread.start()

        # Wait for startup
        time.sleep(0.1)
        if self.state == AutomationState.STARTING:
            self.state = AutomationState.RUNNING

        self.logger.info("Policy automation engine started")

    def stop(self) -> None:
        """Stop the automation engine."""
        if self.state == AutomationState.STOPPED:
            return

        self.state = AutomationState.STOPPING
        self.stop_event.set()

        if self.execution_thread and self.execution_thread.is_alive():
            self.execution_thread.join(timeout=10.0)

        self.executor.shutdown(wait=True)
        self.state = AutomationState.STOPPED

        self.logger.info("Policy automation engine stopped")

    def pause(self) -> None:
        """Pause the automation engine."""
        if self.state != AutomationState.RUNNING:
            raise RuntimeError(f"Cannot pause engine in state: {self.state}")

        self.state = AutomationState.PAUSED
        self.pause_event.set()
        self.logger.info("Policy automation engine paused")

    def resume(self) -> None:
        """Resume the automation engine."""
        if self.state != AutomationState.PAUSED:
            raise RuntimeError(f"Cannot resume engine in state: {self.state}")

        self.state = AutomationState.RUNNING
        self.pause_event.clear()
        self.logger.info("Policy automation engine resumed")

    def add_policy(self, policy_id: str, policy: BaseMLPolicy) -> None:
        """Add a policy to the engine."""
        self.policies[policy_id] = policy
        self.logger.info(f"Added policy: {policy_id}")

    def remove_policy(self, policy_id: str) -> None:
        """Remove a policy from the engine."""
        if policy_id in self.policies:
            del self.policies[policy_id]
            self.logger.info(f"Removed policy: {policy_id}")

    def update_config(self, config: AutomationConfig) -> None:
        """Update engine configuration."""
        self.config = config
        self.logger.info("Updated automation configuration")

    def execute_policies(
        self, market_data: Any, portfolio: Any, policy_ids: list[str] | None = None
    ) -> list[ExecutionResult]:
        """Execute policies immediately."""
        if policy_ids is None:
            policy_ids = list(self.policies.keys())

        return self._execute_policies_batch(market_data, portfolio, policy_ids)

    def get_engine_status(self) -> dict[str, Any]:
        """Get current engine status."""
        return {
            "state": self.state.value,
            "execution_mode": self.config.execution_mode.value,
            "total_policies": len(self.policies),
            "policy_ids": list(self.policies.keys()),
            "metrics": {
                "total_executions": self.metrics.total_executions,
                "successful_executions": self.metrics.successful_executions,
                "failed_executions": self.metrics.failed_executions,
                "avg_execution_time_ms": self.metrics.avg_execution_time_ms,
                "error_rate": self.metrics.error_rate,
                "uptime_seconds": self.metrics.uptime_seconds,
            },
            "last_execution": (
                self.metrics.last_execution_time.isoformat()
                if self.metrics.last_execution_time
                else None
            ),
        }

    def add_execution_callback(
        self, callback: Callable[[ExecutionResult], None]
    ) -> None:
        """Add callback for execution results."""
        self.execution_callbacks.append(callback)

    def add_error_callback(self, callback: Callable[[str, Exception], None]) -> None:
        """Add callback for error handling."""
        self.error_callbacks.append(callback)

    def _execution_loop(self) -> None:
        """Main execution loop."""
        start_time = time.time()

        while not self.stop_event.is_set():
            try:
                # Check if paused
                if self.pause_event.is_set():
                    time.sleep(0.1)
                    continue

                # Execute policies cycle
                self._execute_policies_cycle()

                # Update uptime
                self.metrics.uptime_seconds = time.time() - start_time

                # Sleep for update interval
                self.stop_event.wait(self.config.update_interval_seconds)

            except Exception as e:
                self.logger.error(f"Error in execution loop: {e}")
                self.state = AutomationState.ERROR

                # Call error callbacks
                for callback in self.error_callbacks:
                    try:
                        callback("execution_loop", e)
                    except Exception as callback_error:
                        self.logger.error(f"Error in error callback: {callback_error}")

                # Wait before retry
                time.sleep(self.config.error_retry_delay_seconds)

    def _execute_policies_cycle(self) -> None:
        """Execute one cycle of policies."""
        try:
            # Select policies for execution
            policy_ids = self._select_policies_for_execution()

            if not policy_ids:
                self.logger.debug("No policies selected for execution")
                return

            # Execute policies based on mode
            if self.config.execution_mode == ExecutionMode.SINGLE:
                results = [self._execute_single_policy(policy_ids[0])]
            elif self.config.execution_mode == ExecutionMode.PARALLEL:
                results = self._execute_parallel(policy_ids)
            elif self.config.execution_mode == ExecutionMode.ENSEMBLE:
                results = self._execute_ensemble(policy_ids)
            elif self.config.execution_mode == ExecutionMode.ADAPTIVE:
                results = self._execute_adaptive(policy_ids)
            else:
                raise ValueError(
                    f"Unknown execution mode: {self.config.execution_mode}"
                )

            # Process results
            self._process_execution_results(results)

        except Exception as e:
            self.logger.error(f"Error in execution cycle: {e}")
            raise

    def _select_policies_for_execution(self) -> list[str]:
        """Select policies for execution based on current mode."""
        if not self.policies:
            return []

        if self.config.execution_mode == ExecutionMode.SINGLE:
            # Select single best policy
            criteria = SelectionCriteria(method="best_performance", min_executions=10)
            best_policy = self.policy_selector.select_best_policy(
                self.policies, criteria
            )
            return [best_policy] if best_policy else []

        elif self.config.execution_mode == ExecutionMode.PARALLEL:
            # Execute all policies
            return list(self.policies.keys())

        elif self.config.execution_mode == ExecutionMode.ENSEMBLE:
            # Select top policies for ensemble
            criteria = SelectionCriteria(
                method="ensemble", top_k=min(3, len(self.policies))
            )
            best_policy = self.policy_selector.select_best_policy(
                self.policies, criteria
            )
            return [best_policy] if best_policy else list(self.policies.keys())

        elif self.config.execution_mode == ExecutionMode.ADAPTIVE:
            # Adaptively select based on current conditions
            criteria = SelectionCriteria(method="regime_based", min_executions=5)
            best_policy = self.policy_selector.select_best_policy(
                self.policies, criteria
            )
            return [best_policy] if best_policy else list(self.policies.keys())

        return list(self.policies.keys())

    def _execute_single_policy(self, policy_id: str) -> ExecutionResult:
        """Execute a single policy."""
        start_time = time.time()

        try:
            policy = self.policies[policy_id]

            # Mock market data and portfolio for testing
            market_data = None
            portfolio = None

            decision = policy.decide(market_data, portfolio)
            execution_time_ms = (time.time() - start_time) * 1000

            result = ExecutionResult(
                policy_id=policy_id,
                decision=decision,
                execution_time_ms=execution_time_ms,
                success=True,
            )

            # Record in performance tracker
            self.performance_tracker.record_decision(
                policy_id, decision, execution_time_ms
            )

            return result

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            self.logger.error(f"Policy {policy_id} execution failed: {e}")

            return ExecutionResult(
                policy_id=policy_id,
                decision=None,
                execution_time_ms=execution_time_ms,
                success=False,
                error_message=str(e),
            )

    def _execute_parallel(self, policy_ids: list[str]) -> list[ExecutionResult]:
        """Execute policies in parallel."""
        futures = {}

        for policy_id in policy_ids:
            if policy_id in self.policies:
                future = self.executor.submit(self._execute_single_policy, policy_id)
                futures[future] = policy_id

        results = []
        for future in as_completed(
            futures, timeout=self.config.max_execution_time_ms / 1000.0
        ):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                policy_id = futures[future]
                self.logger.error(f"Parallel execution failed for {policy_id}: {e}")

                results.append(
                    ExecutionResult(
                        policy_id=policy_id,
                        decision=None,
                        execution_time_ms=0.0,
                        success=False,
                        error_message=str(e),
                    )
                )

        return results

    def _execute_ensemble(self, policy_ids: list[str]) -> list[ExecutionResult]:
        """Execute policies as ensemble."""
        # Execute individual policies
        individual_results = self._execute_parallel(policy_ids)

        # Create ensemble decision
        successful_results = [r for r in individual_results if r.success and r.decision]

        if successful_results:
            ensemble_decision = self._create_ensemble_decision(
                [r.decision for r in successful_results]
            )
            ensemble_result = ExecutionResult(
                policy_id="ensemble",
                decision=ensemble_decision,
                execution_time_ms=sum(r.execution_time_ms for r in individual_results),
                success=True,
                metadata={
                    "ensemble_policies": [r.policy_id for r in successful_results],
                    "ensemble_size": len(successful_results),
                },
            )
            return [ensemble_result]
        else:
            # No successful executions
            return [
                ExecutionResult(
                    policy_id="ensemble",
                    decision=None,
                    execution_time_ms=0.0,
                    success=False,
                    error_message="No successful policy executions",
                )
            ]

    def _execute_adaptive(self, policy_ids: list[str]) -> list[ExecutionResult]:
        """Execute policies with adaptive selection."""
        # For now, fall back to single best policy
        # In a full implementation, this would consider market conditions, recent performance, etc.
        if policy_ids:
            return [self._execute_single_policy(policy_ids[0])]
        else:
            return [
                ExecutionResult(
                    policy_id="adaptive",
                    decision=None,
                    execution_time_ms=0.0,
                    success=False,
                    error_message="No policies available for adaptive execution",
                )
            ]

    def _create_ensemble_decision(
        self, decisions: list[PolicyDecision]
    ) -> PolicyDecision:
        """Create ensemble decision from multiple decisions."""
        if not decisions:
            raise ValueError("No decisions provided for ensemble")

        # Simple voting for action
        from collections import Counter

        action_votes = Counter(d.action for d in decisions)
        ensemble_action = action_votes.most_common(1)[0][0]

        # Average confidence
        avg_confidence = sum(d.confidence for d in decisions) / len(decisions)

        # Average signal strength
        avg_signal = sum(d.signal_strength for d in decisions) / len(decisions)

        return PolicyDecision(
            action=ensemble_action,
            confidence=avg_confidence,
            signal_strength=avg_signal,
            metadata={
                "ensemble_size": len(decisions),
                "voting_pattern": dict(action_votes),
            },
        )

    def _process_execution_results(self, results: list[ExecutionResult]) -> None:
        """Process execution results and update metrics."""
        for result in results:
            # Update global metrics
            self.metrics.total_executions += 1
            self.metrics.last_execution_time = datetime.now()

            if result.success:
                self.metrics.successful_executions += 1
            else:
                self.metrics.failed_executions += 1

            # Update average execution time
            if self.metrics.total_executions == 1:
                self.metrics.avg_execution_time_ms = result.execution_time_ms
            else:
                alpha = 0.1
                self.metrics.avg_execution_time_ms = (
                    alpha * result.execution_time_ms
                    + (1 - alpha) * self.metrics.avg_execution_time_ms
                )

            # Update policy-specific statistics
            stats = self.execution_statistics[result.policy_id]
            stats["total_executions"] += 1
            stats["last_execution"] = datetime.now()

            if result.success:
                stats["successful_executions"] += 1
            else:
                stats["failed_executions"] += 1

            # Update average execution time for policy
            if stats["total_executions"] == 1:
                stats["avg_execution_time_ms"] = result.execution_time_ms
            else:
                alpha = 0.1
                stats["avg_execution_time_ms"] = (
                    alpha * result.execution_time_ms
                    + (1 - alpha) * stats["avg_execution_time_ms"]
                )

            # Update error rate
            if self.metrics.total_executions > 0:
                self.metrics.error_rate = (
                    self.metrics.failed_executions / self.metrics.total_executions
                )

            # Call execution callbacks
            for callback in self.execution_callbacks:
                try:
                    callback(result)
                except Exception as e:
                    self.logger.error(f"Error in execution callback: {e}")

    def _execute_policies_batch(
        self, market_data: Any, portfolio: Any, policy_ids: list[str]
    ) -> list[ExecutionResult]:
        """Execute a batch of policies."""
        # For now, use the existing execution methods
        # In a full implementation, this would properly handle market_data and portfolio
        if self.config.execution_mode == ExecutionMode.PARALLEL:
            return self._execute_parallel(policy_ids)
        elif self.config.execution_mode == ExecutionMode.ENSEMBLE:
            return self._execute_ensemble(policy_ids)
        else:
            return [
                (
                    self._execute_single_policy(policy_ids[0])
                    if policy_ids
                    else ExecutionResult("", None, 0.0, False, "No policies specified")
                )
            ]
