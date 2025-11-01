"""Base class for ML-based trading policies."""

from abc import ABC, abstractmethod
from typing import Any

from qx_backtest.order import Order, OrderSide
from qx_backtest.policies.base import Policy

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry


class BaseMLPolicy(Policy, ABC):
    """Base class for ML-based trading policies."""

    def __init__(
        self,
        model_id: str,
        registry: MLModelRegistry | None = None,
        prediction_threshold: float = 0.5,
        position_size_method: str = "fixed",
        position_size_value: float = 1000.0,
        max_positions: int = 5,
        features_required: list[str] | None = None,
        **kwargs,
    ):
        """Initialize ML policy.

        Args:
            model_id: ID of ML model to use
            registry: Model registry (creates default if None)
            prediction_threshold: Threshold for trade signals
            position_size_method: Method for sizing positions ('fixed', 'volatility', 'signal_strength')
            position_size_value: Base position size value
            max_positions: Maximum concurrent positions
            features_required: List of required features (auto-detected if None)
            **kwargs: Additional arguments passed to parent Policy
        """
        super().__init__(**kwargs)

        self.model_id = model_id
        self.prediction_threshold = prediction_threshold
        self.position_size_method = position_size_method
        self.position_size_value = position_size_value
        self.max_positions = max_positions

        # Initialize ML components
        self.registry = registry or MLModelRegistry()
        self.predictor = MLPredictor(self.registry)
        self.model_metadata = self.registry.get_metadata(model_id)

        # Set required features
        if features_required is None:
            self.features_required = self.model_metadata.features
        else:
            self.features_required = features_required

        # Validate model compatibility
        self._validate_model_compatibility()

        # Track state
        self.current_signals: dict[str, float] = {}
        self.last_prediction_ts: dict[str, int] = {}

    def _validate_model_compatibility(self) -> None:
        """Validate that model is suitable for trading."""
        if self.model_metadata.model_type.value not in ["classification", "regression"]:
            raise ValueError(
                f"Unsupported model type: {self.model_metadata.model_type}"
            )

        # Check if model has reasonable performance
        if self.model_metadata.val_score < 0.5:
            raise ValueError(
                f"Model validation score too low: {self.model_metadata.val_score}"
            )

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single bar and generate trading signals.

        Args:
            bar: Bar data dictionary with OHLCV and features
        """
        symbol = bar["symbol"]
        timestamp = bar["ts"]

        # Check if we already have a recent prediction for this symbol
        if (
            symbol in self.last_prediction_ts
            and timestamp <= self.last_prediction_ts[symbol]
        ):
            return

        # Check if we have required features
        if not self._has_required_features(bar):
            return

        # Check position limits
        if not self._can_open_position(symbol):
            return

        # Extract features for prediction
        features = self._extract_features(bar)

        try:
            # Make prediction
            prediction = self._predict_single(features, timestamp, symbol)

            # Store prediction timestamp
            self.last_prediction_ts[symbol] = timestamp

            # Process prediction signal
            signal_strength = self._prediction_to_signal_strength(prediction)
            self.current_signals[symbol] = signal_strength

            # Generate order if signal is strong enough
            if self._should_trade(signal_strength, symbol):
                order = self._create_order(bar, signal_strength, prediction)
                if order:
                    self.submit_order(order)

        except Exception as e:
            # Log prediction error but continue processing
            print(f"Prediction error for {symbol} at {timestamp}: {e}")

    def _has_required_features(self, bar: dict[str, Any]) -> bool:
        """Check if bar has all required features."""
        return all(feature in bar for feature in self.features_required)

    def _can_open_position(self, symbol: str) -> bool:
        """Check if we can open a new position for symbol."""
        # Check if we already have a position
        current_position = self.get_position(symbol)
        if current_position is not None and current_position.size != 0:
            return False

        # Check maximum position limit
        current_positions = (
            sum(
                1
                for s in self.engine.get_positions()
                if self.get_position(s) and self.get_position(s).size != 0
            )
            if self.engine
            else 0
        )

        return current_positions < self.max_positions

    def _extract_features(self, bar: dict[str, Any]) -> dict[str, float]:
        """Extract features from bar for prediction."""
        return {feature: float(bar[feature]) for feature in self.features_required}

    def _predict_single(
        self, features: dict[str, float], timestamp: int, symbol: str
    ) -> Any:
        """Make prediction for single observation."""
        return self.predictor.predict_single(
            model_id=self.model_id,
            features=features,
            timestamp=timestamp,
            symbol=symbol,
            return_probability=True,
        )

    @abstractmethod
    def _prediction_to_signal_strength(self, prediction: Any) -> float:
        """Convert ML prediction to signal strength (-1 to 1).

        Args:
            prediction: ML prediction result

        Returns:
            Signal strength between -1 (strong sell) and 1 (strong buy)
        """
        pass

    def _should_trade(self, signal_strength: float, symbol: str) -> bool:
        """Determine if signal is strong enough to trade."""
        return abs(signal_strength) > self.prediction_threshold

    def _create_order(
        self, bar: dict[str, Any], signal_strength: float, prediction: Any
    ) -> Order | None:
        """Create order based on signal."""
        symbol = bar["symbol"]
        bar["close"]  # Use close price for order

        # Determine order side
        if signal_strength > 0:
            side = OrderSide.BUY
        elif signal_strength < 0:
            side = OrderSide.SELL
        else:
            return None

        # Calculate position size
        qty = self._calculate_position_size(bar, signal_strength, prediction)
        if qty <= 0:
            return None

        # Create order
        order = Order(
            symbol=symbol,
            side=side,
            qty=qty,
            order_type="market",  # Market orders for intraday
            timestamp=bar["ts"],
        )

        return order

    def _calculate_position_size(
        self, bar: dict[str, Any], signal_strength: float, prediction: Any
    ) -> float:
        """Calculate position size based on method and signal."""
        if self.position_size_method == "fixed":
            return self.position_size_value

        elif self.position_size_method == "signal_strength":
            # Scale by signal strength
            base_size = self.position_size_value
            return base_size * abs(signal_strength)

        elif self.position_size_method == "volatility":
            # Volatility-based sizing (simplified)
            if "atr" in bar:
                volatility = float(bar["atr"])
                risk_per_share = volatility * 2.0  # 2x ATR risk
                if risk_per_share > 0:
                    return self.position_size_value / risk_per_share
            return self.position_size_value

        else:
            return self.position_size_value

    def on_start(self) -> None:
        """Called when backtest starts."""
        # Load model into cache
        self.predictor.load_model(self.model_id)
        print(f"Loaded ML model: {self.model_id}")
        print(f"Model type: {self.model_metadata.model_type.value}")
        print(f"Features: {self.features_required}")

    def on_end(self) -> None:
        """Called when backtest ends."""
        # Clear predictor cache
        self.predictor.clear_cache()
