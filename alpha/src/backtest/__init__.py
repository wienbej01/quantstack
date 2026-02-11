"""Backtest engine, execution simulation, and validation modules."""

from .engine import AlphaBacktestEngine, BacktestResult, BarData, Trade
from .execution_sim import FillResult, L2ExecutionSimulator, simulate_execution_batch
from .regime_split import (
    RegimeClassification,
    RegimeStats,
    RegimeStratifier,
    RobustnessReport,
)
from .walk_forward import (
    ConsistencyReport,
    Period,
    WalkForwardPeriod,
    WalkForwardValidator,
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
