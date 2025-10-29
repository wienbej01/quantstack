"""Tests for ML monitoring functionality."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest
from extensions.intraday_ml_monitoring.metrics import (
    MetricsCalculator,
    PerformanceMetrics,
)
from extensions.intraday_ml_monitoring.validator import DriftDetector, ModelValidator


@pytest.fixture
def sample_predictions():
    """Create sample prediction data."""
    dates = pd.date_range("2024-01-01", periods=100, freq="1min")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "symbol": "AAPL",
            "prediction": np.random.normal(0.001, 0.01, 100),
            "prediction_probability": np.random.uniform(0.6, 0.9, 100),
            "actual": np.random.normal(0.001, 0.012, 100),
            "features_used": [["f__vwap_30", "f__rel_volume_30"]] * 100,
            "feature_values": [{"f__vwap_30": 150.5, "f__rel_volume_30": 1.2}] * 100,
        }
    )


@pytest.fixture
def sample_feature_data():
    """Create sample feature data."""
    dates = pd.date_range("2024-01-01", periods=200, freq="1min")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "f__vwap_30": np.random.normal(150, 5, 200),
            "f__rel_volume_30": np.random.normal(1.0, 0.3, 200),
            "f__atr_14": np.random.normal(2.0, 0.5, 200),
            "close": np.random.normal(150, 5, 200),
        }
    )


class TestPerformanceMetrics:
    """Test performance metrics dataclass."""

    def test_performance_metrics_creation(self):
        """Test PerformanceMetrics creation."""
        metrics = PerformanceMetrics(
            total_predictions=100,
            prediction_rate=0.95,
            avg_confidence=0.75,
            mse=0.001,
            mae=0.02,
            r2=0.85,
        )

        assert metrics.total_predictions == 100
        assert metrics.prediction_rate == 0.95
        assert metrics.avg_confidence == 0.75
        assert metrics.mse == 0.001
        assert metrics.mae == 0.02
        assert metrics.r2 == 0.85

    def test_performance_metrics_to_dict(self):
        """Test PerformanceMetrics to_dict conversion."""
        metrics = PerformanceMetrics(
            total_predictions=100, prediction_rate=0.95, avg_confidence=0.75
        )

        result_dict = metrics.to_dict()
        assert isinstance(result_dict, dict)
        assert result_dict["total_predictions"] == 100
        assert result_dict["prediction_rate"] == 0.95


class TestMetricsCalculator:
    """Test metrics calculator."""

    def setup_method(self):
        """Set up test environment."""
        self.calculator = MetricsCalculator()

    def test_calculate_regression_metrics(self, sample_predictions):
        """Test regression metrics calculation."""
        metrics = self.calculator.calculate_regression_metrics(
            predictions=sample_predictions["prediction"],
            actuals=sample_predictions["actual"],
        )

        assert "mse" in metrics
        assert "mae" in metrics
        assert "r2" in metrics
        assert "explained_variance" in metrics
        assert isinstance(metrics["mse"], float)
        assert metrics["mse"] >= 0

    def test_calculate_classification_metrics(self):
        """Test classification metrics calculation."""
        # Create binary classification data
        predictions = np.array([0, 1, 1, 0, 1, 0, 1, 1, 0, 0])
        actuals = np.array([0, 1, 0, 0, 1, 0, 1, 1, 1, 0])
        probabilities = np.array([0.3, 0.8, 0.7, 0.2, 0.9, 0.1, 0.6, 0.8, 0.4, 0.3])

        metrics = self.calculator.calculate_classification_metrics(
            predictions=predictions, actuals=actuals, probabilities=probabilities
        )

        assert "accuracy" in metrics
        assert "precision" in metrics
        assert "recall" in metrics
        assert "f1" in metrics
        assert "roc_auc" in metrics
        assert 0 <= metrics["accuracy"] <= 1

    def test_calculate_rolling_metrics(self, sample_predictions):
        """Test rolling metrics calculation."""
        rolling_metrics = self.calculator.calculate_rolling_metrics(
            predictions=sample_predictions["prediction"],
            actuals=sample_predictions["actual"],
            window=20,
        )

        assert isinstance(rolling_metrics, pd.DataFrame)
        assert len(rolling_metrics) == len(sample_predictions) - 19  # Rolling window
        assert "rolling_mse" in rolling_metrics.columns
        assert "rolling_mae" in rolling_metrics.columns

    def test_calculate_feature_coverage(self, sample_predictions):
        """Test feature coverage calculation."""
        coverage = self.calculator.calculate_feature_coverage(sample_predictions)

        assert isinstance(coverage, dict)
        assert "f__vwap_30" in coverage
        assert "f__rel_volume_30" in coverage
        assert all(0 <= cov <= 1 for cov in coverage.values())

    def test_calculate_uncertainty_metrics(self, sample_predictions):
        """Test uncertainty metrics calculation."""
        uncertainty = self.calculator.calculate_uncertainty_metrics(
            probabilities=sample_predictions["prediction_probability"],
            predictions=sample_predictions["prediction"],
        )

        assert isinstance(uncertainty, dict)
        assert "avg_confidence" in uncertainty
        assert "confidence_std" in uncertainty
        assert "low_confidence_ratio" in uncertainty
        assert 0 <= uncertainty["avg_confidence"] <= 1


class TestModelValidator:
    """Test model validator."""

    def setup_method(self):
        """Set up test environment."""
        self.validator = ModelValidator()

    def test_validate_model_consistency(self):
        """Test model consistency validation."""
        # Mock model metadata
        mock_metadata = Mock()
        mock_metadata.features = ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        mock_metadata.hyperparameters = {"n_estimators": 100, "max_depth": 10}

        # Current model configuration
        current_config = {
            "features": ["f__vwap_30", "f__rel_volume_30", "f__atr_14"],
            "hyperparameters": {"n_estimators": 100, "max_depth": 10},
        }

        result = self.validator.validate_model_consistency(
            mock_metadata, current_config
        )

        assert isinstance(result, dict)
        assert "is_valid" in result
        assert "issues" in result
        assert result["is_valid"] is True
        assert len(result["issues"]) == 0

    def test_validate_model_consistency_with_issues(self):
        """Test model consistency validation with issues."""
        # Mock model metadata
        mock_metadata = Mock()
        mock_metadata.features = ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        mock_metadata.hyperparameters = {"n_estimators": 100, "max_depth": 10}

        # Current model configuration with mismatch
        current_config = {
            "features": ["f__vwap_30", "f__rel_volume_30"],  # Missing feature
            "hyperparameters": {
                "n_estimators": 200,
                "max_depth": 10,
            },  # Different hyperparameter
        }

        result = self.validator.validate_model_consistency(
            mock_metadata, current_config
        )

        assert result["is_valid"] is False
        assert len(result["issues"]) > 0

    def test_validate_feature_importance(self):
        """Test feature importance validation."""
        feature_importance = {
            "f__vwap_30": 0.4,
            "f__rel_volume_30": 0.3,
            "f__atr_14": 0.2,
            "f__close": 0.1,
        }

        result = self.validator.validate_feature_importance(feature_importance)

        assert isinstance(result, dict)
        assert "top_features" in result
        assert "importance_distribution" in result
        assert "total_importance" in result
        assert result["total_importance"] == pytest.approx(1.0, rel=1e-10)

    def test_validate_prediction_distribution(self, sample_predictions):
        """Test prediction distribution validation."""
        result = self.validator.validate_prediction_distribution(
            predictions=sample_predictions["prediction"]
        )

        assert isinstance(result, dict)
        assert "mean" in result
        assert "std" in result
        assert "min" in result
        assert "max" in result
        assert "outliers" in result


class TestDriftDetector:
    """Test drift detector."""

    def setup_method(self):
        """Set up test environment."""
        self.detector = DriftDetector()

    def test_detect_feature_drift_no_drift(self, sample_feature_data):
        """Test feature drift detection with no drift."""
        # Split data into reference and current (same distribution)
        reference_data = sample_feature_data.iloc[:100]
        current_data = sample_feature_data.iloc[100:200]

        features = ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        result = self.detector.detect_feature_drift(
            reference_data=reference_data,
            current_data=current_data,
            features=features,
            threshold=0.05,
        )

        assert isinstance(result, dict)
        assert "drift_detected" in result
        assert "feature_drift" in result
        assert isinstance(result["feature_drift"], dict)
        for feature in features:
            assert feature in result["feature_drift"]

    def test_detect_feature_drift_with_drift(self, sample_feature_data):
        """Test feature drift detection with actual drift."""
        # Create reference data
        reference_data = sample_feature_data.iloc[:100].copy()

        # Create current data with drift (shifted distribution)
        current_data = sample_feature_data.iloc[100:200].copy()
        current_data["f__vwap_30"] += 10  # Add significant shift
        current_data["f__rel_volume_30"] *= 2  # Double the values

        features = ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        result = self.detector.detect_feature_drift(
            reference_data=reference_data,
            current_data=current_data,
            features=features,
            threshold=0.05,
        )

        assert isinstance(result, dict)
        # Should detect drift in at least some features
        assert any(
            result["feature_drift"][feature]["drift_detected"] for feature in features
        )

    def test_detect_target_drift(self):
        """Test target drift detection."""
        # Create reference and current target data
        reference_targets = np.random.normal(0, 1, 1000)
        current_targets = np.random.normal(0.5, 1, 1000)  # Shifted distribution

        result = self.detector.detect_target_drift(
            reference_targets=reference_targets,
            current_targets=current_targets,
            threshold=0.05,
        )

        assert isinstance(result, dict)
        assert "drift_detected" in result
        assert "p_value" in result
        assert "effect_size" in result
        assert "test_statistic" in result

    def test_calculate_population_stability_index(self):
        """Test Population Stability Index calculation."""
        # Create two distributions
        reference_data = np.random.normal(0, 1, 1000)
        current_data = np.random.normal(0.1, 1, 1000)  # Small shift

        psi = self.detector.calculate_population_stability_index(
            reference_data, current_data, bins=10
        )

        assert isinstance(psi, float)
        assert psi >= 0

    def test_detect_concept_drift(self, sample_predictions):
        """Test concept drift detection."""
        # Create predictions and actuals with concept drift
        predictions = sample_predictions["prediction"].values
        actuals = sample_predictions["actual"].values

        # Introduce concept drift in second half
        actuals[50:] += 0.01  # Add systematic bias

        result = self.detector.detect_concept_drift(
            predictions=predictions, actuals=actuals, window=25, threshold=0.05
        )

        assert isinstance(result, dict)
        assert "drift_detected" in result
        assert "drift_points" in result
        assert "performance_degradation" in result


if __name__ == "__main__":
    pytest.main([__file__])
