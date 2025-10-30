"""Adaptive ML policy with market regime detection.

This module provides an adaptive ML trading policy that adjusts its behavior
based on detected market regimes and changing conditions.
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


class MarketRegime(Enum):
    """Market regime types."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    SIDEWAYS = "sideways"
    VOLATILE = "volatile"
    QUIET = "quiet"


@dataclass
class RegimeConfig:
    """Configuration for market regime detection."""

    # Trend detection parameters
    trend_lookback_periods: List[int] = field(default_factory=lambda: [10, 20, 50])
    trend_threshold: float = 0.02  # 2% threshold for trend detection
    volatility_threshold: float = 0.015  # 1.5% volatility threshold
    volume_multiplier: float = 1.2  # Volume spike threshold

    # Regime stability parameters
    min_regime_duration_bars: int = 20
    regime_confirmation_periods: int = 3
    regime_detection_method: str = (
        "combined"  # "trend", "volatility", "volume", "combined"
    )

    # Adaptive parameters
    enable_regime_memory: bool = True
    regime_memory_decay: float = 0.95
    min_confidence_for_regime_switch: float = 0.7


@dataclass
class RegimeState:
    """Current market regime state."""

    current_regime: MarketRegime
    confidence: float
    duration_bars: int
    last_change_time: datetime
    historical_regimes: deque = field(default_factory=lambda: deque(maxlen=100))
    regime_probabilities: Dict[MarketRegime, float] = field(default_factory=dict)


class AdaptiveMLPolicy(BaseMLPolicy):
    """Adaptive ML trading policy with market regime detection.

    Adjusts trading behavior based on detected market regimes and provides
    regime-specific signal processing and risk management.
    """

    def __init__(
        self,
        model_id: str,
        registry=None,
        feature_pipeline=None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize adaptive ML policy.

        Args:
            model_id: ID of the ML model to use
            registry: Optional model registry
            feature_pipeline: Optional feature pipeline
            config: Policy configuration parameters
        """
        super().__init__(model_id, registry, feature_pipeline, config)

        # Regime detection configuration
        self.regime_config = RegimeConfig(**self.config.get("regime_config", {}))

        # Regime state
        self.regime_state = RegimeState(
            current_regime=MarketRegime.SIDEWAYS,
            confidence=0.5,
            duration_bars=0,
            last_change_time=datetime.now(),
        )

        # Regime-specific parameters
        self.regime_parameters = {
            MarketRegime.TRENDING_UP: {
                "signal_multiplier": 1.2,
                "confidence_threshold": 0.5,
                "position_size_multiplier": 1.1,
                "stop_loss_multiplier": 1.5,
                "take_profit_multiplier": 2.0,
            },
            MarketRegime.TRENDING_DOWN: {
                "signal_multiplier": 1.3,
                "confidence_threshold": 0.6,
                "position_size_multiplier": 0.9,
                "stop_loss_multiplier": 1.3,
                "take_profit_multiplier": 1.8,
            },
            MarketRegime.SIDEWAYS: {
                "signal_multiplier": 0.8,
                "confidence_threshold": 0.7,
                "position_size_multiplier": 0.7,
                "stop_loss_multiplier": 1.0,
                "take_profit_multiplier": 1.2,
            },
            MarketRegime.VOLATILE: {
                "signal_multiplier": 0.6,
                "confidence_threshold": 0.8,
                "position_size_multiplier": 0.5,
                "stop_loss_multiplier": 0.8,
                "take_profit_multiplier": 1.5,
            },
            MarketRegime.QUIET: {
                "signal_multiplier": 0.9,
                "confidence_threshold": 0.6,
                "position_size_multiplier": 0.8,
                "stop_loss_multiplier": 1.2,
                "take_profit_multiplier": 1.3,
            },
        }

        # Market data history for regime detection
        self.price_history: deque = deque(maxlen=200)
        self.volume_history: deque = deque(maxlen=200)
        self.volatility_history: deque = deque(maxlen=50)

        # Regime detection metrics
        self.regime_detection_accuracy = 0.5
        self.regime_switch_count = 0
        self.last_regime_detection: Optional[datetime] = None

        self.logger = logging.getLogger(__name__)

    def generate_signal(
        self,
        features: Dict[str, float],
        current_position: float,
        market_data: pd.DataFrame,
    ) -> PolicySignal:
        """
        Generate adaptive trading signal based on current market regime.

        Args:
            features: Feature dictionary
            current_position: Current position size
            market_data: Market data DataFrame

        Returns:
            Adaptive trading signal
        """
        # Detect current market regime
        self._update_market_regime(market_data)

        # Get base signal from parent class or ML model
        base_signal = self._generate_base_signal(
            features, current_position, market_data
        )

        # Apply regime-specific adjustments
        adjusted_signal = self._apply_regime_adjustments(
            base_signal, features, current_position
        )

        return adjusted_signal

    def calculate_position_size(
        self,
        signal: PolicySignal,
        confidence: float,
        volatility: float,
        account_value: float,
    ) -> float:
        """
        Calculate position size with regime-specific adjustments.

        Args:
            signal: Trading signal
            confidence: Signal confidence
            volatility: Market volatility
            account_value: Total account value

        Returns:
            Adjusted position size
        """
        # Get base position size
        base_position_size = super().calculate_position_size(
            signal, confidence, volatility, account_value
        )

        # Apply regime-specific multiplier
        regime_params = self.regime_parameters[self.regime_state.current_regime]
        position_multiplier = regime_params["position_size_multiplier"]

        # Additional adjustments based on regime stability
        if (
            self.regime_state.duration_bars
            < self.regime_config.min_regime_duration_bars
        ):
            # Reduce position size during regime transitions
            position_multiplier *= 0.7

        # Adjust based on regime confidence
        confidence_adjustment = 0.5 + 0.5 * self.regime_state.confidence
        position_multiplier *= confidence_adjustment

        return base_position_size * position_multiplier

    def detect_regime(self, market_data: pd.DataFrame) -> MarketRegime:
        """
        Detect current market regime from market data.

        Args:
            market_data: Market data DataFrame

        Returns:
            Detected market regime
        """
        if len(market_data) < max(self.regime_config.trend_lookback_periods):
            return MarketRegime.SIDEWAYS

        # Calculate various regime indicators
        trend_signal = self._calculate_trend_signal(market_data)
        volatility_signal = self._calculate_volatility_signal(market_data)
        volume_signal = self._calculate_volume_signal(market_data)

        # Combine signals based on detection method
        if self.regime_config.regime_detection_method == "trend":
            return self._regime_from_trend_signal(trend_signal)
        elif self.regime_config.regime_detection_method == "volatility":
            return self._regime_from_volatility_signal(volatility_signal)
        elif self.regime_config.regime_detection_method == "volume":
            return self._regime_from_volume_signal(volume_signal)
        else:  # combined
            return self._regime_from_combined_signals(
                trend_signal, volatility_signal, volume_signal
            )

    def get_regime_state(self) -> RegimeState:
        """Get current regime state."""
        return self.regime_state

    def get_regime_parameters(self, regime: MarketRegime) -> Dict[str, float]:
        """Get parameters for a specific regime."""
        return self.regime_parameters.get(regime, {}).copy()

    def update_regime_parameters(
        self, regime: MarketRegime, parameters: Dict[str, float]
    ) -> None:
        """Update parameters for a specific regime."""
        if regime in self.regime_parameters:
            self.regime_parameters[regime].update(parameters)
            self.logger.info(f"Updated parameters for regime {regime.value}")

    def _update_market_regime(self, market_data: pd.DataFrame) -> None:
        """Update the current market regime detection."""
        try:
            # Detect new regime
            new_regime = self.detect_regime(market_data)
            confidence = self._calculate_regime_confidence(market_data, new_regime)

            # Check if regime change is warranted
            if (
                new_regime != self.regime_state.current_regime
                and confidence >= self.regime_config.min_confidence_for_regime_switch
                and self.regime_state.duration_bars
                >= self.regime_config.min_regime_duration_bars
            ):

                # Record regime change
                self._record_regime_change(new_regime, confidence)

            # Update regime duration
            if new_regime == self.regime_state.current_regime:
                self.regime_state.duration_bars += 1
            else:
                self.regime_state.duration_bars = 1

            # Update regime probabilities
            self._update_regime_probabilities(market_data)

            self.last_regime_detection = datetime.now()

        except Exception as e:
            self.logger.error(f"Error updating market regime: {e}")

    def _generate_base_signal(
        self,
        features: Dict[str, float],
        current_position: float,
        market_data: pd.DataFrame,
    ) -> PolicySignal:
        """Generate base trading signal."""
        # Use parent class implementation or ML model prediction
        # This is a simplified implementation
        if "close" in features and "vwap" in features:
            price_to_vwap = features["close"] / features["vwap"]
            if price_to_vwap > 1.02:  # 2% above VWAP
                return PolicySignal.BUY
            elif price_to_vwap < 0.98:  # 2% below VWAP
                return PolicySignal.SELL

        return PolicySignal.NEUTRAL

    def _apply_regime_adjustments(
        self,
        base_signal: PolicySignal,
        features: Dict[str, float],
        current_position: float,
    ) -> PolicySignal:
        """Apply regime-specific adjustments to signal."""
        regime_params = self.regime_parameters[self.regime_state.current_regime]
        signal_multiplier = regime_params["signal_multiplier"]

        # Convert signal to numeric strength for adjustment
        signal_strength = self._signal_to_strength(base_signal)
        adjusted_strength = signal_strength * signal_multiplier

        # Convert back to signal
        return self._strength_to_signal(adjusted_strength)

    def _calculate_trend_signal(self, market_data: pd.DataFrame) -> float:
        """Calculate trend signal from market data."""
        if len(market_data) < 2:
            return 0.0

        # Calculate returns for different lookback periods
        trend_signals = []
        close_prices = market_data["close"].values

        for period in self.regime_config.trend_lookback_periods:
            if len(close_prices) >= period:
                current_price = close_prices[-1]
                past_price = close_prices[-period]
                return_pct = (current_price - past_price) / past_price
                trend_signals.append(return_pct)

        if trend_signals:
            # Weight recent trends more heavily
            weights = np.array([i + 1 for i in range(len(trend_signals))])
            weights = weights / weights.sum()
            return np.average(trend_signals, weights=weights)

        return 0.0

    def _calculate_volatility_signal(self, market_data: pd.DataFrame) -> float:
        """Calculate volatility signal from market data."""
        if len(market_data) < 20:
            return 0.0

        close_prices = market_data["close"].values
        returns = np.diff(close_prices) / close_prices[:-1]

        # Calculate rolling volatility
        volatility = np.std(returns[-20:]) if len(returns) >= 20 else 0.0

        # Compare to threshold
        if volatility > self.regime_config.volatility_threshold * 2:
            return 2.0  # High volatility
        elif volatility > self.regime_config.volatility_threshold:
            return 1.0  # Moderate volatility
        else:
            return 0.0  # Low volatility

    def _calculate_volume_signal(self, market_data: pd.DataFrame) -> float:
        """Calculate volume signal from market data."""
        if "volume" not in market_data.columns or len(market_data) < 20:
            return 0.0

        volumes = market_data["volume"].values
        recent_volume = volumes[-1]
        avg_volume = (
            np.mean(volumes[-20:-1]) if len(volumes) >= 21 else np.mean(volumes)
        )

        if avg_volume > 0:
            volume_ratio = recent_volume / avg_volume
            if volume_ratio > self.regime_config.volume_multiplier:
                return 1.0  # High volume
            else:
                return 0.0  # Normal volume

        return 0.0

    def _regime_from_trend_signal(self, trend_signal: float) -> MarketRegime:
        """Determine regime from trend signal."""
        if trend_signal > self.regime_config.trend_threshold:
            return MarketRegime.TRENDING_UP
        elif trend_signal < -self.regime_config.trend_threshold:
            return MarketRegime.TRENDING_DOWN
        else:
            return MarketRegime.SIDEWAYS

    def _regime_from_volatility_signal(self, volatility_signal: float) -> MarketRegime:
        """Determine regime from volatility signal."""
        if volatility_signal > 1.5:
            return MarketRegime.VOLATILE
        elif volatility_signal < 0.5:
            return MarketRegime.QUIET
        else:
            return MarketRegime.SIDEWAYS

    def _regime_from_volume_signal(self, volume_signal: float) -> MarketRegime:
        """Determine regime from volume signal."""
        if volume_signal > 0.5:
            return MarketRegime.VOLATILE
        else:
            return MarketRegime.QUIET

    def _regime_from_combined_signals(
        self, trend_signal: float, volatility_signal: float, volume_signal: float
    ) -> MarketRegime:
        """Determine regime from combined signals."""
        # Priority: trend > volatility > volume
        if abs(trend_signal) > self.regime_config.trend_threshold:
            return self._regime_from_trend_signal(trend_signal)
        elif volatility_signal > 1.0:
            return MarketRegime.VOLATILE
        elif volatility_signal < 0.5 and volume_signal < 0.5:
            return MarketRegime.QUIET
        else:
            return MarketRegime.SIDEWAYS

    def _calculate_regime_confidence(
        self, market_data: pd.DataFrame, regime: MarketRegime
    ) -> float:
        """Calculate confidence in regime detection."""
        # Base confidence on signal strength and consistency
        trend_signal = self._calculate_trend_signal(market_data)
        volatility_signal = self._calculate_volatility_signal(market_data)

        if regime == MarketRegime.TRENDING_UP:
            confidence = min(
                1.0, abs(trend_signal) / self.regime_config.trend_threshold
            )
        elif regime == MarketRegime.TRENDING_DOWN:
            confidence = min(
                1.0, abs(trend_signal) / self.regime_config.trend_threshold
            )
        elif regime == MarketRegime.VOLATILE:
            confidence = min(1.0, volatility_signal / 2.0)
        else:
            confidence = 0.5  # Default confidence

        # Boost confidence if regime has been stable
        if (
            self.regime_state.duration_bars
            > self.regime_config.min_regime_duration_bars
        ):
            confidence = min(1.0, confidence * 1.2)

        return confidence

    def _record_regime_change(
        self, new_regime: MarketRegime, confidence: float
    ) -> None:
        """Record a regime change."""
        # Store old regime in history
        self.regime_state.historical_regimes.append(
            {
                "regime": self.regime_state.current_regime,
                "duration_bars": self.regime_state.duration_bars,
                "change_time": self.regime_state.last_change_time,
                "confidence": self.regime_state.confidence,
            }
        )

        # Update current regime
        self.regime_state.current_regime = new_regime
        self.regime_state.confidence = confidence
        self.regime_state.duration_bars = 1
        self.regime_state.last_change_time = datetime.now()

        self.regime_switch_count += 1

        self.logger.info(
            f"Regime changed to {new_regime.value} with confidence {confidence:.2f}"
        )

    def _update_regime_probabilities(self, market_data: pd.DataFrame) -> None:
        """Update regime probability distribution."""
        # Calculate probabilities for each regime
        trend_signal = self._calculate_trend_signal(market_data)
        volatility_signal = self._calculate_volatility_signal(market_data)

        probabilities = {}
        for regime in MarketRegime:
            if regime == MarketRegime.TRENDING_UP:
                prob = max(0, trend_signal / self.regime_config.trend_threshold)
            elif regime == MarketRegime.TRENDING_DOWN:
                prob = max(0, -trend_signal / self.regime_config.trend_threshold)
            elif regime == MarketRegime.VOLATILE:
                prob = min(1.0, volatility_signal / 2.0)
            else:
                prob = 0.2  # Base probability for other regimes

            probabilities[regime] = prob

        # Normalize probabilities
        total_prob = sum(probabilities.values())
        if total_prob > 0:
            probabilities = {
                regime: prob / total_prob for regime, prob in probabilities.items()
            }

        # Apply memory decay
        if self.regime_config.enable_regime_memory:
            for regime in probabilities:
                old_prob = self.regime_state.regime_probabilities.get(regime, 0.2)
                probabilities[regime] = (
                    self.regime_config.regime_memory_decay * old_prob
                    + (1 - self.regime_config.regime_memory_decay)
                    * probabilities[regime]
                )

        self.regime_state.regime_probabilities = probabilities

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
