"""Intraday ML trading policies extension.

This module provides ML-based trading policies that integrate with the existing
qx-backtest framework while maintaining strict compliance with intraday rules.
"""

from .adaptive_policy import AdaptiveMLPolicy, MarketRegime, RegimeConfig
from .automation_engine import (
    AutomationConfig,
    AutomationMetrics,
    AutomationState,
    ExecutionMode,
    ExecutionResult,
    PolicyAutomationEngine,
)

# Sprint 11 Advanced Policy Framework
from .base import (
    BaseMLPolicy,
    PolicyAction,
    PolicyDecision,
    PolicyMetrics,
    PolicySignal,
)
from .base_ml_policy import BaseMLPolicy
from .classification_policy import MLClassificationPolicy
from .ensemble_policy import EnsembleMethod, EnsemblePolicy, ModelConfig
from .performance_tracker import (
    PerformanceMetrics,
    PerformancePeriod,
    PolicyPerformanceTracker,
    RegimePerformance,
    TradeRecord,
)
from .policy_selector import (
    PolicySelector,
    SelectionCriteria,
    SelectionMethod,
    SelectionScore,
)
from .regression_policy import MLRegressionPolicy
from .risk_aware_policy import RiskAwareMLPolicy, RiskConfig, RiskStrategy

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
