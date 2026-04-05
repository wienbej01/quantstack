"""ML-based trading signal wrapping XGBoost predictions.

Implements the Signal interface so it plugs directly into AlphaBacktestEngine.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from .base import ExitEvent, Position, Signal, SignalEvent, SignalSide

logger = logging.getLogger(__name__)


class MLSignal(Signal):
    """Signal driven by XGBoost 3-class predictions (down/flat/up).

    Entry: when predicted probability for up or down exceeds confidence_threshold.
    Exit: target/stop/time-limit (standard), or optional model-based reversal.
    """

    def __init__(self, config: dict, model_artifact: Optional[dict] = None):
        """Initialize ML signal.

        Args:
            config: Full backtest config dict.
            model_artifact: Dict from xgb_trainer.load_model() with keys:
                model, feature_columns, horizon, mean_val_acc.
                If None, loads from config signals.ml.model_path.
        """
        super().__init__(config)
        ml_cfg = config.get("signals", {}).get("ml", {})

        self.confidence_threshold = ml_cfg.get("confidence_threshold", 0.55)
        self.long_confidence_threshold = ml_cfg.get(
            "long_confidence_threshold",
            self.confidence_threshold,
        )
        self.short_confidence_threshold = ml_cfg.get(
            "short_confidence_threshold",
            self.confidence_threshold,
        )
        self.min_probability_gap = ml_cfg.get("min_probability_gap", 0.0)
        self.max_flat_probability = ml_cfg.get("max_flat_probability", 1.0)
        self.target_pct = ml_cfg.get("target_pct", 0.60) / 100
        self.stop_pct = ml_cfg.get("stop_pct", 0.50) / 100
        self.time_limit_minutes = ml_cfg.get("time_limit_minutes", 5)
        self.cooldown_seconds = ml_cfg.get("cooldown_seconds", 60)
        self.exit_mode = ml_cfg.get("exit_mode", "target_stop_time")
        self.market_exit_threshold = ml_cfg.get(
            "market_exit_threshold",
            self.confidence_threshold,
        )
        self.market_exit_gap = ml_cfg.get(
            "market_exit_gap",
            self.min_probability_gap,
        )

        valid_exit_modes = {
            "target_stop_time",
            "time_only",
            "target_only_time",
            "stop_only_time",
            "market_based",
        }
        if self.exit_mode not in valid_exit_modes:
            raise ValueError(
                f"Invalid ml exit_mode '{self.exit_mode}'. Expected one of "
                f"{sorted(valid_exit_modes)}."
            )
        if not 0.0 <= self.min_probability_gap <= 1.0:
            raise ValueError(
                f"min_probability_gap must be in [0, 1], got {self.min_probability_gap}"
            )
        if not 0.0 <= self.max_flat_probability <= 1.0:
            raise ValueError(
                f"max_flat_probability must be in [0, 1], got {self.max_flat_probability}"
            )

        if model_artifact is not None:
            self._model = model_artifact["model"]
            self._model_family = model_artifact.get("model_family", "xgb_multiclass")
            self._feature_cols = model_artifact["feature_columns"]
            self._calibrator = model_artifact.get("calibrator")
            self._recommended_threshold = model_artifact.get("recommended_threshold")
        else:
            import joblib

            path = ml_cfg.get("model_path", "models/xgb_best.pkl")
            art = joblib.load(path)
            self._model = art["model"]
            self._model_family = art.get("model_family", "xgb_multiclass")
            self._feature_cols = art["feature_columns"]
            self._calibrator = art.get("calibrator")
            self._recommended_threshold = art.get("recommended_threshold")

        self._last_exit_ts: dict = {}  # symbol -> last exit timestamp
        self._logged_missing_signatures: set[tuple[str, str, tuple[str, ...]]] = set()
        self._logged_nonfinite_signatures: set[tuple[str, str, tuple[str, ...]]] = set()

    def _extract_feature_row(
        self,
        features: dict,
        *,
        symbol: str,
        timestamp: pd.Timestamp,
    ) -> Optional[np.ndarray]:
        """Validate the model feature contract and return a dense row when scoreable."""
        if features.get("_ml_features_ready") is False:
            return None

        missing = [column for column in self._feature_cols if column not in features]
        if missing:
            signature = (symbol, str(timestamp.date()), tuple(missing[:10]))
            if signature not in self._logged_missing_signatures:
                self._logged_missing_signatures.add(signature)
                logger.warning(
                    "Skipping ML entry for %s on %s due to missing features: %s",
                    symbol,
                    timestamp.date(),
                    missing[:10],
                )
            return None

        row = np.array(
            [features[column] for column in self._feature_cols], dtype=np.float32
        )
        finite_mask = np.isfinite(row)
        if not finite_mask.all():
            bad_columns = [
                self._feature_cols[idx]
                for idx, is_finite in enumerate(finite_mask)
                if not is_finite
            ]
            signature = (symbol, str(timestamp.date()), tuple(bad_columns[:10]))
            if signature not in self._logged_nonfinite_signatures:
                self._logged_nonfinite_signatures.add(signature)
                logger.warning(
                    "Skipping ML entry for %s on %s due to non-finite features: %s",
                    symbol,
                    timestamp.date(),
                    bad_columns[:10],
                )
            return None
        return row

    def predict_probabilities(
        self,
        features: dict,
        *,
        symbol: str,
        timestamp: pd.Timestamp,
    ) -> Optional[tuple[float, float, float]]:
        """Score a validated feature dict and return calibrated class probabilities."""
        row = self._extract_feature_row(features, symbol=symbol, timestamp=timestamp)
        if row is None:
            return None

        x = row.reshape(1, -1)
        proba = self._model.predict_proba(x)
        if self._calibrator is not None:
            proba = self._calibrator.predict_proba(proba)
        p_down, p_flat, p_up = proba[0]  # [p_down, p_flat, p_up]
        return float(p_down), float(p_flat), float(p_up)

    def entry_event_from_probabilities(
        self,
        *,
        symbol: str,
        timestamp: pd.Timestamp,
        p_down: float,
        p_flat: float,
        p_up: float,
    ) -> Optional[SignalEvent]:
        """Construct an entry event from class probabilities if thresholds are met."""
        if symbol in self._last_exit_ts:
            elapsed = (timestamp - self._last_exit_ts[symbol]).total_seconds()
            if elapsed < self.cooldown_seconds:
                return None

        if p_flat > self.max_flat_probability:
            return None

        long_gap = p_up - p_down
        short_gap = p_down - p_up

        if (
            p_up > self.long_confidence_threshold
            and long_gap > 0
            and long_gap >= self.min_probability_gap
        ):
            return SignalEvent(
                symbol=symbol,
                timestamp=timestamp,
                side=SignalSide.LONG,
                confidence=float(p_up),
                features={
                    "p_up": float(p_up),
                    "p_down": float(p_down),
                    "p_flat": float(p_flat),
                    "probability_gap": float(long_gap),
                },
                signal_name=self.signal_name,
            )

        if (
            p_down > self.short_confidence_threshold
            and short_gap > 0
            and short_gap >= self.min_probability_gap
        ):
            return SignalEvent(
                symbol=symbol,
                timestamp=timestamp,
                side=SignalSide.SHORT,
                confidence=float(p_down),
                features={
                    "p_up": float(p_up),
                    "p_down": float(p_down),
                    "p_flat": float(p_flat),
                    "probability_gap": float(short_gap),
                },
                signal_name=self.signal_name,
            )

        return None

    def check_entry(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[SignalEvent]:
        symbol = bar.get("symbol", "UNKNOWN")

        # Cooldown check
        if symbol in self._last_exit_ts:
            elapsed = (timestamp - self._last_exit_ts[symbol]).total_seconds()
            if elapsed < self.cooldown_seconds:
                return None

        probabilities = self.predict_probabilities(
            features, symbol=symbol, timestamp=timestamp
        )
        if probabilities is None:
            return None
        p_down, p_flat, p_up = probabilities
        return self.entry_event_from_probabilities(
            symbol=symbol,
            timestamp=timestamp,
            p_down=p_down,
            p_flat=p_flat,
            p_up=p_up,
        )

    def check_exit(
        self,
        position: Position,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> Optional[ExitEvent]:
        exit_evt: Optional[ExitEvent] = None

        if self.exit_mode == "target_stop_time":
            exit_evt = self._check_target_stop_exit(position, bar)
        elif self.exit_mode == "target_only_time":
            exit_evt = self._check_target_exit(position, bar)
        elif self.exit_mode == "stop_only_time":
            exit_evt = self._check_stop_exit(position, bar)
        elif self.exit_mode == "market_based":
            symbol = bar.get("symbol", position.symbol)
            probabilities = self.predict_probabilities(
                features, symbol=symbol, timestamp=timestamp
            )
            if probabilities is not None:
                exit_evt = self.market_exit_event_from_probabilities(
                    position=position,
                    timestamp=timestamp,
                    p_down=float(probabilities[0]),
                    p_flat=float(probabilities[1]),
                    p_up=float(probabilities[2]),
                )

        if exit_evt:
            self._last_exit_ts[position.symbol] = timestamp
            return exit_evt

        exit_evt = self._check_time_limit_exit(position, timestamp)
        if exit_evt:
            self._last_exit_ts[position.symbol] = timestamp
            return exit_evt

        return None

    def market_exit_event_from_probabilities(
        self,
        *,
        position: Position,
        timestamp: pd.Timestamp,
        p_down: float,
        p_flat: float,
        p_up: float,
    ) -> Optional[ExitEvent]:
        """Exit on model-reversal once the opposite side regains edge."""
        del p_flat  # retained for future richer market-based exit policies
        if position.side == SignalSide.LONG:
            opposite_conf = p_down
            favorable_conf = p_up
        else:
            opposite_conf = p_up
            favorable_conf = p_down

        confidence_gap = opposite_conf - favorable_conf
        if (
            opposite_conf >= self.market_exit_threshold
            and confidence_gap >= self.market_exit_gap
        ):
            return ExitEvent(
                symbol=position.symbol,
                timestamp=timestamp,
                reason="market_reverse",
            )
        return None

    def _check_target_exit(
        self,
        position: Position,
        bar: pd.Series,
    ) -> Optional[ExitEvent]:
        if position.side == SignalSide.LONG and bar["high"] >= position.target_price:
            return ExitEvent(
                symbol=position.symbol,
                timestamp=bar["ts"],
                reason="target",
                exit_price=position.target_price,
            )
        if position.side == SignalSide.SHORT and bar["low"] <= position.target_price:
            return ExitEvent(
                symbol=position.symbol,
                timestamp=bar["ts"],
                reason="target",
                exit_price=position.target_price,
            )
        return None

    def _check_stop_exit(
        self,
        position: Position,
        bar: pd.Series,
    ) -> Optional[ExitEvent]:
        if position.side == SignalSide.LONG and bar["low"] <= position.stop_price:
            return ExitEvent(
                symbol=position.symbol,
                timestamp=bar["ts"],
                reason="stop",
                exit_price=position.stop_price,
            )
        if position.side == SignalSide.SHORT and bar["high"] >= position.stop_price:
            return ExitEvent(
                symbol=position.symbol,
                timestamp=bar["ts"],
                reason="stop",
                exit_price=position.stop_price,
            )
        return None

    def create_position(
        self,
        signal: SignalEvent,
        entry_price: float,
        entry_time: pd.Timestamp,
        quantity: int,
    ) -> Position:
        if signal.side == SignalSide.LONG:
            target = entry_price * (1 + self.target_pct)
            stop = entry_price * (1 - self.stop_pct)
        else:
            target = entry_price * (1 - self.target_pct)
            stop = entry_price * (1 + self.stop_pct)

        return Position(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=entry_price,
            entry_time=entry_time,
            quantity=quantity,
            target_price=target,
            stop_price=stop,
            time_limit_minutes=self.time_limit_minutes,
            signal_name=self.signal_name,
        )
