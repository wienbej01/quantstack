"""Risk-aware ML policy with integrated risk management.

This module provides a risk-aware ML trading policy that integrates
advanced risk management directly into the decision-making process.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .base import (
    BaseMLPolicy,
    PolicyAction,
    PolicyDecision,
    PolicyMetrics,
    PolicySignal,
)


class RiskStrategy(Enum):
    """Risk management strategies."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    ADAPTIVE = "adaptive"


@dataclass
class RiskConfig:
    """Configuration for risk management."""

    # Position sizing risk
    max_position_size: float = 0.1  # 10% of portfolio
    max_daily_loss: float = 0.02  # 2% daily loss limit
    max_drawdown: float = 0.05  # 5% maximum drawdown

    # Stop loss and take profit
    stop_loss_atr_multiplier: float = 2.0
    take_profit_atr_multiplier: float = 3.0
    trailing_stop_enabled: bool = True
    trailing_stop_atr_multiplier: float = 1.5

    # Risk-adjusted position sizing
    kelly_criterion_enabled: bool = False
    kelly_fraction: float = 0.25  # Fraction of Kelly to use
    volatility_adjustment: bool = True
    correlation_adjustment: bool = True

    # Portfolio risk
    max_correlation: float = 0.7
    sector_concentration_limit: float = 0.3
    beta_neutral_target: float = 0.0

    # Market risk
    market_regime_adjustment: bool = True
    volatility_scaling: bool = True
    liquidity_adjustment: bool = True

    # Risk monitoring
    risk_alert_threshold: float = 0.8
    position_review_frequency: int = 100  # bars


@dataclass
class RiskMetrics:
    """Current risk metrics."""

    current_position_size: float = 0.0
    current_exposure: float = 0.0
    daily_pnl: float = 0.0
    current_drawdown: float = 0.0
    portfolio_volatility: float = 0.0
    var_95: float = 0.0
    beta: float = 0.0
    correlation_risk: float = 0.0
    liquidity_score: float = 1.0
    risk_score: float = 0.0
    last_updated: Optional[datetime] = None


@dataclass
class RiskDecision:
    """Risk-aware trading decision."""

    original_decision: PolicyDecision
    risk_adjusted_decision: PolicyDecision
    risk_assessment: Dict[str, Any]
    position_size_adjustment: float
    risk_score: float
    risk_warnings: List[str] = field(default_factory=list)


class RiskAwareMLPolicy(BaseMLPolicy):
    """Risk-aware ML trading policy with integrated risk management.

    Integrates advanced risk management directly into the decision-making process,
    providing risk-adjusted signals and position sizing.
    """

    def __init__(
        self,
        model_id: str,
        registry=None,
        feature_pipeline=None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize risk-aware ML policy.

        Args:
            model_id: ID of the ML model to use
            registry: Optional model registry
            feature_pipeline: Optional feature pipeline
            config: Policy configuration parameters
        """
        super().__init__(model_id, registry, feature_pipeline, config)

        # Risk configuration
        self.risk_config = RiskConfig(**self.config.get("risk_config", {}))
        self.risk_strategy = RiskStrategy(self.config.get("risk_strategy", "moderate"))

        # Risk metrics and state
        self.risk_metrics = RiskMetrics()
        self.risk_history: deque = deque(maxlen=1000)

        # Position tracking
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.daily_pnl_history: deque = deque(maxlen=252)  # 1 year of daily data
        self.high_water_mark: float = 0.0

        # Risk monitoring
        self.risk_alerts: List[str] = []
        self.position_review_counter = 0
        self.last_risk_assessment: Optional[datetime] = None

        # Correlation tracking
        self.returns_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.correlation_matrix: Dict[str, Dict[str, float]] = {}

        # Strategy-specific parameters
        self.strategy_params = self._get_strategy_parameters()

        self.logger = logging.getLogger(__name__)

    def generate_signal(
        self,
        features: Dict[str, float],
        current_position: float,
        market_data: pd.DataFrame,
    ) -> PolicySignal:
        """
        Generate risk-aware trading signal.

        Args:
            features: Feature dictionary
            current_position: Current position size
            market_data: Market data DataFrame

        Returns:
            Risk-adjusted trading signal
        """
        try:
            # Get base signal from ML model
            base_signal = self._generate_base_signal(
                features, current_position, market_data
            )

            # Assess current risk environment
            risk_assessment = self._assess_market_risk(features, market_data)

            # Apply risk adjustments to signal
            risk_adjusted_signal = self._apply_risk_adjustments_to_signal(
                base_signal, risk_assessment, current_position
            )

            return risk_adjusted_signal

        except Exception as e:
            self.logger.error(f"Error generating risk-aware signal: {e}")
            return PolicySignal.NEUTRAL

    def calculate_position_size(
        self,
        signal: PolicySignal,
        confidence: float,
        volatility: float,
        account_value: float,
    ) -> float:
        """
        Calculate risk-adjusted position size.

        Args:
            signal: Trading signal
            confidence: Signal confidence
            volatility: Market volatility
            account_value: Total account value

        Returns:
            Risk-adjusted position size
        """
        # Get base position size
        base_position_size = super().calculate_position_size(
            signal, confidence, volatility, account_value
        )

        # Apply risk adjustments
        risk_adjusted_size = self._apply_risk_adjustments_to_size(
            base_position_size, signal, confidence, volatility, account_value
        )

        # Ensure position size respects limits
        final_size = self._enforce_position_limits(risk_adjusted_size, account_value)

        return final_size

    def assess_decision_risk(
        self,
        decision: PolicyDecision,
        features: Dict[str, float],
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Assess risk for a trading decision.

        Args:
            decision: Trading decision to assess
            features: Feature dictionary
            portfolio: Current portfolio state

        Returns:
            Risk assessment results
        """
        risk_assessment = {
            "overall_risk_score": 0.0,
            "position_size_risk": 0.0,
            "market_risk": 0.0,
            "portfolio_risk": 0.0,
            "liquidity_risk": 0.0,
            "correlation_risk": 0.0,
            "recommendations": [],
            "warnings": [],
        }

        try:
            # Position size risk
            position_risk = self._assess_position_size_risk(decision, portfolio)
            risk_assessment["position_size_risk"] = position_risk

            # Market risk
            market_risk = self._assess_market_risk(features, None)
            risk_assessment["market_risk"] = market_risk.get("overall_score", 0.5)

            # Portfolio risk
            portfolio_risk = self._assess_portfolio_risk(decision, portfolio)
            risk_assessment["portfolio_risk"] = portfolio_risk

            # Liquidity risk
            liquidity_risk = self._assess_liquidity_risk(decision, features)
            risk_assessment["liquidity_risk"] = liquidity_risk

            # Correlation risk
            correlation_risk = self._assess_correlation_risk(decision, portfolio)
            risk_assessment["correlation_risk"] = correlation_risk

            # Calculate overall risk score
            risk_components = [
                position_risk,
                market_risk.get("overall_score", 0.5),
                portfolio_risk,
                liquidity_risk,
                correlation_risk,
            ]
            risk_assessment["overall_risk_score"] = np.mean(risk_components)

            # Generate recommendations and warnings
            risk_assessment["recommendations"] = self._generate_risk_recommendations(
                risk_assessment
            )
            risk_assessment["warnings"] = self._generate_risk_warnings(risk_assessment)

        except Exception as e:
            self.logger.error(f"Error in risk assessment: {e}")
            risk_assessment["overall_risk_score"] = 0.8  # High risk on error

        return risk_assessment

    def get_risk_metrics(self) -> RiskMetrics:
        """Get current risk metrics."""
        self._update_risk_metrics()
        return self.risk_metrics

    def update_risk_config(self, config_updates: Dict[str, Any]) -> None:
        """Update risk configuration."""
        for key, value in config_updates.items():
            if hasattr(self.risk_config, key):
                setattr(self.risk_config, key, value)
                self.logger.info(f"Updated risk config: {key} = {value}")

    def set_risk_strategy(self, strategy: RiskStrategy) -> None:
        """Set risk management strategy."""
        self.risk_strategy = strategy
        self.strategy_params = self._get_strategy_parameters()
        self.logger.info(f"Risk strategy changed to: {strategy.value}")

    def _generate_base_signal(
        self,
        features: Dict[str, float],
        current_position: float,
        market_data: pd.DataFrame,
    ) -> PolicySignal:
        """Generate base trading signal from ML model."""
        # Use parent class or ML model prediction
        # This is a simplified implementation
        if "close" in features and "vwap" in features:
            price_to_vwap = features["close"] / features["vwap"]
            if price_to_vwap > 1.015:  # 1.5% above VWAP
                return PolicySignal.BUY
            elif price_to_vwap < 0.985:  # 1.5% below VWAP
                return PolicySignal.SELL

        return PolicySignal.NEUTRAL

    def _assess_market_risk(
        self, features: Dict[str, float], market_data: Optional[pd.DataFrame]
    ) -> Dict[str, Any]:
        """Assess current market risk conditions."""
        risk_assessment = {
            "volatility_risk": 0.5,
            "trend_risk": 0.5,
            "volume_risk": 0.5,
            "overall_score": 0.5,
        }

        try:
            # Volatility risk
            if "atr_pct" in features:
                volatility = features["atr_pct"]
                if volatility > 0.03:  # 3% daily range
                    risk_assessment["volatility_risk"] = 0.8
                elif volatility > 0.02:  # 2% daily range
                    risk_assessment["volatility_risk"] = 0.6
                else:
                    risk_assessment["volatility_risk"] = 0.3

            # Trend risk (strength of trend)
            if market_data is not None and len(market_data) > 20:
                close_prices = market_data["close"].values
                returns = np.diff(close_prices) / close_prices[:-1]
                trend_strength = abs(np.mean(returns[-20:])) / np.std(returns[-20:])
                risk_assessment["trend_risk"] = min(1.0, trend_strength / 2.0)

            # Volume risk
            if "volume" in features and "avg_volume" in features:
                volume_ratio = features["volume"] / features["avg_volume"]
                if volume_ratio < 0.5:  # Low volume
                    risk_assessment["volume_risk"] = 0.7
                elif volume_ratio > 2.0:  # High volume (could be news)
                    risk_assessment["volume_risk"] = 0.6
                else:
                    risk_assessment["volume_risk"] = 0.3

            # Calculate overall score
            scores = [
                risk_assessment["volatility_risk"],
                risk_assessment["trend_risk"],
                risk_assessment["volume_risk"],
            ]
            risk_assessment["overall_score"] = np.mean(scores)

        except Exception as e:
            self.logger.error(f"Error assessing market risk: {e}")
            risk_assessment["overall_score"] = 0.7  # Moderate-high risk on error

        return risk_assessment

    def _apply_risk_adjustments_to_signal(
        self,
        signal: PolicySignal,
        risk_assessment: Dict[str, Any],
        current_position: float,
    ) -> PolicySignal:
        """Apply risk adjustments to trading signal."""
        # Convert signal to numeric strength
        signal_strength = self._signal_to_strength(signal)

        # Apply strategy-specific risk multiplier
        risk_multiplier = self.strategy_params["signal_adjustment"]

        # Adjust based on market risk
        market_risk = risk_assessment.get("overall_score", 0.5)
        if market_risk > 0.7:  # High market risk
            risk_multiplier *= 0.7
        elif market_risk > 0.5:  # Moderate market risk
            risk_multiplier *= 0.85

        # Apply position size reduction if already heavily positioned
        if abs(current_position) > self.risk_config.max_position_size * 0.8:
            risk_multiplier *= 0.6

        # Adjust signal strength
        adjusted_strength = signal_strength * risk_multiplier

        # Convert back to signal
        return self._strength_to_signal(adjusted_strength)

    def _apply_risk_adjustments_to_size(
        self,
        base_size: float,
        signal: PolicySignal,
        confidence: float,
        volatility: float,
        account_value: float,
    ) -> float:
        """Apply risk adjustments to position size."""
        adjusted_size = base_size

        # Volatility adjustment
        if self.risk_config.volatility_adjustment and volatility > 0:
            vol_factor = min(1.5, 0.01 / volatility)  # Inverse volatility scaling
            adjusted_size *= vol_factor

        # Kelly criterion adjustment
        if self.risk_config.kelly_criterion_enabled:
            kelly_fraction = self._calculate_kelly_fraction(confidence, volatility)
            adjusted_size *= kelly_fraction * self.risk_config.kelly_fraction

        # Strategy-specific adjustment
        strategy_multiplier = self.strategy_params["position_size_multiplier"]
        adjusted_size *= strategy_multiplier

        # Correlation adjustment
        if self.risk_config.correlation_adjustment:
            correlation_factor = self._calculate_correlation_adjustment()
            adjusted_size *= correlation_factor

        return adjusted_size

    def _assess_position_size_risk(
        self, decision: PolicyDecision, portfolio: Dict[str, Any]
    ) -> float:
        """Assess risk related to position size."""
        account_value = portfolio.get("total_value", 10000)
        max_size = self.risk_config.max_position_size * account_value

        # Estimate position size from decision
        estimated_size = getattr(decision, "position_size", 0.1) * account_value

        # Calculate risk score
        size_ratio = abs(estimated_size) / max_size if max_size > 0 else 1.0
        risk_score = min(1.0, size_ratio)

        return risk_score

    def _assess_portfolio_risk(
        self, decision: PolicyDecision, portfolio: Dict[str, Any]
    ) -> float:
        """Assess portfolio-level risk."""
        risk_score = 0.5

        # Current drawdown
        if self.risk_metrics.current_drawdown > self.risk_config.max_drawdown * 0.8:
            risk_score += 0.3

        # Daily loss
        if abs(self.risk_metrics.daily_pnl) > self.risk_config.max_daily_loss * 0.8:
            risk_score += 0.2

        # Portfolio concentration
        if len(self.positions) < 3:  # Low diversification
            risk_score += 0.1

        return min(1.0, risk_score)

    def _assess_liquidity_risk(
        self, decision: PolicyDecision, features: Dict[str, float]
    ) -> float:
        """Assess liquidity risk."""
        # Simplified liquidity assessment
        if "volume" in features and "avg_volume" in features:
            volume_ratio = features["volume"] / features["avg_volume"]
            if volume_ratio < 0.3:  # Very low volume
                return 0.8
            elif volume_ratio < 0.6:  # Low volume
                return 0.5
            else:
                return 0.2
        return 0.3  # Default moderate risk

    def _assess_correlation_risk(
        self, decision: PolicyDecision, portfolio: Dict[str, Any]
    ) -> float:
        """Assess correlation risk with existing positions."""
        if not self.positions:
            return 0.0  # No correlation risk with no positions

        # Simplified correlation assessment
        # In practice, this would calculate actual correlations
        position_count = len(self.positions)
        if position_count > 10:
            return 0.7  # High correlation risk with many positions
        elif position_count > 5:
            return 0.4
        else:
            return 0.2

    def _calculate_kelly_fraction(self, confidence: float, volatility: float) -> float:
        """Calculate Kelly fraction for position sizing."""
        if volatility <= 0:
            return 0.0

        # Simplified Kelly calculation
        # Kelly = (bp - q) / b where b = odds, p = win probability, q = lose probability
        win_prob = confidence
        lose_prob = 1 - confidence
        odds = 1.0 / volatility  # Simplified odds calculation

        kelly = (odds * win_prob - lose_prob) / odds
        return max(0.0, min(1.0, kelly))

    def _calculate_correlation_adjustment(self) -> float:
        """Calculate position size adjustment based on portfolio correlation."""
        # Simplified correlation adjustment
        if len(self.positions) == 0:
            return 1.0
        elif len(self.positions) < 3:
            return 0.8
        else:
            return 0.6

    def _enforce_position_limits(self, size: float, account_value: float) -> float:
        """Enforce position size limits."""
        max_size = self.risk_config.max_position_size * account_value
        return max(-max_size, min(max_size, size))

    def _generate_risk_recommendations(
        self, risk_assessment: Dict[str, Any]
    ) -> List[str]:
        """Generate risk management recommendations."""
        recommendations = []

        if risk_assessment["position_size_risk"] > 0.7:
            recommendations.append("Consider reducing position size")

        if risk_assessment["market_risk"] > 0.7:
            recommendations.append(
                "Market conditions are risky, consider reducing exposure"
            )

        if risk_assessment["portfolio_risk"] > 0.7:
            recommendations.append("Portfolio risk is high, consider risk reduction")

        if risk_assessment["liquidity_risk"] > 0.7:
            recommendations.append(
                "Liquidity risk is high, use caution with position size"
            )

        if risk_assessment["correlation_risk"] > 0.7:
            recommendations.append("High correlation risk, consider diversification")

        return recommendations

    def _generate_risk_warnings(self, risk_assessment: Dict[str, Any]) -> List[str]:
        """Generate risk warnings."""
        warnings = []

        overall_risk = risk_assessment["overall_risk_score"]
        if overall_risk > 0.8:
            warnings.append("HIGH RISK: Overall risk score is elevated")
        elif overall_risk > 0.6:
            warnings.append("MODERATE RISK: Risk levels are above normal")

        return warnings

    def _update_risk_metrics(self) -> None:
        """Update current risk metrics."""
        try:
            # Update timestamp
            self.risk_metrics.last_updated = datetime.now()

            # Calculate current exposure
            total_exposure = sum(
                abs(pos.get("size", 0)) for pos in self.positions.values()
            )
            self.risk_metrics.current_exposure = total_exposure

            # Update other metrics would go here
            # This is a simplified implementation

        except Exception as e:
            self.logger.error(f"Error updating risk metrics: {e}")

    def _get_strategy_parameters(self) -> Dict[str, float]:
        """Get parameters for current risk strategy."""
        if self.risk_strategy == RiskStrategy.CONSERVATIVE:
            return {
                "signal_adjustment": 0.6,
                "position_size_multiplier": 0.5,
                "stop_loss_multiplier": 1.5,
                "confidence_threshold": 0.8,
            }
        elif self.risk_strategy == RiskStrategy.MODERATE:
            return {
                "signal_adjustment": 0.8,
                "position_size_multiplier": 0.75,
                "stop_loss_multiplier": 2.0,
                "confidence_threshold": 0.6,
            }
        elif self.risk_strategy == RiskStrategy.AGGRESSIVE:
            return {
                "signal_adjustment": 1.0,
                "position_size_multiplier": 1.0,
                "stop_loss_multiplier": 2.5,
                "confidence_threshold": 0.4,
            }
        else:  # ADAPTIVE
            return {
                "signal_adjustment": 0.8,
                "position_size_multiplier": 0.75,
                "stop_loss_multiplier": 2.0,
                "confidence_threshold": 0.6,
            }

    def _signal_to_strength(self, signal: PolicySignal) -> float:
        """Convert policy signal to numeric strength."""
        signal_map = {
            PolicySignal.STRONG_BUY: 1.0,
            PolicySignal.BUY: 0.7,
            PolicySignal.WEAK_BUY: 0.3,
            PolicySignal.NEUTRAL: 0.0,
            PolicySignal.WEAK_SELL: -0.3,
            PolicySignal.SELL: -0.7,
            PolicySignal.STRONG_SELL: -1.0,
        }
        return signal_map.get(signal, 0.0)

    def _strength_to_signal(self, strength: float) -> PolicySignal:
        """Convert numeric strength to policy signal."""
        if strength > 0.8:
            return PolicySignal.STRONG_BUY
        elif strength > 0.4:
            return PolicySignal.BUY
        elif strength > 0.1:
            return PolicySignal.WEAK_BUY
        elif strength > -0.1:
            return PolicySignal.NEUTRAL
        elif strength > -0.4:
            return PolicySignal.WEAK_SELL
        elif strength > -0.8:
            return PolicySignal.SELL
        else:
            return PolicySignal.STRONG_SELL
