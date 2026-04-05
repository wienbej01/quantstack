"""Tests for Sprint 4: ML Signal Integration."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from src.signals.base import SignalSide, Position
from src.signals.ml_signal import MLSignal


def _make_mock_model():
    """Create a mock XGBoost model that returns controlled probabilities."""
    model = MagicMock()
    model.predict_proba = MagicMock(return_value=np.array([[0.1, 0.2, 0.7]]))
    return model


def _make_calibrator(return_value):
    calibrator = MagicMock()
    calibrator.predict_proba = MagicMock(return_value=np.array([return_value]))
    return calibrator


def _make_config():
    return {
        "signals": {
            "ml": {
                "confidence_threshold": 0.55,
                "long_confidence_threshold": 0.55,
                "short_confidence_threshold": 0.55,
                "min_probability_gap": 0.0,
                "max_flat_probability": 1.0,
                "target_pct": 0.60,
                "stop_pct": 0.50,
                "time_limit_minutes": 5,
                "cooldown_seconds": 60,
                "exit_mode": "target_stop_time",
            }
        }
    }


def _make_bar(symbol="TEST", close=50.0, high=50.5, low=49.5):
    return pd.Series(
        {
            "symbol": symbol,
            "close": close,
            "high": high,
            "low": low,
            "ts": pd.Timestamp.now(),
        }
    )


class TestMLSignal:
    def test_implements_signal_interface(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)
        assert hasattr(sig, "check_entry")
        assert hasattr(sig, "check_exit")
        assert hasattr(sig, "create_position")

    def test_entry_long_high_confidence(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.1, 0.2, 0.7]])  # p_up=0.7
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)
        features = {"f1": 0.5, "f2": -0.3}
        bar = _make_bar()
        event = sig.check_entry(features, bar, pd.Timestamp.now())
        assert event is not None
        assert event.side == SignalSide.LONG
        assert event.confidence == pytest.approx(0.7)

    def test_entry_short_high_confidence(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.7, 0.2, 0.1]])  # p_down=0.7
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)
        event = sig.check_entry({"f1": 0, "f2": 0}, _make_bar(), pd.Timestamp.now())
        assert event is not None
        assert event.side == SignalSide.SHORT

    def test_calibrator_is_applied_before_threshold_logic(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.30, 0.20, 0.50]])
        calibrator = _make_calibrator([0.72, 0.08, 0.20])
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
            "calibrator": calibrator,
            "recommended_threshold": 0.45,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)

        event = sig.check_entry({"f1": 0, "f2": 0}, _make_bar(), pd.Timestamp.now())

        assert event is not None
        assert event.side == SignalSide.SHORT
        calibrator.predict_proba.assert_called_once()

    def test_no_entry_low_confidence(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.35, 0.35, 0.30]])
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)
        event = sig.check_entry({"f1": 0, "f2": 0}, _make_bar(), pd.Timestamp.now())
        assert event is None

    def test_no_entry_when_probability_gap_too_small(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.28, 0.18, 0.54]])
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        config = _make_config()
        config["signals"]["ml"]["confidence_threshold"] = 0.50
        config["signals"]["ml"]["long_confidence_threshold"] = 0.50
        config["signals"]["ml"]["min_probability_gap"] = 0.30
        sig = MLSignal(config, model_artifact=artifact)
        event = sig.check_entry({"f1": 0}, _make_bar(), pd.Timestamp.now())
        assert event is None

    def test_no_entry_when_flat_probability_too_high(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.10, 0.55, 0.62]])
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        config = _make_config()
        config["signals"]["ml"]["confidence_threshold"] = 0.60
        config["signals"]["ml"]["long_confidence_threshold"] = 0.60
        config["signals"]["ml"]["max_flat_probability"] = 0.50
        sig = MLSignal(config, model_artifact=artifact)
        event = sig.check_entry({"f1": 0}, _make_bar(), pd.Timestamp.now())
        assert event is None

    def test_long_and_short_thresholds_can_differ(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.58, 0.10, 0.32]])
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        config = _make_config()
        config["signals"]["ml"]["confidence_threshold"] = 0.60
        config["signals"]["ml"]["long_confidence_threshold"] = 0.65
        config["signals"]["ml"]["short_confidence_threshold"] = 0.55
        sig = MLSignal(config, model_artifact=artifact)
        event = sig.check_entry({"f1": 0}, _make_bar(), pd.Timestamp.now())
        assert event is not None
        assert event.side == SignalSide.SHORT

    def test_cooldown_prevents_reentry(self):
        model = _make_mock_model()
        model.predict_proba.return_value = np.array([[0.1, 0.2, 0.7]])
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)
        # Simulate a recent exit
        sig._last_exit_ts["TEST"] = pd.Timestamp.now()
        event = sig.check_entry({"f1": 0, "f2": 0}, _make_bar(), pd.Timestamp.now())
        assert event is None  # within cooldown

    def test_missing_model_features_skip_entry(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)

        event = sig.check_entry({"f1": 1.0}, _make_bar(), pd.Timestamp.now())

        assert event is None
        model.predict_proba.assert_not_called()

    def test_not_ready_ml_features_skip_entry_without_scoring(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)

        event = sig.check_entry(
            {"_ml_features_ready": False, "f1": 1.0, "f2": 2.0},
            _make_bar(),
            pd.Timestamp.now(),
        )

        assert event is None
        model.predict_proba.assert_not_called()

    def test_non_finite_model_features_skip_entry(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1", "f2"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)

        event = sig.check_entry(
            {"f1": np.nan, "f2": 1.0}, _make_bar(), pd.Timestamp.now()
        )

        assert event is None
        model.predict_proba.assert_not_called()

    def test_create_position_long(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)
        from src.signals.base import SignalEvent

        signal = SignalEvent(
            symbol="TEST",
            timestamp=pd.Timestamp.now(),
            side=SignalSide.LONG,
            confidence=0.7,
            features={},
            signal_name="MLSignal",
        )
        pos = sig.create_position(signal, 50.0, pd.Timestamp.now(), 100)
        assert pos.target_price > pos.entry_price
        assert pos.stop_price < pos.entry_price

    def test_create_position_short(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        sig = MLSignal(_make_config(), model_artifact=artifact)
        from src.signals.base import SignalEvent

        signal = SignalEvent(
            symbol="TEST",
            timestamp=pd.Timestamp.now(),
            side=SignalSide.SHORT,
            confidence=0.7,
            features={},
            signal_name="MLSignal",
        )
        pos = sig.create_position(signal, 50.0, pd.Timestamp.now(), 100)
        assert pos.target_price < pos.entry_price
        assert pos.stop_price > pos.entry_price

    def test_time_only_exit_ignores_target_and_stop(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        config = _make_config()
        config["signals"]["ml"]["exit_mode"] = "time_only"
        sig = MLSignal(config, model_artifact=artifact)
        position = Position(
            symbol="TEST",
            side=SignalSide.LONG,
            entry_price=50.0,
            entry_time=pd.Timestamp("2026-01-02 09:30:00"),
            quantity=100,
            target_price=50.1,
            stop_price=49.9,
            time_limit_minutes=5,
            signal_name="MLSignal",
        )
        bar = pd.Series(
            {
                "symbol": "TEST",
                "ts": pd.Timestamp("2026-01-02 09:32:00"),
                "high": 50.2,
                "low": 49.8,
                "close": 50.0,
            }
        )
        assert sig.check_exit(position, {}, bar, bar["ts"]) is None
        timed_bar = bar.copy()
        timed_bar["ts"] = pd.Timestamp("2026-01-02 09:35:00")
        exit_event = sig.check_exit(position, {}, timed_bar, timed_bar["ts"])
        assert exit_event is not None
        assert exit_event.reason == "time_limit"

    def test_target_only_time_does_not_stop_out(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        config = _make_config()
        config["signals"]["ml"]["exit_mode"] = "target_only_time"
        sig = MLSignal(config, model_artifact=artifact)
        position = Position(
            symbol="TEST",
            side=SignalSide.LONG,
            entry_price=50.0,
            entry_time=pd.Timestamp("2026-01-02 09:30:00"),
            quantity=100,
            target_price=50.3,
            stop_price=49.8,
            time_limit_minutes=5,
            signal_name="MLSignal",
        )
        stop_bar = pd.Series(
            {
                "symbol": "TEST",
                "ts": pd.Timestamp("2026-01-02 09:31:00"),
                "high": 50.1,
                "low": 49.7,
                "close": 49.8,
            }
        )
        assert sig.check_exit(position, {}, stop_bar, stop_bar["ts"]) is None

    def test_market_based_exit_triggers_on_opposite_side_reversal(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        config = _make_config()
        config["signals"]["ml"]["exit_mode"] = "market_based"
        config["signals"]["ml"]["market_exit_threshold"] = 0.55
        config["signals"]["ml"]["market_exit_gap"] = 0.10
        sig = MLSignal(config, model_artifact=artifact)
        position = Position(
            symbol="TEST",
            side=SignalSide.LONG,
            entry_price=50.0,
            entry_time=pd.Timestamp("2026-01-02 09:30:00"),
            quantity=100,
            target_price=50.3,
            stop_price=49.8,
            time_limit_minutes=8,
            signal_name="MLSignal",
        )

        exit_event = sig.market_exit_event_from_probabilities(
            position=position,
            timestamp=pd.Timestamp("2026-01-02 09:33:00"),
            p_down=0.70,
            p_flat=0.05,
            p_up=0.20,
        )

        assert exit_event is not None
        assert exit_event.reason == "market_reverse"

    def test_market_based_exit_stays_in_trade_without_reversal(self):
        model = _make_mock_model()
        artifact = {
            "model": model,
            "feature_columns": ["f1"],
            "horizon": 180,
            "mean_val_acc": 0.55,
        }
        config = _make_config()
        config["signals"]["ml"]["exit_mode"] = "market_based"
        config["signals"]["ml"]["market_exit_threshold"] = 0.55
        config["signals"]["ml"]["market_exit_gap"] = 0.10
        sig = MLSignal(config, model_artifact=artifact)
        position = Position(
            symbol="TEST",
            side=SignalSide.SHORT,
            entry_price=50.0,
            entry_time=pd.Timestamp("2026-01-02 09:30:00"),
            quantity=100,
            target_price=49.7,
            stop_price=50.2,
            time_limit_minutes=8,
            signal_name="MLSignal",
        )

        exit_event = sig.market_exit_event_from_probabilities(
            position=position,
            timestamp=pd.Timestamp("2026-01-02 09:33:00"),
            p_down=0.60,
            p_flat=0.20,
            p_up=0.30,
        )

        assert exit_event is None
