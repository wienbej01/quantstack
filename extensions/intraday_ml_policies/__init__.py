"""Intraday ML trading policies extension.

This module provides ML-based trading policies that integrate with the existing
qx-backtest framework while maintaining strict compliance with intraday rules.
"""

from .base_ml_policy import BaseMLPolicy
from .classification_policy import MLClassificationPolicy
from .regression_policy import MLRegressionPolicy

# Sprint 11 Advanced Policy Framework
from .base import BaseMLPolicy, PolicyDecision, PolicySignal, PolicyAction, PolicyMetrics
from .adaptive_policy import AdaptiveMLPolicy, MarketRegime, RegimeConfig
from .ensemble_policy import EnsemblePolicy, EnsembleMethod, ModelConfig
from .risk_aware_policy import RiskAwareMLPolicy, RiskStrategy, RiskConfig
from .automation_engine import (
    PolicyAutomationEngine, AutomationConfig, AutomationState, ExecutionMode,
    ExecutionResult, AutomationMetrics
)
from .policy_selector import (
    PolicySelector, SelectionCriteria, SelectionMethod, SelectionScore
)
from .performance_tracker import (
    PolicyPerformanceTracker, PerformanceMetrics, TradeRecord, RegimePerformance,
    PerformancePeriod
)

__version__ = "0.2.0"
__all__ = [
    # Original policies
    "BaseMLPolicy",
    "MLClassificationPolicy",
    "MLRegressionPolicy",

    # Sprint 11 Advanced Framework
    "PolicyDecision",
    "PolicySignal",
    "PolicyAction",
    "PolicyMetrics",
    "AdaptiveMLPolicy",
    "MarketRegime",
    "RegimeConfig",
    "EnsemblePolicy",
    "EnsembleMethod",
    "ModelConfig",
    "RiskAwareMLPolicy",
    "RiskStrategy",
    "RiskConfig",
    "PolicyAutomationEngine",
    "AutomationConfig",
    "AutomationState",
    "ExecutionMode",
    "ExecutionResult",
    "AutomationMetrics",
    "PolicySelector",
    "SelectionCriteria",
    "SelectionMethod",
    "SelectionScore",
    "PolicyPerformanceTracker",
    "PerformanceMetrics",
    "TradeRecord",
    "RegimePerformance",
    "PerformancePeriod",
]