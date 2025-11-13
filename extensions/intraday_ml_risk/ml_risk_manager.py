"""ML-powered risk management for intraday trading."""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry


class RiskLevel(Enum):
    """Risk level classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskMetrics:
    """Risk metrics for a position or portfolio."""

    timestamp: datetime
    position_id: str | None  # None for portfolio-level metrics
    symbol: str
    risk_level: RiskLevel
    var_95: float  # Value at Risk (95%)
    var_99: float  # Value at Risk (99%)
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    beta: float
    volatility: float
    correlation_risk: float
    concentration_risk: float
    liquidity_risk: float
    total_risk_score: float
    risk_factors: dict[str, float] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class RiskLimit:
    """Risk limit configuration."""

    name: str
    metric_name: str
    threshold: float
    operator: str  # "lt", "gt", "eq"
    action: str  # "warn", "reduce", "close", "stop_trading"
    enabled: bool = True
    cooldown_minutes: int = 5


class RiskModelManager:
    """Manages ML models for risk assessment."""

    def __init__(self, registry: MLModelRegistry | None = None):
        self.registry = registry or MLModelRegistry()
        self.logger = logging.getLogger(__name__)
        self.models: dict[str, MLPredictor] = {}
        self.model_cache_timeout = timedelta(minutes=30)
        self._last_load_time = {}

    def load_risk_model(self, model_id: str) -> bool:
        """Load risk assessment model."""
        try:
            if model_id in self.models:
                # Check cache timeout
                last_load = self._last_load_time.get(model_id, datetime.min)
                if datetime.now() - last_load < self.model_cache_timeout:
                    return True

            predictor = MLPredictor(model_id, self.registry)
            self.models[model_id] = predictor
            self._last_load_time[model_id] = datetime.now()

            self.logger.info(f"Loaded risk model: {model_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to load risk model {model_id}: {e}")
            return False

    def predict_risk_metrics(
        self, model_id: str, features: dict[str, float]
    ) -> dict[str, float] | None:
        """Predict risk metrics using ML model."""
        if model_id not in self.models and not self.load_risk_model(model_id):
            return None

        try:
            predictor = self.models[model_id]
            feature_df = pd.DataFrame([features])
            result = predictor.predict(feature_df)

            # Convert prediction to risk metrics format
            if result.prediction and len(result.prediction) > 0:
                return {
                    "risk_score": float(result.prediction[0]),
                    "confidence": (
                        float(result.prediction_probability[0])
                        if result.prediction_probability
                        else 0.5
                    ),
                    "model_id": model_id,
                    "timestamp": datetime.now().isoformat(),
                }

        except Exception as e:
            self.logger.error(f"Risk prediction failed: {e}")

        return None


class PositionRiskMonitor:
    """Monitors risk for individual positions."""

    def __init__(self, risk_model_manager: RiskModelManager):
        self.risk_model_manager = risk_model_manager
        self.logger = logging.getLogger(__name__)
        self.position_data: dict[str, dict[str, Any]] = {}
        self.risk_history: dict[str, list[RiskMetrics]] = {}
        self._lock = threading.Lock()

    def update_position(
        self,
        position_id: str,
        symbol: str,
        size: float,
        entry_price: float,
        current_price: float,
        features: dict[str, float] | None = None,
        risk_model_id: str | None = None,
    ) -> RiskMetrics:
        """Update position and calculate current risk metrics."""
        with self._lock:
            # Store position data
            self.position_data[position_id] = {
                "symbol": symbol,
                "size": size,
                "entry_price": entry_price,
                "current_price": current_price,
                "features": features or {},
                "risk_model_id": risk_model_id,
                "last_updated": datetime.now(),
            }

            # Calculate risk metrics
            risk_metrics = self._calculate_position_risk(position_id)

            # Store risk history
            if position_id not in self.risk_history:
                self.risk_history[position_id] = []
            self.risk_history[position_id].append(risk_metrics)

            # Keep only last 100 risk measurements
            if len(self.risk_history[position_id]) > 100:
                self.risk_history[position_id] = self.risk_history[position_id][-100:]

            return risk_metrics

    def _calculate_position_risk(self, position_id: str) -> RiskMetrics:
        """Calculate risk metrics for a position."""
        position_data = self.position_data[position_id]
        symbol = position_data["symbol"]
        size = position_data["size"]
        entry_price = position_data["entry_price"]
        current_price = position_data["current_price"]

        # Calculate basic metrics
        pnl_pct = (current_price - entry_price) / entry_price * 100
        position_value = size * current_price

        # Calculate volatility (simplified - would use historical data in production)
        volatility = abs(current_price - entry_price) / entry_price * np.sqrt(252)  # Annualized

        # Calculate VaR (simplified)
        var_95 = abs(position_value * volatility * 1.65)  # 95% VaR
        var_99 = abs(position_value * volatility * 2.33)  # 99% VaR

        # Calculate max drawdown (simplified)
        max_drawdown = abs(min(pnl_pct, 0))

        # Calculate Sharpe ratio (simplified)
        risk_free_rate = 0.02  # 2% annual risk-free rate
        excess_return = pnl_pct / 100 - risk_free_rate / 252  # Daily excess return
        sharpe_ratio = excess_return / (volatility / np.sqrt(252)) if volatility > 0 else 0

        # Calculate Sortino ratio (simplified)
        downside_deviation = (
            volatility * np.sqrt(max(0, -excess_return) / abs(excess_return))
            if excess_return != 0
            else volatility
        )
        sortino_ratio = excess_return / downside_deviation if downside_deviation > 0 else 0

        # Calculate beta (simplified - would use market data in production)
        beta = 1.0  # Default beta

        # Calculate risk scores
        correlation_risk = min(1.0, abs(beta - 1.0) * 2)  # Higher if beta deviates from 1
        concentration_risk = min(1.0, abs(size) / 10000)  # Higher for larger positions
        liquidity_risk = 0.3  # Simplified liquidity risk

        # Get ML risk prediction if available
        ml_risk_score = 0.5
        if position_data["risk_model_id"] and position_data["features"]:
            ml_prediction = self.risk_model_manager.predict_risk_metrics(
                position_data["risk_model_id"], position_data["features"]
            )
            if ml_prediction:
                ml_risk_score = ml_prediction["risk_score"]

        # Calculate total risk score (0-1)
        total_risk_score = (
            0.3 * min(1.0, volatility * 10)
            + 0.2 * min(1.0, var_95 / position_value if position_value > 0 else 0)
            + 0.15 * min(1.0, max_drawdown / 10)
            + 0.1 * correlation_risk
            + 0.1 * concentration_risk
            + 0.1 * liquidity_risk
            + 0.05 * ml_risk_score
        )

        # Determine risk level
        if total_risk_score < 0.3:
            risk_level = RiskLevel.LOW
        elif total_risk_score < 0.6:
            risk_level = RiskLevel.MEDIUM
        elif total_risk_score < 0.8:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.CRITICAL

        # Generate recommendations
        recommendations = []
        if total_risk_score > 0.7:
            recommendations.append("Consider reducing position size")
        if volatility > 0.3:
            recommendations.append("High volatility detected")
        if max_drawdown < -5:
            recommendations.append("Consider stop-loss placement")

        # Risk factors
        risk_factors = {
            "volatility": volatility,
            "var_95_ratio": var_95 / position_value if position_value > 0 else 0,
            "drawdown": max_drawdown,
            "ml_risk": ml_risk_score,
        }

        return RiskMetrics(
            timestamp=datetime.now(),
            position_id=position_id,
            symbol=symbol,
            risk_level=risk_level,
            var_95=var_95,
            var_99=var_99,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            beta=beta,
            volatility=volatility,
            correlation_risk=correlation_risk,
            concentration_risk=concentration_risk,
            liquidity_risk=liquidity_risk,
            total_risk_score=total_risk_score,
            risk_factors=risk_factors,
            recommendations=recommendations,
        )

    def get_position_risk(self, position_id: str) -> RiskMetrics | None:
        """Get current risk metrics for a position."""
        with self._lock:
            if position_id not in self.position_data:
                return None

            # Return latest risk metrics
            if position_id in self.risk_history and self.risk_history[position_id]:
                return self.risk_history[position_id][-1]

            # Calculate if not available
            return self._calculate_position_risk(position_id)

    def get_risk_history(self, position_id: str, limit: int = 50) -> list[RiskMetrics]:
        """Get risk history for a position."""
        with self._lock:
            if position_id not in self.risk_history:
                return []
            return self.risk_history[position_id][-limit:]

    def remove_position(self, position_id: str):
        """Remove a position from monitoring."""
        with self._lock:
            self.position_data.pop(position_id, None)
            self.risk_history.pop(position_id, None)
            self.logger.info(f"Removed position {position_id} from risk monitoring")


class PortfolioRiskMonitor:
    """Monitors portfolio-level risk."""

    def __init__(self, position_monitor: PositionRiskMonitor):
        self.position_monitor = position_monitor
        self.logger = logging.getLogger(__name__)
        self.portfolio_risk_history: list[RiskMetrics] = []
        self._lock = threading.Lock()

    def calculate_portfolio_risk(self) -> RiskMetrics:
        """Calculate portfolio-level risk metrics."""
        with self._lock:
            # Get all current positions
            positions = list(self.position_monitor.position_data.keys())
            if not positions:
                return self._create_empty_portfolio_risk()

            # Collect individual position risks
            position_risks = []
            for position_id in positions:
                risk_metrics = self.position_monitor.get_position_risk(position_id)
                if risk_metrics:
                    position_risks.append(risk_metrics)

            if not position_risks:
                return self._create_empty_portfolio_risk()

            # Calculate portfolio metrics
            total_var_95 = sum(risk.var_95 for risk in position_risks)
            total_var_99 = sum(risk.var_99 for risk in position_risks)
            avg_volatility = np.mean([risk.volatility for risk in position_risks])
            max_drawdown = max(risk.max_drawdown for risk in position_risks)

            # Portfolio Sharpe ratio (weighted average)
            total_excess_return = 0
            total_risk = 0
            for risk in position_risks:
                excess_return = risk.sharpe_ratio * risk.volatility / np.sqrt(252)
                total_excess_return += excess_return
                total_risk += risk.volatility

            portfolio_sharpe = total_excess_return / total_risk if total_risk > 0 else 0
            portfolio_sortino = np.mean([risk.sortino_ratio for risk in position_risks])

            # Portfolio beta (weighted average)
            portfolio_beta = np.mean([risk.beta for risk in position_risks])

            # Correlation risk (simplified - would use correlation matrix in production)
            correlation_risk = min(1.0, len(position_risks) * 0.1)

            # Concentration risk (simplified)
            max_position_size = max(
                len(self.position_monitor.position_data.get(pid, {}).get("features", {}))
                for pid in positions
            )
            concentration_risk = min(1.0, max_position_size / 100)

            # Liquidity risk (average)
            liquidity_risk = np.mean([risk.liquidity_risk for risk in position_risks])

            # Total risk score
            total_risk_score = (
                0.3 * min(1.0, avg_volatility * 10)
                + 0.2 * min(1.0, total_var_95 / 100000)  # Normalize by portfolio value
                + 0.15 * min(1.0, max_drawdown / 10)
                + 0.15 * correlation_risk
                + 0.1 * concentration_risk
                + 0.1 * liquidity_risk
            )

            # Determine risk level
            if total_risk_score < 0.3:
                risk_level = RiskLevel.LOW
            elif total_risk_score < 0.6:
                risk_level = RiskLevel.MEDIUM
            elif total_risk_score < 0.8:
                risk_level = RiskLevel.HIGH
            else:
                risk_level = RiskLevel.CRITICAL

            # Generate recommendations
            recommendations = []
            if total_risk_score > 0.7:
                recommendations.append("Portfolio risk is high - consider reducing exposure")
            if correlation_risk > 0.6:
                recommendations.append("High correlation risk - diversify positions")
            if concentration_risk > 0.5:
                recommendations.append("High concentration risk - reduce large positions")

            portfolio_risk = RiskMetrics(
                timestamp=datetime.now(),
                position_id=None,
                symbol="PORTFOLIO",
                risk_level=risk_level,
                var_95=total_var_95,
                var_99=total_var_99,
                max_drawdown=max_drawdown,
                sharpe_ratio=portfolio_sharpe,
                sortino_ratio=portfolio_sortino,
                beta=portfolio_beta,
                volatility=avg_volatility,
                correlation_risk=correlation_risk,
                concentration_risk=concentration_risk,
                liquidity_risk=liquidity_risk,
                total_risk_score=total_risk_score,
                recommendations=recommendations,
            )

            # Store in history
            self.portfolio_risk_history.append(portfolio_risk)
            if len(self.portfolio_risk_history) > 200:
                self.portfolio_risk_history = self.portfolio_risk_history[-200:]

            return portfolio_risk

    def _create_empty_portfolio_risk(self) -> RiskMetrics:
        """Create empty portfolio risk metrics."""
        return RiskMetrics(
            timestamp=datetime.now(),
            position_id=None,
            symbol="PORTFOLIO",
            risk_level=RiskLevel.LOW,
            var_95=0.0,
            var_99=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            beta=0.0,
            volatility=0.0,
            correlation_risk=0.0,
            concentration_risk=0.0,
            liquidity_risk=0.0,
            total_risk_score=0.0,
        )

    def get_portfolio_risk_history(self, limit: int = 100) -> list[RiskMetrics]:
        """Get portfolio risk history."""
        with self._lock:
            return self.portfolio_risk_history[-limit:]


class MLRiskManager:
    """Main ML-powered risk management system."""

    def __init__(
        self,
        registry: MLModelRegistry | None = None,
        risk_limits: list[RiskLimit] | None = None,
    ):
        self.registry = registry or MLModelRegistry()
        self.risk_model_manager = RiskModelManager(registry)
        self.position_monitor = PositionRiskMonitor(self.risk_model_manager)
        self.portfolio_monitor = PortfolioRiskMonitor(self.position_monitor)

        # Risk limits
        self.risk_limits = risk_limits or self._create_default_limits()
        self.limit_violations: dict[str, list[dict[str, Any]]] = {}
        self.limit_cooldowns: dict[str, datetime] = {}

        self.logger = logging.getLogger(__name__)

    def _create_default_limits(self) -> list[RiskLimit]:
        """Create default risk limits."""
        return [
            RiskLimit(
                name="max_position_risk",
                metric_name="total_risk_score",
                threshold=0.8,
                operator="lt",
                action="reduce",
            ),
            RiskLimit(
                name="max_portfolio_var",
                metric_name="var_95",
                threshold=50000,
                operator="lt",
                action="warn",
            ),
            RiskLimit(
                name="max_drawdown",
                metric_name="max_drawdown",
                threshold=10.0,
                operator="lt",
                action="close",
            ),
            RiskLimit(
                name="min_sharpe_ratio",
                metric_name="sharpe_ratio",
                threshold=-1.0,
                operator="gt",
                action="warn",
            ),
        ]

    def add_position(
        self,
        position_id: str,
        symbol: str,
        size: float,
        entry_price: float,
        current_price: float,
        features: dict[str, float] | None = None,
        risk_model_id: str | None = None,
    ) -> RiskMetrics:
        """Add a position to risk monitoring."""
        risk_metrics = self.position_monitor.update_position(
            position_id,
            symbol,
            size,
            entry_price,
            current_price,
            features,
            risk_model_id,
        )

        # Check risk limits
        self._check_position_limits(position_id, risk_metrics)

        return risk_metrics

    def update_position(
        self,
        position_id: str,
        current_price: float,
        features: dict[str, float] | None = None,
    ) -> RiskMetrics:
        """Update existing position with new price."""
        position_data = self.position_monitor.position_data.get(position_id)
        if not position_data:
            raise ValueError(f"Position {position_id} not found")

        return self.position_monitor.update_position(
            position_id,
            position_data["symbol"],
            position_data["size"],
            position_data["entry_price"],
            current_price,
            features or position_data["features"],
            position_data["risk_model_id"],
        )

    def remove_position(self, position_id: str):
        """Remove a position from monitoring."""
        self.position_monitor.remove_position(position_id)
        self.limit_violations.pop(position_id, None)

    def get_position_risk(self, position_id: str) -> RiskMetrics | None:
        """Get current risk metrics for a position."""
        return self.position_monitor.get_position_risk(position_id)

    def get_portfolio_risk(self) -> RiskMetrics:
        """Get current portfolio risk metrics."""
        portfolio_risk = self.portfolio_monitor.calculate_portfolio_risk()

        # Check portfolio limits
        self._check_portfolio_limits(portfolio_risk)

        return portfolio_risk

    def _check_position_limits(self, position_id: str, risk_metrics: RiskMetrics):
        """Check if position violates any risk limits."""
        violations = []

        for limit in self.risk_limits:
            if not limit.enabled:
                continue

            # Check cooldown
            limit_key = f"{position_id}:{limit.name}"
            if limit_key in self.limit_cooldowns:
                if datetime.now() - self.limit_cooldowns[limit_key] < timedelta(
                    minutes=limit.cooldown_minutes
                ):
                    continue

            # Check limit violation
            metric_value = getattr(risk_metrics, limit.metric_name, None)
            if metric_value is None:
                continue

            violation = self._check_limit_violation(metric_value, limit.threshold, limit.operator)
            if violation:
                violations.append(
                    {
                        "limit_name": limit.name,
                        "metric_name": limit.metric_name,
                        "current_value": metric_value,
                        "threshold": limit.threshold,
                        "action": limit.action,
                        "timestamp": datetime.now(),
                    }
                )

                # Set cooldown
                self.limit_cooldowns[limit_key] = datetime.now()

        if violations:
            if position_id not in self.limit_violations:
                self.limit_violations[position_id] = []
            self.limit_violations[position_id].extend(violations)

            # Take action based on violations
            self._handle_risk_violations(position_id, violations)

    def _check_portfolio_limits(self, portfolio_risk: RiskMetrics):
        """Check if portfolio violates any risk limits."""
        violations = []

        for limit in self.risk_limits:
            if not limit.enabled:
                continue

            # Check cooldown
            limit_key = f"portfolio:{limit.name}"
            if limit_key in self.limit_cooldowns:
                if datetime.now() - self.limit_cooldowns[limit_key] < timedelta(
                    minutes=limit.cooldown_minutes
                ):
                    continue

            # Check limit violation
            metric_value = getattr(portfolio_risk, limit.metric_name, None)
            if metric_value is None:
                continue

            violation = self._check_limit_violation(metric_value, limit.threshold, limit.operator)
            if violation:
                violations.append(
                    {
                        "limit_name": limit.name,
                        "metric_name": limit.metric_name,
                        "current_value": metric_value,
                        "threshold": limit.threshold,
                        "action": limit.action,
                        "timestamp": datetime.now(),
                    }
                )

                # Set cooldown
                self.limit_cooldowns[limit_key] = datetime.now()

        if violations:
            if "portfolio" not in self.limit_violations:
                self.limit_violations["portfolio"] = []
            self.limit_violations["portfolio"].extend(violations)

            # Handle portfolio-level violations
            self._handle_risk_violations("portfolio", violations)

    def _check_limit_violation(self, current_value: float, threshold: float, operator: str) -> bool:
        """Check if a limit is violated."""
        if operator == "lt":
            return current_value >= threshold
        elif operator == "gt":
            return current_value <= threshold
        elif operator == "eq":
            return abs(current_value - threshold) > 1e-9
        return False

    def _handle_risk_violations(self, entity_id: str, violations: list[dict[str, Any]]):
        """Handle risk limit violations."""
        for violation in violations:
            action = violation["action"]
            limit_name = violation["limit_name"]
            current_value = violation["current_value"]
            threshold = violation["threshold"]

            self.logger.warning(
                f"Risk limit violation for {entity_id}: {limit_name} "
                f"({current_value:.4f} vs {threshold:.4f})"
            )

            if action == "warn":
                # Just log warning
                pass
            elif action == "reduce":
                # Signal position reduction (would be handled by trading system)
                self.logger.info(f"Recommendation: Reduce position size for {entity_id}")
            elif action == "close":
                # Signal position closure (would be handled by trading system)
                self.logger.warning(f"Recommendation: Close position {entity_id}")
            elif action == "stop_trading":
                # Signal trading stop (would be handled by trading system)
                self.logger.error(f"Recommendation: Stop trading for {entity_id}")

    def get_risk_summary(self) -> dict[str, Any]:
        """Get comprehensive risk summary."""
        portfolio_risk = self.portfolio_monitor.calculate_portfolio_risk()
        position_risks = {}
        for position_id in self.position_monitor.position_data:
            position_risks[position_id] = self.position_monitor.get_position_risk(position_id)

        # Count positions by risk level
        risk_level_counts = {level.value: 0 for level in RiskLevel}
        for risk in position_risks.values():
            if risk:
                risk_level_counts[risk.risk_level.value] += 1

        # Get recent violations
        recent_violations = {}
        for entity_id, violations in self.limit_violations.items():
            recent_violations[entity_id] = [
                v for v in violations if datetime.now() - v["timestamp"] < timedelta(hours=1)
            ]

        return {
            "portfolio_risk": portfolio_risk.to_dict() if portfolio_risk else None,
            "position_count": len(position_risks),
            "risk_level_distribution": risk_level_counts,
            "active_violations": recent_violations,
            "total_violations_last_hour": sum(len(v) for v in recent_violations.values()),
            "risk_model_status": {
                model_id: model_id in self.risk_model_manager.models
                for model_id in {
                    pos.get("risk_model_id")
                    for pos in self.position_monitor.position_data.values()
                    if pos.get("risk_model_id")
                }
            },
        }

    def load_risk_model(self, model_id: str) -> bool:
        """Load a risk assessment model."""
        return self.risk_model_manager.load_risk_model(model_id)

    def get_available_risk_models(self) -> list[str]:
        """Get list of available risk models."""
        return list(self.risk_model_manager.models.keys())
