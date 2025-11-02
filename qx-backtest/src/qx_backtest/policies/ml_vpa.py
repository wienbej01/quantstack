"""ML VPA trading policy that consumes VPA features + model scores."""

import json
import pathlib
from typing import Any

import numpy as np

from qx_features.ml_trainer import ModelTrainer

from ..order import OrderSide
from ..portfolio import Position
from .base import Policy


class MLVpaPolicy(Policy):
    """ML-powered VPA trading policy.

    This policy uses machine learning predictions combined with VPA patterns
    to make trading decisions:
    - Entry: Model prediction >= threshold AND VPA patterns align
    - Exit: Model prediction crosses threshold OR timeout/stop conditions
    """

    def __init__(
        self,
        model_path: str,
        prediction_threshold: float = 0.6,
        vpa_weight: float = 0.3,
        max_position_bars: int = 50,
        position_size_pct: float = 0.1,
        max_positions: int = 5,
        min_confidence: float = 0.5,
        name: str = "MLVpa",
    ):
        """Initialize ML VPA policy.

        Args:
            model_path: Path to trained model directory
            prediction_threshold: Minimum model prediction for entry
            vpa_weight: Weight given to VPA patterns in final decision
            max_position_bars: Maximum bars to hold position
            position_size_pct: Position size as percentage of equity
            max_positions: Maximum concurrent positions
            min_confidence: Minimum confidence score for VPA patterns
            name: Policy name
        """
        super().__init__(name)
        self.model_path = pathlib.Path(model_path)
        self.prediction_threshold = prediction_threshold
        self.vpa_weight = vpa_weight
        self.max_position_bars = max_position_bars
        self.position_size_pct = position_size_pct
        self.max_positions = max_positions
        self.min_confidence = min_confidence

        # Load model and metadata
        self.model_trainer = None
        self.model_metadata = None
        self.feature_names = None

        # Track position entry times and entry conditions
        self.position_entry_times: dict[str, int] = {}
        self.position_entry_scores: dict[str, float] = {}

    def on_start(self) -> None:
        """Called when backtest starts - load the model."""
        try:
            # Load the trained model
            self.model_trainer = ModelTrainer.load_model(self.model_path)

            # Load model metadata
            manifest_path = self.model_path / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    self.model_metadata = json.load(f)
                self.feature_names = self.model_metadata.get("feature_names", [])

            print(f"{self.name}: Loaded model from {self.model_path}")
            print(
                f"{self.name}: Using {len(self.feature_names) if self.feature_names else 0} features"
            )

        except Exception as e:
            print(f"{self.name}: Failed to load model: {e}")
            self.model_trainer = None

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single bar of data."""
        if self.model_trainer is None or self.feature_names is None:
            return

        symbol = bar["symbol"]
        timestamp = bar["ts"]

        # Check if we have all required features
        missing_features = [f for f in self.feature_names if f not in bar]
        if missing_features:
            return

        # Extract features for prediction
        feature_values = [bar[f] for f in self.feature_names]

        # Handle NaN values
        if any(np.isnan(v) for v in feature_values):
            return

        # Make prediction
        try:
            X = np.array([feature_values])
            prediction_prob = self.model_trainer.predict(
                pd.DataFrame(X, columns=self.feature_names), return_proba=True
            )

            if isinstance(prediction_prob, tuple):
                _, prob = prediction_prob
                model_score = float(prob[0])
            else:
                model_score = float(prediction_prob[0])

        except Exception as e:
            print(f"{self.name}: Prediction failed for {symbol}: {e}")
            return

        # Get VPA pattern scores
        vpa_score = self._calculate_vpa_score(bar)

        # Combine model and VPA scores
        combined_score = (
            1 - self.vpa_weight
        ) * model_score + self.vpa_weight * vpa_score

        # Get current position
        position = self.get_position(symbol)

        if position is None or position.is_flat:
            # Check for entry signal
            self._check_entry_signal(
                symbol, bar, model_score, vpa_score, combined_score, timestamp
            )
        else:
            # Check for exit signal
            self._check_exit_signal(
                symbol, bar, position, model_score, vpa_score, combined_score, timestamp
            )

    def _calculate_vpa_score(self, bar: dict[str, Any]) -> float:
        """Calculate VPA pattern score from bar data."""
        vpa_patterns = []
        vpa_confidences = []

        # Extract VPA pattern flags and confidences
        for key, value in bar.items():
            if key.startswith("p__vpa__") and value == 1:
                pattern_name = key.replace("p__vpa__", "")
                vpa_patterns.append(pattern_name)

                # Get corresponding confidence
                conf_key = f"conf__vpa__{pattern_name}"
                if conf_key in bar:
                    vpa_confidences.append(bar[conf_key])

        if not vpa_patterns:
            return 0.0

        # Average confidence of active patterns
        avg_confidence = np.mean(vpa_confidences) if vpa_confidences else 0.0

        # Only count if confidence meets minimum threshold
        if avg_confidence < self.min_confidence:
            return 0.0

        # Weight by number of patterns (more patterns = stronger signal)
        pattern_weight = min(len(vpa_patterns) / 3.0, 1.0)  # Cap at 3 patterns

        return avg_confidence * pattern_weight

    def _check_entry_signal(
        self,
        symbol: str,
        bar: dict[str, Any],
        model_score: float,
        vpa_score: float,
        combined_score: float,
        timestamp: int,
    ) -> None:
        """Check for entry signal."""
        # Entry criteria: combined score >= threshold
        if combined_score >= self.prediction_threshold:
            # Check if we have room for more positions
            current_positions = len(self.engine.portfolio.positions)
            if current_positions >= self.max_positions:
                return

            # Check if we already have a pending order for this symbol
            pending_orders = self.get_pending_orders(symbol)
            if pending_orders:
                return

            # Additional sanity checks
            if not self._validate_entry_conditions(bar, model_score, vpa_score):
                return

            # Calculate position size
            close = bar["close"]
            position_size = self._calculate_position_size(close)

            if position_size > 0:
                # Create buy order
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=position_size,
                    tags={
                        "policy": self.name,
                        "entry_price": close,
                        "model_score": model_score,
                        "vpa_score": vpa_score,
                        "combined_score": combined_score,
                        "threshold": self.prediction_threshold,
                        "active_vpa_patterns": self._get_active_patterns(bar),
                    },
                )

                self.submit_order(order)

                # Track entry
                self.position_entry_times[symbol] = timestamp
                self.position_entry_scores[symbol] = combined_score

    def _check_exit_signal(
        self,
        symbol: str,
        bar: dict[str, Any],
        position: Position,
        model_score: float,
        vpa_score: float,
        combined_score: float,
        timestamp: int,
    ) -> None:
        """Check for exit signal."""
        # Check if position has entry time recorded
        if symbol not in self.position_entry_times:
            self.position_entry_times[symbol] = timestamp

        entry_time = self.position_entry_times[symbol]
        bars_held = self._calculate_bars_held(entry_time, timestamp)
        entry_score = self.position_entry_scores.get(symbol, combined_score)

        # Exit criteria:
        # 1. Model score drops below threshold significantly
        # 2. Combined score drops significantly below entry score
        # 3. Maximum bars held (timeout)
        # 4. Stop loss (optional)

        exit_reason = None

        # Model-based exit
        if model_score < (self.prediction_threshold * 0.5):
            exit_reason = "model_signal_loss"

        # Combined score exit (significant degradation)
        elif combined_score < (entry_score * 0.7):
            exit_reason = "combined_score_decay"

        # Timeout exit
        elif bars_held >= self.max_position_bars:
            exit_reason = "timeout"

        # Could add stop loss or profit target here

        if exit_reason:
            # Check if we already have a pending sell order
            pending_orders = self.get_pending_orders(symbol)
            sell_pending = any(order.side == OrderSide.SELL for order in pending_orders)

            if not sell_pending:
                # Create sell order for entire position
                close = bar["close"]
                order = self.engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=position.quantity,
                    tags={
                        "policy": self.name,
                        "exit_reason": exit_reason,
                        "bars_held": bars_held,
                        "entry_price": position.avg_cost,
                        "exit_price": close,
                        "entry_score": entry_score,
                        "exit_model_score": model_score,
                        "exit_vpa_score": vpa_score,
                        "exit_combined_score": combined_score,
                        "pnl": position.quantity * (close - position.avg_cost),
                    },
                )

                self.submit_order(order)

                # Clean up tracking
                self.position_entry_times.pop(symbol, None)
                self.position_entry_scores.pop(symbol, None)

    def _validate_entry_conditions(
        self, bar: dict[str, Any], model_score: float, vpa_score: float
    ) -> bool:
        """Validate additional entry conditions."""
        # Basic sanity checks
        if model_score < 0.5 or model_score > 1.0:
            return False

        if vpa_score < 0 or vpa_score > 1.0:
            return False

        # Check for extreme market conditions
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]

        # Avoid entering during extreme volatility within the bar
        bar_range = (high - low) / close
        if bar_range > 0.1:  # More than 10% intraday range
            return False

        # Could add more sophisticated checks here
        return True

    def _get_active_patterns(self, bar: dict[str, Any]) -> list[str]:
        """Get list of active VPA patterns."""
        active_patterns = []
        for key, value in bar.items():
            if key.startswith("p__vpa__") and value == 1:
                pattern_name = key.replace("p__vpa__", "")
                active_patterns.append(pattern_name)
        return active_patterns

    def _calculate_position_size(self, price: float) -> int:
        """Calculate position size based on risk management."""
        # Get current equity
        current_equity = self.engine.portfolio.total_equity
        target_value = current_equity * self.position_size_pct

        # Calculate number of shares
        position_size = int(target_value / price)

        # Round to nearest 100 (board lot)
        position_size = (position_size // 100) * 100

        # Ensure minimum position size
        if position_size < 100:
            position_size = 0

        return position_size

    def _calculate_bars_held(self, entry_time: int, current_time: int) -> int:
        """Calculate number of bars held since entry."""
        # Assuming 1-minute bars
        minute_ns = 60 * 1_000_000_000
        bars_held = (current_time - entry_time) // minute_ns
        return int(bars_held)

    def on_end(self) -> None:
        """Called when backtest ends."""
        if self.model_metadata:
            print(
                f"{self.name}: Model info - {self.model_metadata.get('model_type', 'unknown')} "
                f"with {len(self.feature_names) if self.feature_names else 0} features"
            )

        total_positions_held = len(self.position_entry_times)
        if total_positions_held > 0:
            avg_entry_score = (
                np.mean(list(self.position_entry_scores.values()))
                if self.position_entry_scores
                else 0
            )
            print(
                f"{self.name}: Held {total_positions_held} positions, avg entry score: {avg_entry_score:.3f}"
            )


# Legacy function for backward compatibility
def generate_ml_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Generate signals for ML VPA strategy (legacy function).

    Args:
        df: DataFrame with bars, features, and model predictions
        params: Parameters dict with threshold, vpa_weight, etc.

    Returns:
        DataFrame with signals: ts, symbol, signal (1=long, 0=flat), and diagnostic columns
    """
    threshold = params.get("threshold", 0.6)
    vpa_weight = params.get("vpa_weight", 0.3)
    timeout_bars = params.get("timeout_bars", 50)
    min_confidence = params.get("min_confidence", 0.5)

    signals = []
    position_tracker = (
        {}
    )  # symbol -> {'entry_ts': ts, 'bars_held': int, 'entry_score': float}

    for _idx, row in df.iterrows():
        ts = row["ts"]
        symbol = row["symbol"]
        close = row["close"]

        # Get model prediction
        model_score = row.get("model_prediction", 0)

        # Calculate VPA score
        vpa_patterns = []
        vpa_confidences = []

        for key, value in row.items():
            if key.startswith("p__vpa__") and value == 1:
                pattern_name = key.replace("p__vpa__", "")
                vpa_patterns.append(pattern_name)

                conf_key = f"conf__vpa__{pattern_name}"
                if conf_key in row:
                    vpa_confidences.append(row[conf_key])

        vpa_score = 0.0
        if vpa_patterns:
            avg_confidence = np.mean(vpa_confidences) if vpa_confidences else 0.0
            if avg_confidence >= min_confidence:
                pattern_weight = min(len(vpa_patterns) / 3.0, 1.0)
                vpa_score = avg_confidence * pattern_weight

        # Combine scores
        combined_score = (1 - vpa_weight) * model_score + vpa_weight * vpa_score

        # Get position state from START of bar
        pos_before_decision = position_tracker.get(
            symbol, {"entry_ts": None, "bars_held": 0, "entry_score": 0}
        )

        # Decision logic
        decision = "hold"
        if pos_before_decision["entry_ts"] is not None:
            # In position
            new_bars_held = pos_before_decision["bars_held"] + 1

            # Exit conditions
            exit_signal = False

            # Model signal loss
            if model_score < (threshold * 0.5):
                exit_signal = True
                decision = "exit_model"
            # Combined score decay
            elif combined_score < (pos_before_decision["entry_score"] * 0.7):
                exit_signal = True
                decision = "exit_combined"
            # Timeout
            elif new_bars_held >= timeout_bars:
                exit_signal = True
                decision = "exit_timeout"

            if exit_signal:
                position_tracker[symbol] = {
                    "entry_ts": None,
                    "bars_held": 0,
                    "entry_score": 0,
                }
            else:
                position_tracker[symbol]["bars_held"] = new_bars_held

        # Flat - check entry
        elif combined_score >= threshold:
            decision = "enter"
            position_tracker[symbol] = {
                "entry_ts": ts,
                "bars_held": 1,
                "entry_score": combined_score,
            }

        # Get position state AFTER decision for the current bar
        pos_after_decision = position_tracker.get(
            symbol, {"entry_ts": None, "bars_held": 0, "entry_score": 0}
        )

        # Generate signal based on the state AFTER the decision
        signal = 1 if pos_after_decision["entry_ts"] is not None else 0

        # Diagnostic columns
        diag = {
            "ts": ts,
            "symbol": symbol,
            "signal": signal,
            "close": close,
            "model_score": model_score,
            "vpa_score": vpa_score,
            "combined_score": combined_score,
            "threshold": threshold,
            "bars_held": pos_after_decision["bars_held"],
            "decision": decision,
            "active_patterns": len(vpa_patterns),
        }

        signals.append(diag)

    return pd.DataFrame(signals)
