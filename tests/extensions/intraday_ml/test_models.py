"""Tests for ML model functionality."""

from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry
from extensions.intraday_ml_models.schemas import ModelConfig, ModelType
from extensions.intraday_ml_models.trainers import MLModelTrainer


@pytest.fixture
def sample_bars():
    """Create sample bar data with features."""
    np.random.seed(42)
    n_samples = 1000

    data = {
        "ts": pd.date_range("2024-01-01", periods=n_samples, freq="1min").astype(
            np.int64
        ),
        "symbol": ["AAPL"] * n_samples,
        "open": 150.0 + np.random.randn(n_samples) * 2,
        "high": 152.0 + np.random.randn(n_samples) * 2,
        "low": 148.0 + np.random.randn(n_samples) * 2,
        "close": 150.0 + np.random.randn(n_samples) * 2,
        "volume": 1000000 + np.random.randn(n_samples) * 100000,
        "f__vwap_30": 150.0 + np.random.randn(n_samples) * 1,
        "f__rel_volume_30": 1.0 + np.random.randn(n_samples) * 0.3,
        "f__atr_14": 2.0 + np.random.randn(n_samples) * 0.5,
    }

    return pd.DataFrame(data)


@pytest.fixture
def temp_registry_dir(tmp_path):
    """Create temporary registry directory."""
    return str(tmp_path / "test_registry")


class TestMLModelRegistry:
    """Test ML model registry functionality."""

    def test_registry_initialization(self, temp_registry_dir):
        """Test registry initialization."""
        registry = MLModelRegistry(temp_registry_dir)
        assert registry.registry_dir.exists()
        assert registry.models_dir.exists()
        assert isinstance(registry._registry, dict)

    def test_register_and_load_model(self, temp_registry_dir, sample_bars):
        """Test model registration and loading."""
        from sklearn.ensemble import RandomForestClassifier

        from extensions.intraday_ml_models.schemas import (
            FeatureImportance,
            ModelMetadata,
        )

        registry = MLModelRegistry(temp_registry_dir)

        # Create and train a simple model
        model = RandomForestClassifier(n_estimators=5, random_state=42)
        features = ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        X = sample_bars[features].iloc[:500]

        # Create binary target with proper alignment
        target_series = (sample_bars["close"].pct_change().shift(-5) > 0.01).astype(int)
        y = target_series.iloc[:500].dropna()
        X = X.loc[y.index]  # Align features with target

        model.fit(X, y)

        # Create metadata
        metadata = ModelMetadata(
            model_id="test_model",
            model_type=ModelType.CLASSIFICATION,
            model_class="RandomForestClassifier",
            training_date=pd.Timestamp.now(),
            features=features,
            target_column="close",
            train_samples=len(X),
            val_samples=len(y) // 4,
            test_samples=len(y) // 4,
            train_score=0.7,
            val_score=0.65,
            test_score=0.68,
            feature_importance=[
                FeatureImportance(feature_name=f, importance=0.3, rank=1)
                for f in features
            ],
            random_seed=42,
            data_hash="test_hash",
            model_hash="model_hash",
        )

        # Register model
        registry.register_model(model, metadata)

        # Verify registration
        assert "test_model" in registry._registry
        assert registry.get_metadata("test_model") == metadata

        # Load model
        loaded_model = registry.load_model("test_model")
        assert isinstance(loaded_model, RandomForestClassifier)

    def test_list_models(self, temp_registry_dir):
        """Test model listing functionality."""
        registry = MLModelRegistry(temp_registry_dir)

        # Initially empty
        assert registry.list_models() == []

        # Add models with different types (mock metadata)
        mock_metadata = Mock()
        mock_metadata.model_type.value = "classification"
        mock_metadata.training_date = pd.Timestamp.now()

        registry._registry["model1"] = mock_metadata
        registry._registry["model2"] = mock_metadata

        # List all models
        all_models = registry.list_models()
        assert len(all_models) == 2

        # Filter by type
        classification_models = registry.list_models(model_type="classification")
        assert len(classification_models) == 2

        regression_models = registry.list_models(model_type="regression")
        assert len(regression_models) == 0


class TestMLModelTrainer:
    """Test ML model trainer functionality."""

    @pytest.fixture
    def trainer(self, temp_registry_dir):
        """Create trainer instance."""
        return MLModelTrainer(MLModelRegistry(temp_registry_dir))

    @pytest.fixture
    def sample_config(self):
        """Create sample model configuration."""
        return ModelConfig(
            model_type=ModelType.CLASSIFICATION,
            model_class="RandomForestClassifier",
            features=["f__vwap_30", "f__rel_volume_30", "f__atr_14"],
            target_column="close",
            prediction_horizon_bars=5,
            random_seed=42,
        )

    def test_prepare_training_data(self, trainer, sample_bars, sample_config):
        """Test training data preparation."""
        features_df, target_series = trainer.prepare_training_data(
            sample_bars, sample_config
        )

        # Verify features
        assert list(features_df.columns) == sample_config.features
        assert len(features_df) == len(target_series)

        # Verify target is forward-looking
        assert target_series.name == "close_forward_5_ret"

        # Check that NaN values are handled
        valid_mask = target_series.notna()
        assert len(features_df) == valid_mask.sum()

    def test_train_model(self, trainer, sample_bars, sample_config):
        """Test model training."""
        # Add binary classification target for testing
        sample_bars_with_target = sample_bars.copy()
        # Create simple classification target: 1 if price goes up > 1%, 0 otherwise
        sample_bars_with_target["classification_target"] = (
            sample_bars["close"].pct_change().shift(-5) > 0.01
        ).astype(int)

        # Update config to use classification target
        classification_config = ModelConfig(
            model_type=ModelType.CLASSIFICATION,
            model_class="RandomForestClassifier",
            features=["f__vwap_30", "f__rel_volume_30", "f__atr_14"],
            target_column="classification_target",
            prediction_horizon_bars=5,
            random_seed=42,
        )

        # Train model
        metadata = trainer.train_model(
            sample_bars_with_target, classification_config, model_id="test_train"
        )

        # Verify metadata
        assert metadata.model_id == "test_train"
        assert metadata.model_type == ModelType.CLASSIFICATION
        assert metadata.features == classification_config.features
        assert metadata.train_samples > 0
        assert 0 <= metadata.val_score <= 1

        # Verify model is registered
        assert metadata.model_id in trainer.registry._registry

        # Verify model can be loaded
        loaded_model = trainer.registry.load_model(metadata.model_id)
        assert loaded_model is not None


class TestMLPredictor:
    """Test ML predictor functionality."""

    @pytest.fixture
    def predictor(self, temp_registry_dir):
        """Create predictor instance."""
        return MLPredictor(MLModelRegistry(temp_registry_dir))

    @pytest.fixture
    def trained_model(self, predictor, sample_bars):
        """Create a trained model for testing."""
        from sklearn.ensemble import RandomForestClassifier

        from extensions.intraday_ml_models.schemas import (
            FeatureImportance,
            ModelMetadata,
        )

        # Train simple model
        model = RandomForestClassifier(n_estimators=5, random_state=42)
        features = ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        X = sample_bars[features].iloc[:500]

        # Create binary target with proper alignment
        target_series = (sample_bars["close"].pct_change().shift(-5) > 0.01).astype(int)
        y = target_series.iloc[:500].dropna()
        X = X.loc[y.index]  # Align features with target

        model.fit(X, y)

        # Create metadata
        metadata = ModelMetadata(
            model_id="test_predict_model",
            model_type=ModelType.CLASSIFICATION,
            model_class="RandomForestClassifier",
            training_date=pd.Timestamp.now(),
            features=features,
            target_column="close",
            train_samples=len(X),
            val_samples=len(y) // 4,
            test_samples=len(y) // 4,
            train_score=0.7,
            val_score=0.65,
            test_score=0.68,
            feature_importance=[
                FeatureImportance(feature_name=f, importance=0.3, rank=1)
                for f in features
            ],
            random_seed=42,
            data_hash="test_hash",
            model_hash="model_hash",
        )

        # Register model
        predictor.registry.register_model(model, metadata)

        return metadata.model_id

    def test_predict_single(self, predictor, sample_bars, trained_model):
        """Test single prediction."""
        features = {"f__vwap_30": 150.5, "f__rel_volume_30": 1.2, "f__atr_14": 2.1}

        result = predictor.predict_single(
            model_id=trained_model,
            features=features,
            timestamp=1640995200000000000,  # 2022-01-01 00:00:00 UTC in ns
            symbol="AAPL",
            return_probability=True,
        )

        # Verify result structure
        assert result.model_id == trained_model
        assert result.symbol == "AAPL"
        assert result.prediction in [0, 1]  # Binary classification
        assert len(result.feature_values) == 3
        assert all(f in result.feature_values for f in features.keys())

    def test_predict_batch(self, predictor, sample_bars, trained_model):
        """Test batch prediction."""
        # Use subset of features for prediction
        features_df = sample_bars[["f__vwap_30", "f__rel_volume_30", "f__atr_14"]].iloc[
            :10
        ]

        results = predictor.predict(
            model_id=trained_model,
            features=features_df,
            timestamps=sample_bars["ts"].iloc[:10],
            symbols=sample_bars["symbol"].iloc[:10],
            return_probabilities=True,
        )

        # Verify results
        assert len(results) == 10
        for result in results:
            assert result.model_id == trained_model
            assert result.prediction in [0, 1]
            assert len(result.feature_values) == 3

    def test_feature_validation(self, predictor, trained_model):
        """Test feature validation."""
        # Missing features
        incomplete_features = {"f__vwap_30": 150.5}

        with pytest.raises(ValueError, match="Missing required features"):
            predictor.predict_single(
                model_id=trained_model,
                features=incomplete_features,
                timestamp=1640995200000000000,
                symbol="AAPL",
            )

        # NaN features
        nan_features = {"f__vwap_30": np.nan, "f__rel_volume_30": 1.2, "f__atr_14": 2.1}

        with pytest.raises(ValueError, match="Features contain NaN"):
            predictor.predict_single(
                model_id=trained_model,
                features=nan_features,
                timestamp=1640995200000000000,
                symbol="AAPL",
            )


if __name__ == "__main__":
    pytest.main([__file__])
