"""qx-backtest: Event-driven backtesting engine and entry/exit AB testing framework."""

from .ab_testing import ABTestConfig, ABTestResult, EntryExitABTest
from .engine import BacktestConfig, BacktestEngine, BacktestResult
from .fill import DefaultFiller, Fill, Filler
from .order import Order, OrderStatus, OrderType
from .policies.vwap_revert import VwapRevertPolicy
from .portfolio import Portfolio, Position

__version__ = "0.1.0"

__all__ = [
    # Core engine
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
    # Portfolio management
    "Portfolio",
    "Position",
    # Order management
    "Order",
    "OrderType",
    "OrderStatus",
    # Fill simulation
    "Fill",
    "Filler",
    "DefaultFiller",
    # Trading policies
    "VwapRevertPolicy",
    # AB testing framework
    "EntryExitABTest",
    "ABTestConfig",
    "ABTestResult",
]
