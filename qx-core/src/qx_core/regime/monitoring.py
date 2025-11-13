"""
Regime monitoring metrics for regime detection system.

Provides metrics for tracking regime behavior, stability, and performance impact.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from qx_core.schemas import RegimeType


@dataclass
class RegimeStateMetrics:
    """Metrics for tracking individual regime states."""

    regime_type: RegimeType
    total_duration_bars: int = 0
    total_duration_minutes: int = 0
    entry_count: int = 0
    exit_count: int = 0
    avg_duration_bars: float = 0.0
    max_duration_bars: int = 0
    min_duration_bars: int = float("inf")
    first_entry_time: datetime | None = None
    last_exit_time: datetime | None = None

    def update_entry(self, timestamp: datetime) -> None:
        """Record regime entry."""
        self.entry_count += 1
        if self.first_entry_time is None:
            self.first_entry_time = timestamp

    def update_exit(self, entry_time: datetime, exit_time: datetime, bar_count: int) -> None:
        """Record regime exit and update duration metrics."""
        self.exit_count += 1
        self.last_exit_time = exit_time

        # Update duration metrics
        self.total_duration_bars += bar_count
        duration_minutes = int((exit_time - entry_time).total_seconds() / 60)
        self.total_duration_minutes += duration_minutes

        # Update min/max duration
        self.max_duration_bars = max(self.max_duration_bars, bar_count)
        self.min_duration_bars = min(self.min_duration_bars, bar_count)

        # Update average duration
        if self.exit_count > 0:
            self.avg_duration_bars = self.total_duration_bars / self.exit_count

    def get_summary(self) -> dict[str, Any]:
        """Get summary dictionary of regime state metrics."""
        return {
            "regime_type": self.regime_type.value,
            "entry_count": self.entry_count,
            "exit_count": self.exit_count,
            "total_duration_bars": self.total_duration_bars,
            "total_duration_minutes": self.total_duration_minutes,
            "avg_duration_bars": round(self.avg_duration_bars, 2),
            "max_duration_bars": self.max_duration_bars,
            "min_duration_bars": (
                self.min_duration_bars if self.min_duration_bars != float("inf") else 0
            ),
            "first_entry_time": (
                self.first_entry_time.isoformat() if self.first_entry_time else None
            ),
            "last_exit_time": (self.last_exit_time.isoformat() if self.last_exit_time else None),
        }


@dataclass
class RegimeTransitionMetrics:
    """Metrics for tracking regime transitions and stability."""

    transition_matrix: dict[tuple[RegimeType, RegimeType], int] = field(default_factory=dict)
    total_transitions: int = 0
    regime_flips: int = 0  # Number of times regime changed
    same_regime_continuations: int = 0

    # Transition timing metrics
    avg_time_between_flips: float = 0.0
    max_time_between_flips: int = 0
    min_time_between_flips: float("inf") = float("inf")

    # Last flip tracking
    last_flip_time: datetime | None = None
    last_regime: RegimeType | None = None

    def record_transition(
        self,
        from_regime: RegimeType | None,
        to_regime: RegimeType,
        timestamp: datetime,
    ) -> None:
        """Record a regime transition."""
        if from_regime is not None and from_regime != to_regime:
            # This is a regime flip
            self.regime_flips += 1

            # Update transition matrix
            transition_key = (from_regime, to_regime)
            self.transition_matrix[transition_key] = (
                self.transition_matrix.get(transition_key, 0) + 1
            )

            # Update timing metrics
            if self.last_flip_time is not None:
                time_diff = int((timestamp - self.last_flip_time).total_seconds() / 60)
                self.max_time_between_flips = max(self.max_time_between_flips, time_diff)
                self.min_time_between_flips = min(self.min_time_between_flips, time_diff)

                # Update average time between flips
                if self.regime_flips > 1:
                    self.avg_time_between_flips = (
                        self.avg_time_between_flips * (self.regime_flips - 2) + time_diff
                    ) / (self.regime_flips - 1)

            self.last_flip_time = timestamp
        elif from_regime == to_regime:
            # Same regime continuation
            self.same_regime_continuations += 1

        self.total_transitions += 1
        self.last_regime = to_regime

    def get_transition_matrix_df(self) -> pd.DataFrame:
        """Get transition matrix as DataFrame."""
        all_regimes = list(RegimeType)
        matrix_data = []

        for from_regime in all_regimes:
            row = {"from_regime": from_regime.value}
            for to_regime in all_regimes:
                transition_key = (from_regime, to_regime)
                row[f"to_{to_regime.value}"] = self.transition_matrix.get(transition_key, 0)
            matrix_data.append(row)

        return pd.DataFrame(matrix_data).set_index("from_regime")

    def get_summary(self) -> dict[str, Any]:
        """Get summary dictionary of transition metrics."""
        return {
            "total_transitions": self.total_transitions,
            "regime_flips": self.regime_flips,
            "same_regime_continuations": self.same_regime_continuations,
            "avg_time_between_flips_minutes": round(self.avg_time_between_flips, 2),
            "max_time_between_flips_minutes": self.max_time_between_flips,
            "min_time_between_flips_minutes": (
                self.min_time_between_flips if self.min_time_between_flips != float("inf") else 0
            ),
            "flip_frequency_per_hour": round(
                self.regime_flips / max(self.total_transitions / 60, 1), 4
            ),
            "stability_ratio": round(
                self.same_regime_continuations / max(self.total_transitions, 1), 4
            ),
        }


@dataclass
class RegimePerformanceMetrics:
    """Metrics for tracking regime impact on trading performance."""

    regime_returns: dict[RegimeType, list[float]] = field(default_factory=dict)
    regime_trades: dict[RegimeType, int] = field(default_factory=dict)
    regime_win_rate: dict[RegimeType, float] = field(default_factory=dict)
    regime_pnl: dict[RegimeType, float] = field(default_factory=dict)
    regime_sharpe: dict[RegimeType, float] = field(default_factory=dict)

    # Drawdown metrics by regime
    regime_drawdowns: dict[RegimeType, list[float]] = field(default_factory=dict)
    regime_max_drawdown: dict[RegimeType, float] = field(default_factory=dict)

    # Performance attribution
    total_return: float = 0.0
    regime_attribution: dict[RegimeType, float] = field(default_factory=dict)

    def update_trade(self, regime: RegimeType, trade_return: float, is_win: bool) -> None:
        """Update metrics with completed trade."""
        if regime not in self.regime_returns:
            self.regime_returns[regime] = []
            self.regime_trades[regime] = 0
            self.regime_drawdowns[regime] = []

        self.regime_returns[regime].append(trade_return)
        self.regime_trades[regime] += 1

        # Update win rate
        total_trades = self.regime_trades[regime]
        wins = sum(1 for r in self.regime_returns[regime] if r > 0)
        self.regime_win_rate[regime] = wins / total_trades if total_trades > 0 else 0.0

        # Update PnL
        self.regime_pnl[regime] = sum(self.regime_returns[regime])

        # Update Sharpe (simplified)
        if len(self.regime_returns[regime]) > 1:
            returns_array = np.array(self.regime_returns[regime])
            self.regime_sharpe[regime] = (
                np.mean(returns_array) / (np.std(returns_array) + 1e-8)
            ) * np.sqrt(252)  # Annualized

    def update_drawdown(self, regime: RegimeType, drawdown: float) -> None:
        """Update drawdown metrics for regime."""
        if regime not in self.regime_drawdowns:
            self.regime_drawdowns[regime] = []

        self.regime_drawdowns[regime].append(drawdown)
        self.regime_max_drawdown[regime] = max(self.regime_drawdowns[regime])

    def finalize_attribution(self) -> None:
        """Calculate performance attribution by regime."""
        total_pnl = sum(self.regime_pnl.values())
        self.total_return = total_pnl

        for regime, pnl in self.regime_pnl.items():
            self.regime_attribution[regime] = pnl / abs(total_pnl) if total_pnl != 0 else 0.0

    def get_summary(self) -> dict[str, Any]:
        """Get summary dictionary of performance metrics."""
        summary = {"total_return": round(self.total_return, 4), "regime_breakdown": {}}

        for regime in RegimeType:
            if regime in self.regime_trades and self.regime_trades[regime] > 0:
                summary["regime_breakdown"][regime.value] = {
                    "trades": self.regime_trades[regime],
                    "total_pnl": round(self.regime_pnl[regime], 4),
                    "win_rate": round(self.regime_win_rate[regime], 4),
                    "avg_return": round(np.mean(self.regime_returns[regime]), 4),
                    "sharpe": round(self.regime_sharpe[regime], 4),
                    "max_drawdown": round(self.regime_max_drawdown.get(regime, 0.0), 4),
                    "attribution": round(self.regime_attribution.get(regime, 0.0), 4),
                }

        return summary


@dataclass
class RegimeMonitoringMetrics:
    """Comprehensive regime monitoring metrics container."""

    symbol: str
    start_time: datetime
    end_time: datetime | None = None

    # Component metrics
    state_metrics: dict[RegimeType, RegimeStateMetrics] = field(default_factory=dict)
    transition_metrics: RegimeTransitionMetrics = field(default_factory=RegimeTransitionMetrics)
    performance_metrics: RegimePerformanceMetrics = field(default_factory=RegimePerformanceMetrics)

    # Overall statistics
    total_bars: int = 0
    regime_changes: int = 0
    unique_regimes_seen: set[RegimeType] = field(default_factory=set)

    # Health indicators
    data_quality_score: float = 1.0
    detection_confidence_avg: float = 0.0

    def __post_init__(self) -> None:
        """Initialize regime state metrics."""
        for regime_type in RegimeType:
            self.state_metrics[regime_type] = RegimeStateMetrics(regime_type=regime_type)

    def update_regime_state(
        self,
        timestamp: datetime,
        current_regime: RegimeType,
        confidence: float = 1.0,
        bar_data: dict | None = None,
    ) -> None:
        """Update metrics with new regime state."""
        self.total_bars += 1
        self.unique_regimes_seen.add(current_regime)
        self.detection_confidence_avg = (
            self.detection_confidence_avg * (self.total_bars - 1) + confidence
        ) / self.total_bars

        # Record transition if this is not the first state
        if hasattr(self, "_last_regime") and self._last_regime != current_regime:
            self.regime_changes += 1
            self.transition_metrics.record_transition(self._last_regime, current_regime, timestamp)

        self._last_regime = current_regime
        self._last_regime_time = timestamp

    def finalize_session(self, end_time: datetime) -> None:
        """Finalize metrics at end of monitoring session."""
        self.end_time = end_time
        self.performance_metrics.finalize_attribution()

    def get_health_score(self) -> float:
        """Calculate overall regime detection health score."""
        # Factor in regime stability, data quality, and detection confidence
        stability_score = 1.0 - min(self.regime_changes / max(self.total_bars, 1), 1.0)
        diversity_score = len(self.unique_regimes_seen) / len(RegimeType)

        health_score = (
            stability_score * 0.4
            + self.data_quality_score * 0.3
            + self.detection_confidence_avg * 0.2
            + diversity_score * 0.1
        )

        return round(health_score, 4)

    def get_comprehensive_summary(self) -> dict[str, Any]:
        """Get comprehensive summary of all regime metrics."""
        return {
            "metadata": {
                "symbol": self.symbol,
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "total_bars": self.total_bars,
                "regime_changes": self.regime_changes,
                "unique_regimes_seen": [r.value for r in self.unique_regimes_seen],
                "health_score": self.get_health_score(),
            },
            "state_metrics": {
                regime.value: metrics.get_summary()
                for regime, metrics in self.state_metrics.items()
            },
            "transition_metrics": self.transition_metrics.get_summary(),
            "performance_metrics": self.performance_metrics.get_summary(),
        }

    def export_transition_matrix(self) -> pd.DataFrame:
        """Export regime transition matrix as DataFrame."""
        return self.transition_metrics.get_transition_matrix_df()


class RegimeMonitor:
    """Real-time regime monitoring and metrics collection."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.metrics = RegimeMonitoringMetrics(symbol=symbol, start_time=datetime.now())
        self._current_regime: RegimeType | None = None
        self._regime_start_time: datetime | None = None
        self._regime_bar_count: int = 0

    def update(
        self,
        timestamp: datetime,
        regime: RegimeType,
        confidence: float = 1.0,
        bar_data: dict | None = None,
    ) -> None:
        """Update monitor with new regime detection."""
        # Record regime state change
        if self._current_regime != regime:
            # Finalize previous regime if exists
            if self._current_regime is not None and self._regime_start_time is not None:
                self.metrics.state_metrics[self._current_regime].update_exit(
                    self._regime_start_time, timestamp, self._regime_bar_count
                )

            # Start new regime
            self._current_regime = regime
            self._regime_start_time = timestamp
            self._regime_bar_count = 0
            self.metrics.state_metrics[regime].update_entry(timestamp)

        self._regime_bar_count += 1
        self.metrics.update_regime_state(timestamp, regime, confidence, bar_data)

    def record_trade(self, trade_return: float, is_win: bool) -> None:
        """Record completed trade for current regime."""
        if self._current_regime:
            self.metrics.performance_metrics.update_trade(
                self._current_regime, trade_return, is_win
            )

    def record_drawdown(self, drawdown: float) -> None:
        """Record drawdown for current regime."""
        if self._current_regime:
            self.metrics.performance_metrics.update_drawdown(self._current_regime, drawdown)

    def finalize(self) -> RegimeMonitoringMetrics:
        """Finalize monitoring and return complete metrics."""
        self.metrics.finalize_session(datetime.now())
        return self.metrics

    def get_real_time_summary(self) -> dict[str, Any]:
        """Get real-time summary of current monitoring session."""
        if self._current_regime is None:
            return {"status": "No regime data available"}

        current_duration_bars = self._regime_bar_count
        current_duration_minutes = (
            int((datetime.now() - self._regime_start_time).total_seconds() / 60)
            if self._regime_start_time
            else 0
        )

        return {
            "symbol": self.symbol,
            "current_regime": self._current_regime.value,
            "current_duration_bars": current_duration_bars,
            "current_duration_minutes": current_duration_minutes,
            "total_bars_monitored": self.metrics.total_bars,
            "regime_changes_so_far": self.metrics.regime_changes,
            "health_score": self.metrics.get_health_score(),
            "regimes_seen": [r.value for r in self.metrics.unique_regimes_seen],
        }
