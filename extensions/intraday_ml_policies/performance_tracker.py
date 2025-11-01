"""Performance tracker for ML trading policies.

This module provides comprehensive performance tracking and analytics for ML trading policies
including risk-adjusted metrics, regime-specific performance, and trend analysis.
"""

import json
import logging
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from extensions.intraday_ml_policies.adaptive_policy import MarketRegime
from extensions.intraday_ml_policies.base import PolicyDecision


class PerformancePeriod(Enum):
    """Performance tracking periods."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


@dataclass
class TradeRecord:
    """Record of a single trade."""

    policy_id: str
    symbol: str
    entry_time: datetime
    exit_time: datetime | None
    entry_price: float
    exit_price: float | None
    quantity: float
    pnl: float
    return_pct: float
    bars_held: int
    regime: MarketRegime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics for a policy."""

    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    avg_execution_time_ms: float = 0.0
    success_rate: float = 0.0
    avg_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    avg_trade_duration_bars: float = 0.0
    last_updated: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        if self.last_updated:
            data["last_updated"] = self.last_updated.isoformat()
        return data


@dataclass
class RegimePerformance:
    """Performance metrics for a specific market regime."""

    regime: MarketRegime
    total_trades: int = 0
    winning_trades: int = 0
    total_return: float = 0.0
    avg_return: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_duration_bars: float = 0.0
    last_updated: datetime | None = None


class PolicyPerformanceTracker:
    """Comprehensive performance tracker for ML trading policies.

    Tracks execution performance, trading results, risk metrics, and regime-specific
    performance with support for multiple time periods and trend analysis.
    """

    def __init__(
        self,
        max_history_days: int = 365,
        regime_tracking: bool = True,
        detailed_logging: bool = True,
    ):
        """
        Initialize performance tracker.

        Args:
            max_history_days: Maximum days to keep detailed history
            regime_tracking: Enable regime-specific performance tracking
            detailed_logging: Enable detailed execution logging
        """
        self.max_history_days = max_history_days
        self.regime_tracking = regime_tracking
        self.detailed_logging = detailed_logging

        # Core metrics storage
        self.policy_metrics: dict[str, PerformanceMetrics] = defaultdict(
            PerformanceMetrics
        )
        self.execution_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self.trade_history: dict[str, list[TradeRecord]] = defaultdict(list)

        # Regime-specific performance
        self.regime_performance: dict[str, dict[MarketRegime, RegimePerformance]] = (
            defaultdict(lambda: defaultdict(RegimePerformance))
        )

        # Time-based performance
        self.period_performance: dict[
            str, dict[PerformancePeriod, PerformanceMetrics]
        ] = defaultdict(lambda: defaultdict(PerformanceMetrics))

        # Performance trends
        self.performance_trends: dict[str, dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=100))
        )

        # Risk metrics
        self.risk_metrics: dict[str, dict[str, float]] = defaultdict(dict)

        self.logger = logging.getLogger(__name__)

    def record_decision(
        self,
        policy_id: str,
        decision: PolicyDecision,
        execution_time_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a policy decision."""
        # Update basic metrics
        metrics = self.policy_metrics[policy_id]
        metrics.total_executions += 1
        metrics.last_updated = datetime.now()

        if decision and decision.action.value != "hold":
            metrics.successful_executions += 1
        else:
            metrics.failed_executions += 1

        # Update execution time
        if metrics.total_executions == 1:
            metrics.avg_execution_time_ms = execution_time_ms
        else:
            alpha = 0.1
            metrics.avg_execution_time_ms = (
                alpha * execution_time_ms + (1 - alpha) * metrics.avg_execution_time_ms
            )

        # Update success rate
        metrics.success_rate = metrics.successful_executions / metrics.total_executions

        # Record in history
        if self.detailed_logging:
            self.execution_history[policy_id].append(
                {
                    "timestamp": datetime.now(),
                    "decision": decision,
                    "execution_time_ms": execution_time_ms,
                    "metadata": metadata or {},
                }
            )

        # Update trends
        self.performance_trends[policy_id]["execution_time"].append(execution_time_ms)
        self.performance_trends[policy_id]["success_rate"].append(metrics.success_rate)

        self.logger.debug(f"Recorded decision for policy {policy_id}")

    def record_trade(self, policy_id: str, trade: TradeRecord) -> None:
        """Record a completed trade."""
        # Add to trade history
        self.trade_history[policy_id].append(trade)

        # Update policy metrics
        metrics = self.policy_metrics[policy_id]
        metrics.total_pnl += trade.pnl
        metrics.last_updated = datetime.now()

        # Update return metrics
        total_return = sum(t.return_pct for t in self.trade_history[policy_id])
        metrics.avg_return = total_return / len(self.trade_history[policy_id])

        # Update win/loss statistics
        if trade.pnl > 0:
            if not hasattr(metrics, "winning_trades"):
                metrics.winning_trades = 0
            metrics.winning_trades += 1
        else:
            if not hasattr(metrics, "losing_trades"):
                metrics.losing_trades = 0
            metrics.losing_trades += 1

        # Calculate win rate
        total_trades = len(self.trade_history[policy_id])
        if total_trades > 0:
            metrics.win_rate = metrics.winning_trades / total_trades

        # Update average win/loss
        wins = [t.pnl for t in self.trade_history[policy_id] if t.pnl > 0]
        losses = [t.pnl for t in self.trade_history[policy_id] if t.pnl < 0]

        if wins:
            metrics.avg_win = sum(wins) / len(wins)
        if losses:
            metrics.avg_loss = sum(losses) / len(losses)

        # Calculate profit factor
        total_wins = sum(wins)
        total_losses = abs(sum(losses))
        if total_losses > 0:
            metrics.profit_factor = total_wins / total_losses

        # Update trade duration
        durations = [
            t.bars_held for t in self.trade_history[policy_id] if t.bars_held > 0
        ]
        if durations:
            metrics.avg_trade_duration_bars = sum(durations) / len(durations)

        # Calculate risk metrics
        self._calculate_risk_metrics(policy_id)

        # Update regime performance
        if self.regime_tracking and trade.regime:
            self._update_regime_performance(policy_id, trade)

        # Update period performance
        self._update_period_performance(policy_id, trade)

        # Update trends
        self.performance_trends[policy_id]["pnl"].append(trade.pnl)
        self.performance_trends[policy_id]["return"].append(trade.return_pct)

        self.logger.debug(f"Recorded trade for policy {policy_id}: PnL={trade.pnl:.4f}")

    def get_policy_metrics(self, policy_id: str) -> PerformanceMetrics | None:
        """Get performance metrics for a policy."""
        return self.policy_metrics.get(policy_id)

    def get_regime_performance(
        self, policy_id: str, regime: MarketRegime
    ) -> RegimePerformance | None:
        """Get regime-specific performance for a policy."""
        return self.regime_performance.get(policy_id, {}).get(regime)

    def get_period_performance(
        self, policy_id: str, period: PerformancePeriod
    ) -> PerformanceMetrics | None:
        """Get period-specific performance for a policy."""
        return self.period_performance.get(policy_id, {}).get(period)

    def get_performance_summary(self, policy_id: str) -> dict[str, Any]:
        """Get comprehensive performance summary for a policy."""
        metrics = self.policy_metrics.get(policy_id)
        if not metrics:
            return {}

        # Basic metrics
        summary = metrics.to_dict()

        # Recent performance (last 30 days)
        recent_trades = [
            t
            for t in self.trade_history[policy_id]
            if t.entry_time > datetime.now() - timedelta(days=30)
        ]

        if recent_trades:
            recent_pnl = sum(t.pnl for t in recent_trades)
            recent_return = statistics.mean([t.return_pct for t in recent_trades])
            recent_win_rate = sum(1 for t in recent_trades if t.pnl > 0) / len(
                recent_trades
            )

            summary["recent_30_days"] = {
                "total_trades": len(recent_trades),
                "total_pnl": recent_pnl,
                "avg_return": recent_return,
                "win_rate": recent_win_rate,
            }

        # Regime breakdown
        if self.regime_tracking:
            regime_breakdown = {}
            for regime, regime_perf in self.regime_performance.get(
                policy_id, {}
            ).items():
                if regime_perf.total_trades > 0:
                    regime_breakdown[regime.value] = {
                        "trades": regime_perf.total_trades,
                        "win_rate": regime_perf.winning_trades
                        / regime_perf.total_trades,
                        "avg_return": regime_perf.avg_return,
                        "sharpe_ratio": regime_perf.sharpe_ratio,
                    }
            summary["regime_breakdown"] = regime_breakdown

        # Performance trends
        trends = {}
        for metric_name, values in self.performance_trends.get(policy_id, {}).items():
            if len(values) >= 2:
                # Calculate trend (simple linear regression slope)
                x = list(range(len(values)))
                y = list(values)
                n = len(values)
                sum_x = sum(x)
                sum_y = sum(y)
                sum_xy = sum(x[i] * y[i] for i in range(n))
                sum_x2 = sum(x[i] ** 2 for i in range(n))

                if n * sum_x2 - sum_x**2 != 0:
                    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x**2)
                    trends[metric_name] = {
                        "slope": slope,
                        "current": values[-1],
                        "trend": "improving" if slope > 0 else "declining",
                    }

        summary["trends"] = trends

        # Risk metrics
        summary["risk_metrics"] = self.risk_metrics.get(policy_id, {})

        return summary

    def compare_policies(self, policy_ids: list[str]) -> dict[str, Any]:
        """Compare performance across multiple policies."""
        comparison = {"policies": {}, "ranking": [], "summary": {}}

        # Collect metrics for all policies
        for policy_id in policy_ids:
            metrics = self.policy_metrics.get(policy_id)
            if metrics:
                comparison["policies"][policy_id] = metrics.to_dict()

        # Rank policies by composite score
        policy_scores = []
        for policy_id in policy_ids:
            metrics = self.policy_metrics.get(policy_id)
            if metrics and metrics.total_executions > 0:
                # Simple composite score (can be enhanced)
                score = (
                    0.4 * metrics.success_rate
                    + 0.3 * min(2.0, max(0.0, metrics.sharpe_ratio)) / 2.0
                    + 0.2 * min(1.0, max(0.0, metrics.win_rate))
                    + 0.1 * min(1.0, max(-1.0, metrics.avg_return * 100))
                )
                policy_scores.append((policy_id, score))

        # Sort by score
        policy_scores.sort(key=lambda x: x[1], reverse=True)
        comparison["ranking"] = policy_scores

        # Summary statistics
        if policy_scores:
            scores = [score for _, score in policy_scores]
            comparison["summary"] = {
                "best_policy": policy_scores[0][0],
                "worst_policy": policy_scores[-1][0],
                "avg_score": statistics.mean(scores),
                "score_std": statistics.stdev(scores) if len(scores) > 1 else 0.0,
            }

        return comparison

    def cleanup_old_data(self) -> None:
        """Clean up old data beyond retention period."""
        cutoff_date = datetime.now() - timedelta(days=self.max_history_days)

        # Clean trade history
        for policy_id in self.trade_history:
            self.trade_history[policy_id] = [
                trade
                for trade in self.trade_history[policy_id]
                if trade.entry_time > cutoff_date
            ]

        # Clean execution history
        for policy_id in self.execution_history:
            while (
                self.execution_history[policy_id]
                and self.execution_history[policy_id][0]["timestamp"] < cutoff_date
            ):
                self.execution_history[policy_id].popleft()

        self.logger.info("Cleaned up old performance data")

    def export_metrics(self, filepath: str) -> None:
        """Export performance metrics to file."""
        export_data = {"timestamp": datetime.now().isoformat(), "policies": {}}

        for policy_id, metrics in self.policy_metrics.items():
            export_data["policies"][policy_id] = {
                "metrics": metrics.to_dict(),
                "regime_performance": {
                    regime.value: asdict(regime_perf)
                    for regime, regime_perf in self.regime_performance.get(
                        policy_id, {}
                    ).items()
                },
                "trade_count": len(self.trade_history.get(policy_id, [])),
                "execution_count": metrics.total_executions,
            }

        with open(filepath, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        self.logger.info(f"Exported performance metrics to {filepath}")

    def _calculate_risk_metrics(self, policy_id: str) -> None:
        """Calculate risk metrics for a policy."""
        trades = self.trade_history.get(policy_id, [])
        if len(trades) < 2:
            return

        returns = [t.return_pct for t in trades]

        # Calculate volatility
        if len(returns) > 1:
            volatility = statistics.stdev(returns)
            self.policy_metrics[policy_id].volatility = volatility

        # Calculate maximum drawdown
        cumulative_returns = []
        running_sum = 0
        for ret in returns:
            running_sum += ret
            cumulative_returns.append(running_sum)

        if cumulative_returns:
            peak = cumulative_returns[0]
            max_dd = 0
            for value in cumulative_returns:
                peak = max(peak, value)
                dd = (peak - value) / peak if peak != 0 else 0
                max_dd = max(max_dd, dd)

            self.policy_metrics[policy_id].max_drawdown = max_dd

        # Calculate Sharpe ratio (simplified, assuming 0% risk-free rate)
        if len(returns) > 1:
            avg_return = statistics.mean(returns)
            return_std = statistics.stdev(returns) if len(returns) > 1 else 0

            if return_std > 0:
                # Annualized Sharpe ratio (assuming daily returns)
                sharpe = (avg_return * 252) / (return_std * (252**0.5))
                self.policy_metrics[policy_id].sharpe_ratio = sharpe

        # Store additional risk metrics
        self.risk_metrics[policy_id] = {
            "var_95": self._calculate_var(returns, 0.95),
            "var_99": self._calculate_var(returns, 0.99),
            "cvar_95": self._calculate_cvar(returns, 0.95),
            "skewness": self._calculate_skewness(returns),
            "kurtosis": self._calculate_kurtosis(returns),
        }

    def _calculate_var(self, returns: list[float], confidence: float) -> float:
        """Calculate Value at Risk."""
        if not returns:
            return 0.0

        sorted_returns = sorted(returns)
        index = int((1 - confidence) * len(sorted_returns))
        return sorted_returns[index] if index < len(sorted_returns) else 0.0

    def _calculate_cvar(self, returns: list[float], confidence: float) -> float:
        """Calculate Conditional Value at Risk."""
        if not returns:
            return 0.0

        var = self._calculate_var(returns, confidence)
        tail_returns = [r for r in returns if r <= var]

        return statistics.mean(tail_returns) if tail_returns else 0.0

    def _calculate_skewness(self, returns: list[float]) -> float:
        """Calculate return skewness."""
        if len(returns) < 3:
            return 0.0

        mean = statistics.mean(returns)
        std = statistics.stdev(returns)

        if std == 0:
            return 0.0

        skew = sum(((r - mean) / std) ** 3 for r in returns) / len(returns)
        return skew

    def _calculate_kurtosis(self, returns: list[float]) -> float:
        """Calculate return kurtosis."""
        if len(returns) < 4:
            return 0.0

        mean = statistics.mean(returns)
        std = statistics.stdev(returns)

        if std == 0:
            return 0.0

        kurt = sum(((r - mean) / std) ** 4 for r in returns) / len(returns) - 3
        return kurt

    def _update_regime_performance(self, policy_id: str, trade: TradeRecord) -> None:
        """Update regime-specific performance."""
        regime_perf = self.regime_performance[policy_id][trade.regime]
        regime_perf.total_trades += 1
        regime_perf.last_updated = datetime.now()

        if trade.pnl > 0:
            regime_perf.winning_trades += 1

        regime_perf.total_return += trade.return_pct
        regime_perf.avg_return = regime_perf.total_return / regime_perf.total_trades

        # Update duration
        if trade.bars_held > 0:
            if regime_perf.total_trades == 1:
                regime_perf.avg_duration_bars = trade.bars_held
            else:
                alpha = 0.1
                regime_perf.avg_duration_bars = (
                    alpha * trade.bars_held
                    + (1 - alpha) * regime_perf.avg_duration_bars
                )

        # Calculate regime-specific risk metrics
        regime_trades = [
            t for t in self.trade_history[policy_id] if t.regime == trade.regime
        ]
        if len(regime_trades) >= 2:
            returns = [t.return_pct for t in regime_trades]
            regime_perf.volatility = statistics.stdev(returns)

            # Calculate regime Sharpe ratio
            avg_return = statistics.mean(returns)
            if regime_perf.volatility > 0:
                regime_perf.sharpe_ratio = avg_return / regime_perf.volatility

            # Calculate regime max drawdown
            cumulative_returns = []
            running_sum = 0
            for ret in returns:
                running_sum += ret
                cumulative_returns.append(running_sum)

            if cumulative_returns:
                peak = cumulative_returns[0]
                max_dd = 0
                for value in cumulative_returns:
                    peak = max(peak, value)
                    dd = (peak - value) / peak if peak != 0 else 0
                    max_dd = max(max_dd, dd)
                regime_perf.max_drawdown = max_dd

    def _update_period_performance(self, policy_id: str, trade: TradeRecord) -> None:
        """Update period-specific performance."""
        # This is a simplified implementation
        # In a full implementation, this would properly track different periods
        for period in PerformancePeriod:
            period_metrics = self.period_performance[policy_id][period]
            period_metrics.total_pnl += trade.pnl
            period_metrics.last_updated = datetime.now()

            # Update other period metrics as needed
            # This would need proper period boundary logic
