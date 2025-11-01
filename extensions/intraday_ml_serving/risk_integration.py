"""Risk-aware ML serving integration."""

import logging
import queue
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

import numpy as np

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_risk.ml_risk_manager import (
    MLRiskManager,
    RiskLevel,
    RiskMetrics,
)


@dataclass
class RiskAwareConfig:
    """Configuration for risk-aware serving."""

    enable_risk_filtering: bool = True
    max_risk_score: float = 0.7
    risk_adjustment_factor: float = 0.5
    position_size_adjustment: bool = True
    portfolio_consideration: bool = True
    risk_monitoring_interval: int = 60  # seconds
    alert_on_high_risk: bool = True


@dataclass
class RiskAwarePrediction:
    """Risk-aware prediction result."""

    prediction: float
    original_prediction: float
    confidence: float
    risk_metrics: RiskMetrics
    risk_adjusted_prediction: float
    position_size_multiplier: float
    risk_level: RiskLevel
    prediction_allowed: bool
    risk_reasons: list[str]


class RiskAwareServing:
    """Risk-aware ML serving that integrates with risk management."""

    def __init__(
        self,
        model_predictor: MLPredictor,
        risk_manager: MLRiskManager,
        config: RiskAwareConfig | None = None,
    ):
        """
        Initialize risk-aware serving.

        Args:
            model_predictor: ML model predictor
            risk_manager: Risk manager instance
            config: Risk-aware configuration
        """
        self.predictor = model_predictor
        self.risk_manager = risk_manager
        self.config = config or RiskAwareConfig()
        self.logger = logging.getLogger(__name__)
        self._lock = Lock()

        # Risk monitoring
        self.risk_history = queue.Queue(maxsize=1000)
        self.prediction_count = 0
        self.blocked_predictions = 0

    def predict_with_risk(
        self, features: dict[str, float], position_size: float | None = None
    ) -> RiskAwarePrediction:
        """
        Make prediction with risk assessment.

        Args:
            features: Feature dictionary
            position_size: Optional position size for risk calculation

        Returns:
            Risk-aware prediction result
        """
        with self._lock:
            self.prediction_count += 1

        # Get original prediction
        original_result = self.predictor.predict(features)
        original_prediction = float(original_result.prediction)
        confidence = (
            float(original_result.prediction_probability)
            if hasattr(original_result, "prediction_probability")
            else 0.5
        )

        # Get risk assessment
        risk_metrics = self.assess_prediction_risk(
            features, original_prediction, position_size
        )

        # Apply risk adjustments
        risk_adjusted_prediction = self.apply_risk_adjustment(
            original_prediction, risk_metrics
        )
        position_size_multiplier = self.calculate_position_size_multiplier(risk_metrics)

        # Check if prediction is allowed
        prediction_allowed, risk_reasons = self.check_prediction_allowed(risk_metrics)

        # Create result
        result = RiskAwarePrediction(
            prediction=risk_adjusted_prediction if prediction_allowed else 0.0,
            original_prediction=original_prediction,
            confidence=confidence,
            risk_metrics=risk_metrics,
            risk_adjusted_prediction=risk_adjusted_prediction,
            position_size_multiplier=position_size_multiplier,
            risk_level=risk_metrics.risk_level,
            prediction_allowed=prediction_allowed,
            risk_reasons=risk_reasons,
        )

        # Log and monitor
        self.log_prediction_result(result)
        self.update_risk_monitoring(result)

        return result

    def assess_prediction_risk(
        self,
        features: dict[str, float],
        prediction: float,
        position_size: float | None = None,
    ) -> RiskMetrics:
        """Assess risk for a prediction."""
        try:
            # Create a temporary position for risk assessment
            if position_size is None:
                position_size = 100.0  # Default position size

            # Mock position for risk calculation
            position_id = f"risk_assessment_{int(time.time())}"
            symbol = features.get("symbol", "UNKNOWN")
            entry_price = features.get("current_price", 100.0)
            current_price = entry_price

            # Add position to risk manager
            risk_metrics = self.risk_manager.add_position(
                position_id=position_id,
                symbol=symbol,
                size=position_size,
                entry_price=entry_price,
                current_price=current_price,
            )

            # Adjust risk based on prediction characteristics
            risk_metrics = self.adjust_risk_for_prediction(
                risk_metrics, prediction, features
            )

            # Clean up temporary position
            self.risk_manager.remove_position(position_id)

            return risk_metrics

        except Exception as e:
            self.logger.error(f"Risk assessment failed: {e}")
            # Return conservative risk metrics
            return RiskMetrics(
                position_id="error",
                symbol="UNKNOWN",
                risk_score=0.8,
                risk_level=RiskLevel.HIGH,
                position_size=0.0,
                max_position_size=0.0,
                recommended_position_size=0.0,
                stop_loss_price=0.0,
                take_profit_price=0.0,
                risk_reward_ratio=0.0,
                portfolio_heat=0.0,
                correlation_risk=0.0,
                volatility_risk=0.0,
                liquidity_risk=0.0,
                total_exposure=0.0,
                exposure_limit=1000.0,
                margin_requirement=0.0,
                value_at_risk_1d=0.0,
                expected_shortfall_1d=0.0,
                maximum_drawdown=0.0,
                time_in_position=timedelta(0),
                last_updated=datetime.now(),
            )

    def adjust_risk_for_prediction(
        self, risk_metrics: RiskMetrics, prediction: float, features: dict[str, float]
    ) -> RiskMetrics:
        """Adjust risk metrics based on prediction characteristics."""
        # Increase risk for extreme predictions
        prediction_magnitude = abs(prediction)
        if prediction_magnitude > 2.0:
            risk_metrics.risk_score = min(risk_metrics.risk_score * 1.2, 1.0)
        elif prediction_magnitude < 0.1:
            risk_metrics.risk_score = max(risk_metrics.risk_score * 0.9, 0.0)

        # Adjust for volatility
        volatility = features.get("volatility", 0.1)
        if volatility > 0.3:  # High volatility
            risk_metrics.risk_score = min(risk_metrics.risk_score * 1.1, 1.0)

        # Adjust for liquidity
        liquidity_score = features.get("liquidity_score", 0.5)
        if liquidity_score < 0.3:  # Low liquidity
            risk_metrics.risk_score = min(risk_metrics.risk_score * 1.15, 1.0)

        # Update risk level based on adjusted score
        if risk_metrics.risk_score < 0.3:
            risk_metrics.risk_level = RiskLevel.LOW
        elif risk_metrics.risk_score < 0.6:
            risk_metrics.risk_level = RiskLevel.MEDIUM
        elif risk_metrics.risk_score < 0.8:
            risk_metrics.risk_level = RiskLevel.HIGH
        else:
            risk_metrics.risk_level = RiskLevel.CRITICAL

        return risk_metrics

    def apply_risk_adjustment(
        self, prediction: float, risk_metrics: RiskMetrics
    ) -> float:
        """Apply risk-based adjustment to prediction."""
        if not self.config.enable_risk_filtering:
            return prediction

        # Adjust prediction based on risk level
        risk_factor = 1.0 - (
            risk_metrics.risk_score * self.config.risk_adjustment_factor
        )
        risk_factor = max(risk_factor, 0.1)  # Don't reduce to zero

        return prediction * risk_factor

    def calculate_position_size_multiplier(self, risk_metrics: RiskMetrics) -> float:
        """Calculate position size multiplier based on risk."""
        if not self.config.position_size_adjustment:
            return 1.0

        # Base multiplier on risk score
        if risk_metrics.risk_score < 0.3:
            return 1.0  # Full size for low risk
        elif risk_metrics.risk_score < 0.6:
            return 0.75  # Reduce by 25% for medium risk
        elif risk_metrics.risk_score < 0.8:
            return 0.5  # Reduce by 50% for high risk
        else:
            return 0.1  # Minimal size for critical risk

    def check_prediction_allowed(
        self, risk_metrics: RiskMetrics
    ) -> tuple[bool, list[str]]:
        """Check if prediction is allowed based on risk."""
        if not self.config.enable_risk_filtering:
            return True, []

        reasons = []

        # Check risk score threshold
        if risk_metrics.risk_score > self.config.max_risk_score:
            reasons.append(
                f"Risk score {risk_metrics.risk_score:.2f} exceeds threshold {self.config.max_risk_score}"
            )

        # Check portfolio heat
        if self.config.portfolio_consideration and risk_metrics.portfolio_heat > 0.8:
            reasons.append(f"Portfolio heat {risk_metrics.portfolio_heat:.2f} too high")

        # Check exposure limits
        if risk_metrics.total_exposure > risk_metrics.exposure_limit:
            reasons.append(
                f"Exposure {risk_metrics.total_exposure:.2f} exceeds limit {risk_metrics.exposure_limit:.2f}"
            )

        # Check correlation risk
        if risk_metrics.correlation_risk > 0.7:
            reasons.append(
                f"Correlation risk {risk_metrics.correlation_risk:.2f} too high"
            )

        # Check liquidity risk
        if risk_metrics.liquidity_risk > 0.8:
            reasons.append(f"Liquidity risk {risk_metrics.liquidity_risk:.2f} too high")

        # Check critical risk level
        if risk_metrics.risk_level == RiskLevel.CRITICAL:
            reasons.append("Critical risk level detected")

        allowed = len(reasons) == 0
        return allowed, reasons

    def log_prediction_result(self, result: RiskAwarePrediction):
        """Log prediction result."""
        if result.prediction_allowed:
            self.logger.info(
                f"Prediction allowed: {result.prediction:.3f} (orig: {result.original_prediction:.3f}) "
                f"Risk: {result.risk_metrics.risk_score:.2f} ({result.risk_level.value})"
            )
        else:
            self.logger.warning(
                f"Prediction blocked: {result.original_prediction:.3f} "
                f"Risk: {result.risk_metrics.risk_score:.2f} Reasons: {result.risk_reasons}"
            )

    def update_risk_monitoring(self, result: RiskAwarePrediction):
        """Update risk monitoring metrics."""
        try:
            # Add to risk history
            self.risk_history.put(
                {
                    "timestamp": datetime.now(),
                    "risk_score": result.risk_metrics.risk_score,
                    "risk_level": result.risk_level.value,
                    "prediction_allowed": result.prediction_allowed,
                    "original_prediction": result.original_prediction,
                    "adjusted_prediction": result.prediction,
                }
            )

            # Update counters
            if not result.prediction_allowed:
                self.blocked_predictions += 1

            # Alert on high risk
            if self.config.alert_on_high_risk and result.risk_level in [
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            ]:
                self.send_risk_alert(result)

        except Exception as e:
            self.logger.error(f"Risk monitoring update failed: {e}")

    def send_risk_alert(self, result: RiskAwarePrediction):
        """Send risk alert for high-risk predictions."""
        try:
            alert_message = (
                f"HIGH RISK ALERT: Prediction {result.original_prediction:.3f} "
                f"with risk score {result.risk_metrics.risk_score:.2f} ({result.risk_level.value}) "
                f"Reasons: {result.risk_reasons}"
            )
            self.logger.warning(alert_message)

            # Here you could integrate with external alerting systems
            # e.g., send to Slack, email, PagerDuty, etc.

        except Exception as e:
            self.logger.error(f"Failed to send risk alert: {e}")

    def get_risk_statistics(self) -> dict[str, Any]:
        """Get risk statistics for monitoring."""
        total_predictions = self.prediction_count
        blocked_predictions = self.blocked_predictions
        block_rate = blocked_predictions / max(total_predictions, 1)

        # Calculate average risk score from recent history
        recent_risk_scores = []
        while not self.risk_history.empty() and len(recent_risk_scores) < 100:
            try:
                item = self.risk_history.get_nowait()
                recent_risk_scores.append(item["risk_score"])
                # Put it back for others
                self.risk_history.put(item)
            except queue.Empty:
                break

        avg_risk_score = np.mean(recent_risk_scores) if recent_risk_scores else 0.0

        return {
            "total_predictions": total_predictions,
            "blocked_predictions": blocked_predictions,
            "block_rate": block_rate,
            "average_risk_score": avg_risk_score,
            "risk_filtering_enabled": self.config.enable_risk_filtering,
            "max_risk_threshold": self.config.max_risk_score,
        }

    def update_config(self, new_config: RiskAwareConfig):
        """Update risk-aware configuration."""
        with self._lock:
            self.config = new_config
            self.logger.info(
                f"Updated risk-aware config: max_risk_score={new_config.max_risk_score}"
            )

    def get_portfolio_risk_overview(self) -> dict[str, Any]:
        """Get portfolio risk overview."""
        try:
            portfolio_metrics = self.risk_manager.get_portfolio_metrics()

            return {
                "total_positions": portfolio_metrics.get("total_positions", 0),
                "total_exposure": portfolio_metrics.get("total_exposure", 0.0),
                "portfolio_heat": portfolio_metrics.get("portfolio_heat", 0.0),
                "average_risk_score": portfolio_metrics.get("average_risk_score", 0.0),
                "high_risk_positions": portfolio_metrics.get("high_risk_positions", 0),
                "value_at_risk_1d": portfolio_metrics.get("value_at_risk_1d", 0.0),
                "expected_shortfall_1d": portfolio_metrics.get(
                    "expected_shortfall_1d", 0.0
                ),
            }
        except Exception as e:
            self.logger.error(f"Failed to get portfolio risk overview: {e}")
            return {
                "total_positions": 0,
                "total_exposure": 0.0,
                "portfolio_heat": 0.0,
                "average_risk_score": 0.0,
                "high_risk_positions": 0,
                "value_at_risk_1d": 0.0,
                "expected_shortfall_1d": 0.0,
            }
