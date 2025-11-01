"""ML-powered position sizing for intraday trading."""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry


class SizingMethod(Enum):
    """Position sizing methods."""

    FIXED = "fixed"
    VOLATILITY = "volatility"
    KELLY = "kelly"
    RISK_PARITY = "risk_parity"
    ML_BASED = "ml_based"


@dataclass
class PositionSize:
    """Position size information."""

    symbol: str
    size: float
    max_size: float
    risk_adjusted_size: float
    sizing_method: SizingMethod
    confidence: float
    reasons: list[str]


class MLPositionSizer:
    """ML-powered position sizer for intraday trading."""

    def __init__(
        self,
        max_position_size: float = 1000.0,
        risk_tolerance: float = 0.02,
        sizing_method: SizingMethod = SizingMethod.VOLATILITY,
        ml_model_id: str | None = None,
        registry: MLModelRegistry | None = None,
    ):
        """
        Initialize ML position sizer.

        Args:
            max_position_size: Maximum position size in dollars
            risk_tolerance: Risk tolerance as fraction of portfolio
            sizing_method: Method for position sizing
            ml_model_id: ML model ID for ML-based sizing
            registry: Model registry instance
        """
        self.max_position_size = max_position_size
        self.risk_tolerance = risk_tolerance
        self.sizing_method = sizing_method
        self.registry = registry or MLModelRegistry()
        self.logger = logging.getLogger(__name__)

        # Load ML model if specified
        self.ml_predictor = None
        if ml_model_id and sizing_method == SizingMethod.ML_BASED:
            try:
                self.ml_predictor = MLPredictor(ml_model_id, self.registry)
                self.logger.info(f"Loaded ML model for position sizing: {ml_model_id}")
            except Exception as e:
                self.logger.error(f"Failed to load ML model {ml_model_id}: {e}")

    def calculate_position_size(
        self,
        symbol: str,
        signal_strength: float,
        volatility: float,
        account_size: float,
        current_price: float,
        confidence: float = 0.5,
        additional_features: dict[str, float] | None = None,
    ) -> PositionSize:
        """
        Calculate position size for a trade.

        Args:
            symbol: Trading symbol
            signal_strength: Signal strength (-1 to 1)
            volatility: Volatility estimate
            account_size: Total account size
            current_price: Current price
            confidence: Confidence in signal
            additional_features: Additional features for ML model

        Returns:
            Position size information
        """
        additional_features = additional_features or {}

        if self.sizing_method == SizingMethod.FIXED:
            size = self._fixed_sizing(signal_strength)
        elif self.sizing_method == SizingMethod.VOLATILITY:
            size = self._volatility_sizing(signal_strength, volatility)
        elif self.sizing_method == SizingMethod.KELLY:
            size = self._kelly_sizing(signal_strength, confidence, volatility)
        elif self.sizing_method == SizingMethod.RISK_PARITY:
            size = self._risk_parity_sizing(signal_strength, volatility, account_size)
        elif self.sizing_method == SizingMethod.ML_BASED:
            size = self._ml_based_sizing(
                symbol, signal_strength, volatility, confidence, additional_features
            )
        else:
            raise ValueError(f"Unknown sizing method: {self.sizing_method}")

        # Apply maximum size limit
        max_allowed_size = min(
            self.max_position_size, account_size * self.risk_tolerance
        )
        final_size = min(size, max_allowed_size)

        return PositionSize(
            symbol=symbol,
            size=final_size,
            max_size=max_allowed_size,
            risk_adjusted_size=final_size,
            sizing_method=self.sizing_method,
            confidence=confidence,
            reasons=self._get_sizing_reasons(final_size, size, max_allowed_size),
        )

    def _fixed_sizing(self, signal_strength: float) -> float:
        """Fixed position sizing based on signal strength."""
        base_size = self.max_position_size * 0.5
        return base_size * abs(signal_strength)

    def _volatility_sizing(self, signal_strength: float, volatility: float) -> float:
        """Volatility-based position sizing."""
        # Inverse relationship with volatility
        volatility = max(volatility, 0.01)  # Minimum volatility

        volatility_target = 0.02  # 2% daily volatility target
        size = (
            self.max_position_size
            * (volatility_target / volatility)
            * abs(signal_strength)
        )
        return size

    def _kelly_sizing(
        self, signal_strength: float, confidence: float, volatility: float
    ) -> float:
        """Kelly criterion position sizing."""
        # Estimate win rate from confidence
        win_rate = confidence
        lose_rate = 1 - win_rate

        # Estimate average win/loss from signal strength and volatility
        avg_win = abs(signal_strength) * volatility * 2
        avg_loss = volatility * 1.5

        if avg_loss <= 0:
            return 0.0

        # Kelly fraction
        kelly_fraction = (win_rate * avg_win - lose_rate * avg_loss) / avg_loss
        kelly_fraction = max(min(kelly_fraction, 0.25), 0.0)  # Limit to 25% max

        return self.max_position_size * kelly_fraction

    def _risk_parity_sizing(
        self, signal_strength: float, volatility: float, account_size: float
    ) -> float:
        """Risk parity position sizing."""
        # Equal risk contribution
        target_risk = account_size * self.risk_tolerance / 10  # Assume 10 positions max
        size = target_risk / (volatility * np.sqrt(252))  # Annualized volatility
        size *= abs(signal_strength)
        return size

    def _ml_based_sizing(
        self,
        symbol: str,
        signal_strength: float,
        volatility: float,
        confidence: float,
        additional_features: dict[str, float],
    ) -> float:
        """ML-based position sizing."""
        if not self.ml_predictor:
            # Fallback to volatility sizing
            return self._volatility_sizing(signal_strength, volatility)

        try:
            # Prepare features for ML model
            features = {
                "signal_strength": signal_strength,
                "volatility": volatility,
                "confidence": confidence,
                "account_size": additional_features.get("account_size", 0),
                "current_price": additional_features.get("current_price", 0),
                "volume_ratio": additional_features.get("volume_ratio", 1.0),
                "market_beta": additional_features.get("market_beta", 1.0),
                "liquidity_score": additional_features.get("liquidity_score", 0.5),
            }

            # Add symbol-specific features if available
            if symbol in additional_features:
                features[f"{symbol}_momentum"] = additional_features[symbol].get(
                    "momentum", 0.0
                )
                features[f"{symbol}_trend"] = additional_features[symbol].get(
                    "trend", 0.0
                )

            # Get ML prediction
            result = self.ml_predictor.predict(features)
            predicted_size = float(result.prediction)
            predicted_confidence = (
                float(result.prediction_probability)
                if hasattr(result, "prediction_probability")
                else confidence
            )

            # Adjust prediction by confidence
            adjusted_size = predicted_size * predicted_confidence

            # Apply signal strength direction
            adjusted_size *= abs(signal_strength)

            return max(adjusted_size, 0.0)

        except Exception as e:
            self.logger.error(f"ML-based sizing failed for {symbol}: {e}")
            return self._volatility_sizing(signal_strength, volatility)

    def _get_sizing_reasons(
        self, final_size: float, requested_size: float, max_allowed: float
    ) -> list[str]:
        """Get reasons for position sizing decision."""
        reasons = []

        if abs(final_size - requested_size) > 1e-6:
            if final_size >= max_allowed:
                reasons.append("Limited by maximum size constraint")
            else:
                reasons.append("Size adjusted by risk constraints")

        if final_size < 100:
            reasons.append("Small position due to weak signal")

        if self.sizing_method == SizingMethod.ML_BASED:
            reasons.append("ML-based sizing used")
        elif self.sizing_method == SizingMethod.VOLATILITY:
            reasons.append("Volatility-based sizing used")
        elif self.sizing_method == SizingMethod.KELLY:
            reasons.append("Kelly criterion sizing used")

        return reasons

    def update_sizing_method(
        self, new_method: SizingMethod, ml_model_id: str | None = None
    ):
        """Update sizing method."""
        self.sizing_method = new_method

        if new_method == SizingMethod.ML_BASED and ml_model_id:
            try:
                self.ml_predictor = MLPredictor(ml_model_id, self.registry)
                self.logger.info(f"Updated ML model for sizing: {ml_model_id}")
            except Exception as e:
                self.logger.error(f"Failed to load new ML model {ml_model_id}: {e}")
                self.ml_predictor = None

    def get_sizing_statistics(self) -> dict[str, Any]:
        """Get sizing statistics."""
        return {
            "sizing_method": self.sizing_method.value,
            "max_position_size": self.max_position_size,
            "risk_tolerance": self.risk_tolerance,
            "ml_model_loaded": self.ml_predictor is not None,
        }

    def validate_position_size(self, position: PositionSize) -> tuple[bool, list[str]]:
        """Validate position size."""
        errors = []

        if position.size <= 0:
            errors.append("Position size must be positive")

        if position.size > self.max_position_size:
            errors.append(
                f"Position size {position.size} exceeds maximum {self.max_position_size}"
            )

        if position.confidence < 0 or position.confidence > 1:
            errors.append(f"Invalid confidence: {position.confidence}")

        return len(errors) == 0, errors
