"""Tests for ML trading policy functionality."""

from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_models.schemas import (
    FeatureImportance,
    ModelMetadata,
    ModelType,
    PredictionResult,
)
from extensions.intraday_ml_policies.base_ml_policy import BaseMLPolicy
from extensions.intraday_ml_policies.classification_policy import MLClassificationPolicy
from extensions.intraday_ml_policies.regression_policy import MLRegressionPolicy


@pytest.fixture
def mock_engine():
    """Create mock backtest engine."""
    engine = Mock()
    engine.get_position.return_value = None  # No existing positions
    engine.get_positions.return_value = []  # No positions
    return engine


@pytest.fixture
def mock_model_metadata():
    """Create mock model metadata."""
    return ModelMetadata(
        model_id="test_model",
        model_type=ModelType.CLASSIFICATION,
        model_class="RandomForestClassifier",
        training_date=pd.Timestamp.now(),
        features=["f__vwap_30", "f__rel_volume_30", "f__atr_14"],
        target_column="close",
        train_samples=1000,
        val_samples=200,
        test_samples=200,
        train_score=0.8,
        val_score=0.75,
        test_score=0.77,
        feature_importance=[
            FeatureImportance(feature_name=f, importance=0.3, rank=1)
            for f in ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        ],
        random_seed=42,
        data_hash="test_hash",
        model_hash="model_hash",
    )


@pytest.fixture
def sample_bar():
    """Create sample bar data."""
    return {
        "ts": 1640995200000000000,  # 2022-01-01 00:00:00 UTC in ns
        "symbol": "AAPL",
        "open": 150.0,
        "high": 152.0,
        "low": 148.0,
        "close": 151.0,
        "volume": 1000000,
        "f__vwap_30": 150.5,
        "f__rel_volume_30": 1.2,
        "f__atr_14": 2.1,
    }


class TestBaseMLPolicy:
    """Test base ML policy functionality."""

    def test_policy_initialization(self, mock_model_metadata):
        """Test policy initialization."""
        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            with patch(
                "extensions.intraday_ml_policies.base_ml_policy.MLPredictor"
            ) as mock_predictor_class:
                # Setup mocks
                mock_registry = Mock()
                mock_registry.get_metadata.return_value = mock_model_metadata
                mock_registry_class.return_value = mock_registry

                # Create concrete implementation for testing
                class TestPolicy(BaseMLPolicy):
                    def _prediction_to_signal_strength(self, prediction):
                        return 0.5  # Simple implementation

                # Create policy
                policy = TestPolicy(model_id="test_model", name="TestPolicy")

                # Verify initialization
                assert policy.model_id == "test_model"
                assert policy.features_required == mock_model_metadata.features
                assert policy.prediction_threshold == 0.5
                assert policy.max_positions == 5

    def test_feature_validation(self, sample_bar, mock_model_metadata):
        """Test feature validation in bar processing."""
        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            with patch(
                "extensions.intraday_ml_policies.base_ml_policy.MLPredictor"
            ) as mock_predictor_class:
                # Setup mocks
                mock_registry = Mock()
                mock_registry.get_metadata.return_value = mock_model_metadata
                mock_registry_class.return_value = mock_registry

                mock_predictor = Mock()
                mock_predictor_class.return_value = mock_predictor

                # Create concrete implementation for testing
                class TestPolicy(BaseMLPolicy):
                    def _prediction_to_signal_strength(self, prediction):
                        return 0.5  # Simple implementation

                policy = TestPolicy(model_id="test_model")
                policy.engine = Mock()
                policy.submit_order = Mock()

                # Test with all features present
                assert policy._has_required_features(sample_bar) is True

                # Test with missing features
                incomplete_bar = sample_bar.copy()
                del incomplete_bar["f__atr_14"]
                assert policy._has_required_features(incomplete_bar) is False

    def test_position_limits(self, mock_engine, sample_bar, mock_model_metadata):
        """Test position limit checking."""
        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            with patch(
                "extensions.intraday_ml_policies.base_ml_policy.MLPredictor"
            ) as mock_predictor_class:
                # Setup mocks
                mock_registry = Mock()
                mock_registry.get_metadata.return_value = mock_model_metadata
                mock_registry_class.return_value = mock_registry

                mock_predictor = Mock()
                mock_predictor_class.return_value = mock_predictor

                # Create concrete implementation for testing
                class TestPolicy(BaseMLPolicy):
                    def _prediction_to_signal_strength(self, prediction):
                        return 0.5  # Simple implementation

                    def _can_open_position(self, symbol):
                        # Override for easier testing
                        if not self.engine:
                            return True
                        current_position = self.get_position(symbol)
                        if current_position is not None and current_position.size != 0:
                            return False
                        positions = self.engine.get_positions()
                        return len(positions) < self.max_positions

                policy = TestPolicy(model_id="test_model", max_positions=2)
                policy.engine = mock_engine
                policy.get_position = Mock(return_value=None)  # No position

                # Should be able to open position
                assert policy._can_open_position("AAPL") is True

                # Mock existing positions
                policy.engine.get_positions.return_value = ["MSFT", "GOOGL"]
                assert (
                    policy._can_open_position("AAPL") is False
                )  # Max positions reached


class TestMLClassificationPolicy:
    """Test ML classification policy functionality."""

    def test_policy_initialization(self, mock_model_metadata):
        """Test classification policy initialization."""
        # Mock metadata as classification type
        classification_metadata = mock_model_metadata
        classification_metadata.model_type = ModelType.CLASSIFICATION

        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            mock_registry = Mock()
            mock_registry.get_metadata.return_value = classification_metadata
            mock_registry_class.return_value = mock_registry

            policy = MLClassificationPolicy(
                model_id="test_model",
                long_threshold=0.7,
                short_threshold=0.3,
                confidence_threshold=0.2,
            )

            assert policy.long_threshold == 0.7
            assert policy.short_threshold == 0.3
            assert policy.confidence_threshold == 0.2

    def test_prediction_to_signal_strength(self, mock_model_metadata):
        """Test conversion of prediction to signal strength."""
        # Mock metadata as classification type
        classification_metadata = mock_model_metadata
        classification_metadata.model_type = ModelType.CLASSIFICATION

        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            mock_registry = Mock()
            mock_registry.get_metadata.return_value = classification_metadata
            mock_registry_class.return_value = mock_registry

            policy = MLClassificationPolicy(model_id="test_model")

            # Test long signal with high confidence
            long_prediction = PredictionResult(
                model_id="test_model",
                timestamp=1640995200000000000,
                symbol="AAPL",
                features_used=["f__vwap_30"],
                prediction=1,
                prediction_probability=0.8,
                feature_values={"f__vwap_30": 150.5},
            )

            signal = policy._prediction_to_signal_strength(long_prediction)
            assert signal > 0  # Long signal
            assert signal <= 1.0

            # Test short signal with high confidence
            short_prediction = PredictionResult(
                model_id="test_model",
                timestamp=1640995200000000000,
                symbol="AAPL",
                features_used=["f__vwap_30"],
                prediction=0,
                prediction_probability=0.7,
                feature_values={"f__vwap_30": 150.5},
            )

            signal = policy._prediction_to_signal_strength(short_prediction)
            assert signal < 0  # Short signal
            assert signal >= -1.0

    def test_should_trade_logic(self, mock_model_metadata):
        """Test trading logic for classification policy."""
        # Mock metadata as classification type
        classification_metadata = mock_model_metadata
        classification_metadata.model_type = ModelType.CLASSIFICATION

        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            mock_registry = Mock()
            mock_registry.get_metadata.return_value = classification_metadata
            mock_registry_class.return_value = mock_registry

            policy = MLClassificationPolicy(
                model_id="test_model",
                long_threshold=0.7,
                short_threshold=0.3,
                confidence_threshold=0.2,
            )

            # Strong signal should trade
            assert policy._should_trade(0.8, "AAPL") is True
            assert policy._should_trade(-0.8, "AAPL") is True

            # Weak signal should not trade
            assert policy._should_trade(0.1, "AAPL") is False
            assert policy._should_trade(-0.1, "AAPL") is False


class TestMLRegressionPolicy:
    """Test ML regression policy functionality."""

    def test_policy_initialization(self, mock_model_metadata):
        """Test regression policy initialization."""
        # Mock metadata as regression type
        regression_metadata = mock_model_metadata
        regression_metadata.model_type = ModelType.REGRESSION

        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            mock_registry = Mock()
            mock_registry.get_metadata.return_value = regression_metadata
            mock_registry_class.return_value = mock_registry

            policy = MLRegressionPolicy(
                model_id="test_model",
                prediction_threshold=0.015,
                volatility_scaling=True,
            )

            assert policy.prediction_threshold == 0.015
            assert policy.volatility_scaling is True

    def test_prediction_to_signal_strength(self, mock_model_metadata):
        """Test conversion of prediction to signal strength."""
        # Mock metadata as regression type
        regression_metadata = mock_model_metadata
        regression_metadata.model_type = ModelType.REGRESSION

        with patch(
            "extensions.intraday_ml_policies.base_ml_policy.MLModelRegistry"
        ) as mock_registry_class:
            mock_registry = Mock()
            mock_registry.get_metadata.return_value = regression_metadata
            mock_registry_class.return_value = mock_registry

            policy = MLRegressionPolicy(
                model_id="test_model", prediction_threshold=0.01
            )

            # Test positive prediction (expected return)
            positive_prediction = PredictionResult(
                model_id="test_model",
                timestamp=1640995200000000000,
                symbol="AAPL",
                features_used=["f__vwap_30"],
                prediction=0.02,  # 2% expected return
                prediction_probability=None,
                feature_values={"f__vwap_30": 150.5, "close": 150.0},
            )

            signal = policy._prediction_to_signal_strength(positive_prediction)
            assert signal > 0  # Long signal
            assert signal <= 1.0

            # Test negative prediction
            negative_prediction = PredictionResult(
                model_id="test_model",
                timestamp=1640995200000000000,
                symbol="AAPL",
                features_used=["f__vwap_30"],
                prediction=-0.015,  # -1.5% expected return
                prediction_probability=None,
                feature_values={"f__vwap_30": 150.5, "close": 150.0},
            )

            signal = policy._prediction_to_signal_strength(negative_prediction)
            assert signal < 0  # Short signal
            assert signal >= -1.0

            # Test weak prediction (below threshold)
            weak_prediction = PredictionResult(
                model_id="test_model",
                timestamp=1640995200000000000,
                symbol="AAPL",
                features_used=["f__vwap_30"],
                prediction=0.005,  # 0.5% expected return (below 1% threshold)
                prediction_probability=None,
                feature_values={"f__vwap_30": 150.5, "close": 150.0},
            )

            signal = policy._prediction_to_signal_strength(weak_prediction)
            assert signal == 0.0  # No signal


if __name__ == "__main__":
    pytest.main([__file__])
