"""Backtest engine, execution simulation, and validation modules."""

from .engine import (
    AlphaBacktestEngine,
    BacktestResult,
    Trade,
    BarData,
)
from .execution_sim import (
    L2ExecutionSimulator,
    FillResult,
    simulate_execution_batch,
)
from .walk_forward import (
    WalkForwardValidator,
    Period,
    WalkForwardPeriod,
    ConsistencyReport,
)
from .regime_split import (
    RegimeStratifier,
    RegimeClassification,
    RegimeStats,
    RobustnessReport,
)

__all__ = [
    "AlphaBacktestEngine",
    "BacktestResult",
    "Trade",
    "BarData",
    "L2ExecutionSimulator",
    "FillResult",
    "simulate_execution_batch",
    "WalkForwardValidator",
    "Period",
    "WalkForwardPeriod",
    "ConsistencyReport",
    "RegimeStratifier",
    "RegimeClassification",
    "RegimeStats",
    "RobustnessReport",
]
