"""Base classes for ML trading policies.

This module provides the foundational abstract base class and common utilities
for all ML trading policies in the Sprint 11 framework.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from extensions.intraday_ml_features.pipeline import FeaturePipeline
from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry


class PolicyAction(Enum):
    """Trading actions for policies."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"


class PolicySignal(Enum):
    """Trading signals strength."""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    WEAK_BUY = "weak_buy"
    NEUTRAL = "neutral"
    WEAK_SELL = "weak_sell"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class PolicyDecision:
    """Decision made by a trading policy."""

    action: PolicyAction
    confidence: float  # 0.0 to 1.0
    signal_strength: float  # -1.0 to 1.0
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_buy_signal(self) -> bool:
        """Check if decision is a buy signal."""
        return self.action in [PolicyAction.BUY]

    def is_sell_signal(self) -> bool:
        """Check if decision is a sell signal."""
        return self.action in [PolicyAction.SELL]

    def is_hold_signal(self) -> bool:
        """Check if decision is a hold signal."""
        return self.action == PolicyAction.HOLD


@dataclass
class PolicyMetrics:
    """Performance metrics for a policy."""

    total_decisions: int = 0
    buy_decisions: int = 0
    sell_decisions: int = 0
    hold_decisions: int = 0
    avg_confidence: float = 0.0
    avg_signal_strength: float = 0.0
    decision_frequency: float = 0.0  # decisions per hour
    last_updated: Optional[datetime] = None

    def update(self, decision: PolicyDecision) -> None:
        """Update metrics with new decision."""
        self.total_decisions += 1
        self.last_updated = datetime.now()

        if decision.action == PolicyAction.BUY:
            self.buy_decisions += 1
        elif decision.action == PolicyAction.SELL:
            self.sell_decisions += 1
        else:
            self.hold_decisions += 1

        # Update averages
        if self.total_decisions == 1:
            self.avg_confidence = decision.confidence
            self.avg_signal_strength = decision.signal_strength
        else:
            alpha = 0.1  # Smoothing factor
            self.avg_confidence = (
                alpha * decision.confidence + (1 - alpha) * self.avg_confidence
            )
            self.avg_signal_strength = (
                alpha * decision.signal_strength
                + (1 - alpha) * self.avg_signal_strength
            )


class BaseMLPolicy(ABC):
    """Abstract base class for ML trading policies.

    Provides common functionality and interface for all ML-based trading policies
    while maintaining strict compliance with intraday trading rules.
    """

    def __init__(
        self,
        model_id: str,
        registry: Optional[MLModelRegistry] = None,
        feature_pipeline: Optional[FeaturePipeline] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize ML policy.

        Args:
            model_id: ID of the ML model to use
            registry: Optional model registry
            feature_pipeline: Optional feature pipeline
            config: Policy configuration parameters
        """
        self.model_id = model_id
        self.registry = registry or MLModelRegistry()
        self.feature_pipeline = feature_pipeline
        self.config = config or {}

        # Initialize ML predictor
        self.predictor = MLPredictor(self.registry)

        # Policy metrics
        self.metrics = PolicyMetrics()

        # State management
        self.last_decision_time: Optional[datetime] = None
        self.position_state: Dict[str, float] = {}  # symbol -> position_size
        self.signal_history: List[PolicyDecision] = []

        # Configuration parameters
        self.min_confidence_threshold = self.config.get("min_confidence_threshold", 0.6)
        self.signal_strength_threshold = self.config.get(
            "signal_strength_threshold", 0.3
        )
        self.position_size_method = self.config.get("position_size_method", "fixed")
        self.max_position_size = self.config.get("max_position_size", 1.0)
        self.risk_adjustment_enabled = self.config.get("risk_adjustment_enabled", True)

        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def generate_signal(
        self,
        features: Dict[str, float],
        current_position: float,
        market_data: pd.DataFrame,
    ) -> PolicySignal:
        """
        Generate trading signal from ML model.

        Args:
            features: Feature dictionary
            current_position: Current position size
            market_data: Market data DataFrame

        Returns:
            Trading signal
        """
        pass

    @abstractmethod
    def calculate_position_size(
        self,
        signal: PolicySignal,
        confidence: float,
        volatility: float,
        account_value: float,
    ) -> float:
        """
        Calculate position size based on signal and risk parameters.

        Args:
            signal: Trading signal
            confidence: Signal confidence
            volatility: Market volatility
            account_value: Total account value

        Returns:
            Position size (positive for long, negative for short)
        """
        pass

    def decide(self, bar: pd.Series, portfolio: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make trading decision for current bar.

        Args:
            bar: Current market bar data
            portfolio: Current portfolio state

        Returns:
            Trading decision order or None
        """
        try:
            # Extract features
            features = self._extract_features(bar, portfolio)
            if not features:
                return None

            # Get current position
            symbol = bar.get("symbol", "default")
            current_position = self.position_state.get(symbol, 0.0)

            # Get market data context
            market_data = self._get_market_data_context(bar, portfolio)

            # Generate signal
            signal = self.generate_signal(features, current_position, market_data)

            # Get model prediction and confidence
            prediction_results = self.predictor.predict(
                self.model_id, pd.DataFrame([features]), return_probabilities=True
            )
            if not prediction_results:
                return None

            prediction_result = prediction_results[0]
            prediction = (
                prediction_result.prediction[0] if prediction_result.prediction else 0.0
            )
            confidence = (
                prediction_result.prediction_probability[0]
                if prediction_result.prediction_probability
                else 0.5
            )

            # Convert prediction to signal strength
            signal_strength = self._prediction_to_signal_strength(prediction)

            # Apply risk adjustments if enabled
            if self.risk_adjustment_enabled:
                signal_strength = self._apply_risk_adjustments(
                    signal_strength, features, current_position, market_data
                )
                confidence = self._adjust_confidence(confidence, features, market_data)

            # Create policy decision
            decision = self._create_decision(
                signal, signal_strength, confidence, features
            )

            # Update metrics
            self.metrics.update(decision)
            self.last_decision_time = datetime.now()
            self.signal_history.append(decision)

            # Keep signal history manageable
            if len(self.signal_history) > 1000:
                self.signal_history = self.signal_history[-500:]

            # Convert decision to order if it meets thresholds
            if self._meets_execution_thresholds(decision):
                order = self._create_order(decision, bar, portfolio)
                return order

            return None

        except Exception as e:
            self.logger.error(f"Error in policy decision making: {e}")
            return None

    def update_position(self, symbol: str, position_size: float) -> None:
        """Update position state for a symbol."""
        self.position_state[symbol] = position_size

    def get_metrics(self) -> PolicyMetrics:
        """Get current policy metrics."""
        # Calculate decision frequency
        if self.last_decision_time and self.metrics.total_decisions > 1:
            time_diff = (datetime.now() - self.last_decision_time).total_seconds()
            if time_diff > 0:
                self.metrics.decision_frequency = self.metrics.total_decisions / (
                    time_diff / 3600.0
                )

        return self.metrics

    def reset_metrics(self) -> None:
        """Reset policy metrics."""
        self.metrics = PolicyMetrics()
        self.signal_history.clear()
        self.last_decision_time = None

    def _extract_features(
        self, bar: pd.Series, portfolio: Dict[str, Any]
    ) -> Optional[Dict[str, float]]:
        """Extract features from bar and portfolio data."""
        try:
            # Basic features from bar data
            features = {
                "open": float(bar.get("open", 0)),
                "high": float(bar.get("high", 0)),
                "low": float(bar.get("low", 0)),
                "close": float(bar.get("close", 0)),
                "volume": float(bar.get("volume", 0)),
            }

            # Add technical indicators if available
            if "vwap" in bar:
                features["vwap"] = float(bar["vwap"])
                features["price_to_vwap"] = features["close"] / features["vwap"]

            if "atr" in bar:
                features["atr"] = float(bar["atr"])
                features["atr_pct"] = features["atr"] / features["close"]

            # Add portfolio features
            if portfolio:
                features["account_value"] = float(portfolio.get("total_value", 0))
                features["cash"] = float(portfolio.get("cash", 0))
                features["leverage"] = float(portfolio.get("leverage", 0))

            # Add position state
            symbol = bar.get("symbol", "default")
            current_position = self.position_state.get(symbol, 0.0)
            features["current_position"] = current_position

            return features

        except Exception as e:
            self.logger.error(f"Error extracting features: {e}")
            return None

    def _get_market_data_context(
        self, bar: pd.Series, portfolio: Dict[str, Any]
    ) -> pd.DataFrame:
        """Get market data context for decision making."""
        # This is a simplified implementation
        # In practice, this would fetch recent market data for context
        return pd.DataFrame([bar])

    def _prediction_to_signal_strength(self, prediction: float) -> float:
        """Convert model prediction to signal strength."""
        # Normalize prediction to [-1, 1] range
        # This depends on the specific model output format
        if isinstance(prediction, (int, float)):
            # Assume prediction is already in reasonable range
            return max(-1.0, min(1.0, float(prediction)))
        else:
            return 0.0

    def _apply_risk_adjustments(
        self,
        signal_strength: float,
        features: Dict[str, float],
        current_position: float,
        market_data: pd.DataFrame,
    ) -> float:
        """Apply risk adjustments to signal strength."""
        # Adjust based on current position (position size limits)
        if abs(current_position) >= self.max_position_size:
            # Reduce signal if already at max position
            signal_strength *= 0.5

        # Adjust based on volatility if available
        if "atr_pct" in features:
            volatility = features["atr_pct"]
            # Reduce signal in high volatility environments
            if volatility > 0.02:  # 2% daily range
                signal_strength *= 0.8
            elif volatility > 0.05:  # 5% daily range
                signal_strength *= 0.6

        return max(-1.0, min(1.0, signal_strength))

    def _adjust_confidence(
        self, confidence: float, features: Dict[str, float], market_data: pd.DataFrame
    ) -> float:
        """Adjust confidence based on market conditions."""
        # Reduce confidence in high volatility
        if "atr_pct" in features:
            volatility = features["atr_pct"]
            if volatility > 0.03:  # 3% daily range
                confidence *= 0.9

        # Reduce confidence for large positions
        symbol = features.get("symbol", "default")
        current_position = self.position_state.get(symbol, 0.0)
        position_ratio = (
            abs(current_position) / self.max_position_size
            if self.max_position_size > 0
            else 0
        )

        if position_ratio > 0.8:
            confidence *= 0.8

        return max(0.0, min(1.0, confidence))

    def _create_decision(
        self,
        signal: PolicySignal,
        signal_strength: float,
        confidence: float,
        features: Dict[str, float],
    ) -> PolicyDecision:
        """Create policy decision from signal and analysis."""
        # Convert signal to action
        if signal in [PolicySignal.STRONG_BUY, PolicySignal.BUY, PolicySignal.WEAK_BUY]:
            action = PolicyAction.BUY
        elif signal in [
            PolicySignal.STRONG_SELL,
            PolicySignal.SELL,
            PolicySignal.WEAK_SELL,
        ]:
            action = PolicyAction.SELL
        else:
            action = PolicyAction.HOLD

        return PolicyDecision(
            action=action,
            confidence=confidence,
            signal_strength=signal_strength,
            metadata={
                "signal": signal.value,
                "features": features,
                "model_id": self.model_id,
            },
        )

    def _meets_execution_thresholds(self, decision: PolicyDecision) -> bool:
        """Check if decision meets execution thresholds."""
        # Check confidence threshold
        if decision.confidence < self.min_confidence_threshold:
            return False

        # Check signal strength threshold
        if abs(decision.signal_strength) < self.signal_strength_threshold:
            return False

        # Additional checks can be added here
        return True

    def _create_order(
        self, decision: PolicyDecision, bar: pd.Series, portfolio: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create order from policy decision."""
        symbol = bar.get("symbol", "default")
        current_position = self.position_state.get(symbol, 0.0)

        # Calculate position size
        volatility = float(bar.get("atr_pct", 0.01))  # Default 1% volatility
        account_value = float(portfolio.get("total_value", 10000))

        position_size = self.calculate_position_size(
            decision.metadata.get("signal", PolicySignal.NEUTRAL),
            decision.confidence,
            volatility,
            account_value,
        )

        # Create order dictionary
        order = {
            "symbol": symbol,
            "action": decision.action.value,
            "quantity": abs(position_size),
            "order_type": "market",
            "timestamp": datetime.now(),
            "price": float(bar.get("close", 0)),
            "confidence": decision.confidence,
            "signal_strength": decision.signal_strength,
            "metadata": decision.metadata,
        }

        return order

    def get_signal_history(self, limit: int = 100) -> List[PolicyDecision]:
        """Get recent signal history."""
        return self.signal_history[-limit:] if self.signal_history else []

    def get_position_state(self) -> Dict[str, float]:
        """Get current position state."""
        return self.position_state.copy()
