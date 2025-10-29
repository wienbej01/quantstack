"""Regression-based ML trading policy."""

from typing import Any

import numpy as np

from .base_ml_policy import BaseMLPolicy


class MLRegressionPolicy(BaseMLPolicy):
    """ML trading policy using regression models."""

    def __init__(
        self,
        model_id: str,
        prediction_threshold: float = 0.01,
        volatility_scaling: bool = True,
        volatility_window: int = 20,
        **kwargs,
    ):
        """Initialize regression policy.

        Args:
            model_id: ID of regression model to use
            prediction_threshold: Minimum predicted return to trade
            volatility_scaling: Whether to scale threshold by volatility
            volatility_window: Window for volatility calculation
            **kwargs: Additional arguments passed to base class
        """
        super().__init__(model_id=model_id, **kwargs)

        self.prediction_threshold = prediction_threshold
        self.volatility_scaling = volatility_scaling
        self.volatility_window = volatility_window

        # Store returns for volatility calculation
        self.price_history: Dict[str, list] = {}

        # Validate model type
        if self.model_metadata.model_type.value != "regression":
            raise ValueError("MLRegressionPolicy requires a regression model")

    def _prediction_to_signal_strength(self, prediction: Any) -> float:
        """Convert regression prediction (expected return) to signal strength.

        Args:
            prediction: PredictionResult with return prediction

        Returns:
            Signal strength between -1 and 1
        """
        predicted_return = float(prediction.prediction)

        # Store price history for volatility calculation
        symbol = prediction.symbol
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        # Add current price (extracted from features if available)
        current_price = prediction.feature_values.get("close", 100.0)
        self.price_history[symbol].append(current_price)

        # Keep only recent history
        if len(self.price_history[symbol]) > self.volatility_window * 2:
            self.price_history[symbol] = self.price_history[symbol][
                -self.volatility_window * 2 :
            ]

        # Calculate dynamic threshold if volatility scaling is enabled
        threshold = self.prediction_threshold
        if (
            self.volatility_scaling
            and len(self.price_history[symbol]) >= self.volatility_window
        ):
            prices = np.array(self.price_history[symbol])
            returns = np.diff(prices) / prices[:-1]
            volatility = np.std(returns)
            threshold = max(threshold, volatility * 0.5)  # Scale with volatility

        # Convert predicted return to signal strength with saturation
        if abs(predicted_return) < threshold:
            return 0.0

        # Scale signal strength (sigmoid-like scaling)
        signal = np.tanh(predicted_return / threshold)
        return float(np.clip(signal, -1.0, 1.0))

    def _should_trade(self, signal_strength: float, symbol: str) -> bool:
        """Determine if signal meets trading thresholds."""
        return abs(signal_strength) > self.prediction_threshold
