"""Classification-based ML trading policy."""

from typing import Any

from .base_ml_policy import BaseMLPolicy


class MLClassificationPolicy(BaseMLPolicy):
    """ML trading policy using classification models."""

    def __init__(
        self,
        model_id: str,
        long_threshold: float = 0.6,
        short_threshold: float = 0.4,
        confidence_threshold: float = 0.1,
        **kwargs
    ):
        """Initialize classification policy.

        Args:
            model_id: ID of classification model to use
            long_threshold: Probability threshold for long signals
            short_threshold: Probability threshold for short signals
            confidence_threshold: Minimum confidence to trade
            **kwargs: Additional arguments passed to base class
        """
        super().__init__(model_id=model_id, **kwargs)

        self.long_threshold = long_threshold
        self.short_threshold = short_threshold
        self.confidence_threshold = confidence_threshold

        # Validate model type
        if self.model_metadata.model_type.value != "classification":
            raise ValueError("MLClassificationPolicy requires a classification model")

    def _prediction_to_signal_strength(self, prediction: Any) -> float:
        """Convert classification prediction to signal strength.

        Args:
            prediction: PredictionResult with classification prediction

        Returns:
            Signal strength between -1 and 1
        """
        # Get probability of positive class (class 1)
        if prediction.prediction_probability is not None:
            confidence = prediction.prediction_probability
        else:
            # If no probability available, use prediction directly
            confidence = float(prediction.prediction)

        # Convert to signal strength
        if prediction.prediction == 1:  # Long signal
            # Map confidence to signal strength (0.5 to 1.0)
            signal = (confidence - 0.5) * 2.0
            return max(0, min(signal, 1.0))

        elif prediction.prediction == 0:  # Short signal
            # Map confidence to signal strength (-1.0 to -0.5)
            signal = -(confidence - 0.5) * 2.0
            return max(-1.0, min(signal, 0))

        else:
            # No signal
            return 0.0

    def _should_trade(self, signal_strength: float, symbol: str) -> bool:
        """Determine if signal meets trading thresholds."""
        if abs(signal_strength) < self.confidence_threshold:
            return False

        if signal_strength > 0:
            return signal_strength >= (self.long_threshold - 0.5) * 2.0
        else:
            return abs(signal_strength) >= (0.5 - self.short_threshold) * 2.0