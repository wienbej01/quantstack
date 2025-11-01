"""Integration tests for Sprint 9 ML functionality."""

import pathlib
import tempfile

import numpy as np
import pandas as pd
import pytest
import yaml
from extensions.intraday_ml_monitoring.metrics import MetricsCalculator
from extensions.intraday_ml_monitoring.validator import ModelValidator

from extensions.intraday_ml_features.pipeline import FeaturePipeline
from extensions.intraday_ml_features.selection import FeatureSelector


@pytest.fixture
def sample_intraday_data():
    """Create realistic intraday data for testing."""
    dates = pd.date_range(
        "2024-01-01 09:30:00", periods=390, freq="1min"
    )  # One trading day
    np.random.seed(42)  # For reproducible tests

    # Simulate price movement with trend and volatility
    base_price = 150.0
    returns = np.random.normal(0.0001, 0.001, 390)
    prices = [base_price]
    for ret in returns:
        prices.append(prices[-1] * (1 + ret))

    prices = prices[1:]  # Remove initial price

    # Create realistic features
    data = pd.DataFrame(
        {
            "timestamp": dates,
            "close": prices,
            "volume": np.random.lognormal(14, 0.5, 390),
            "open": np.array(prices) * (1 + np.random.normal(0, 0.001, 390)),
            "high": np.array(prices) * (1 + np.abs(np.random.normal(0, 0.002, 390))),
            "low": np.array(prices) * (1 - np.abs(np.random.normal(0, 0.002, 390))),
        }
    ).set_index("timestamp")

    # Add VWAP and other features
    data["f__vwap_30"] = data["close"].rolling(30).mean()
    data["f__rel_volume_30"] = data["volume"] / data["volume"].rolling(30).mean()
    data["f__atr_14"] = data["high"] - data["low"]  # Simplified ATR
    data["f__vwap_distance"] = (data["close"] - data["f__vwap_30"]) / data["f__vwap_30"]
    data["f__price_position"] = (data["close"] - data["low"]) / (
        data["high"] - data["low"]
    )

    return data.dropna()


@pytest.fixture
def sample_config():
    """Create sample configuration for testing."""
    return {
        "model_type": "regression",
        "model_class": "RandomForestRegressor",
        "hyperparameters": {
            "n_estimators": 50,
            "max_depth": 8,
            "min_samples_split": 5,
            "random_state": 42,
        },
        "features": [
            "f__vwap_30",
            "f__rel_volume_30",
            "f__atr_14",
            "f__vwap_distance",
            "f__price_position",
        ],
        "target_column": "close",
        "prediction_horizon_bars": 3,
        "training": {
            "train_test_split": 0.2,
            "random_seed": 42,
            "scale_features": True,
            "feature_selection": True,
        },
    }


class TestEndToEndWorkflow:
    """Test end-to-end ML workflow."""

    def test_complete_feature_engineering_pipeline(self, sample_intraday_data):
        """Test complete feature engineering pipeline."""
        # Create target variable (future returns)
        target = sample_intraday_data["close"].pct_change(3).shift(-3).dropna()
        features = sample_intraday_data.iloc[:-3]  # Align with target

        # Initialize feature pipeline
        pipeline = FeaturePipeline()
        pipeline.add_scaling_step(method="robust")
        pipeline.add_feature_selection_step(method="mutual_info", k=3)

        # Fit and transform
        engineered_features = pipeline.fit_transform(features, target)

        # Verify results
        assert isinstance(engineered_features, pd.DataFrame)
        assert len(engineered_features) == len(target)
        assert len(engineered_features.columns) <= 3  # Feature selection limit
        assert pipeline.fitted is True

        # Test transform on new data
        new_features = pipeline.transform(features.tail(10))
        assert len(new_features) == 10
        assert len(new_features.columns) == len(engineered_features.columns)

    def test_feature_selection_integration(self, sample_intraday_data):
        """Test feature selection integration."""
        # Prepare data
        features = sample_intraday_data.drop(
            columns=["close", "open", "high", "low", "volume"]
        )
        target = sample_intraday_data["close"].pct_change(3).shift(-3).dropna()
        features = features.iloc[:-3]

        # Test multiple selection methods
        selector = FeatureSelector()

        # Univariate selection
        result_univariate = selector.select_univariate(
            X=features, y=target, method="k_best", k=3
        )

        # Mutual information selection
        result_mutual = selector.select_mutual_info(X=features, y=target, k=3)

        # RFE selection
        result_rfe = selector.select_rfe(X=features, y=target, n_features=3)

        # Verify all methods return results
        for result in [result_univariate, result_mutual, result_rfe]:
            assert isinstance(result, type(result_univariate))  # Same type
            assert len(result.selected_features) == 3
            assert len(result.feature_scores) == len(features.columns)

    def test_monitoring_integration(self, sample_intraday_data):
        """Test monitoring integration with realistic data."""
        # Create realistic predictions
        predictions = np.random.normal(0.001, 0.002, len(sample_intraday_data))
        actuals = sample_intraday_data["close"].pct_change().fillna(0)
        probabilities = np.random.beta(
            2, 2, len(sample_intraday_data)
        )  # Realistic confidence distribution

        # Test metrics calculation
        calculator = MetricsCalculator()

        # Regression metrics
        reg_metrics = calculator.calculate_regression_metrics(predictions, actuals)
        assert all(key in reg_metrics for key in ["mse", "mae", "r2"])
        assert reg_metrics["mse"] >= 0

        # Rolling metrics
        rolling_metrics = calculator.calculate_rolling_metrics(
            predictions, actuals, window=30
        )
        assert isinstance(rolling_metrics, pd.DataFrame)
        assert "rolling_mse" in rolling_metrics.columns

        # Uncertainty metrics
        uncertainty = calculator.calculate_uncertainty_metrics(
            probabilities, predictions
        )
        assert "avg_confidence" in uncertainty
        assert 0 <= uncertainty["avg_confidence"] <= 1

    def test_model_validation_integration(self, sample_intraday_data):
        """Test model validation integration."""
        validator = ModelValidator()

        # Test feature importance validation
        feature_importance = {
            "f__vwap_30": 0.35,
            "f__rel_volume_30": 0.25,
            "f__atr_14": 0.20,
            "f__vwap_distance": 0.15,
            "f__price_position": 0.05,
        }

        importance_result = validator.validate_feature_importance(feature_importance)
        assert importance_result["total_importance"] == pytest.approx(1.0, rel=1e-10)
        assert len(importance_result["top_features"]) == 5

        # Test prediction distribution validation
        predictions = np.random.normal(0.001, 0.002, 1000)
        dist_result = validator.validate_prediction_distribution(predictions)
        assert "mean" in dist_result
        assert "std" in dist_result
        assert "outliers" in dist_result

    def test_drift_detection_integration(self, sample_intraday_data):
        """Test drift detection integration."""
        # Split data for drift testing
        split_point = len(sample_intraday_data) // 2
        reference_data = sample_intraday_data.iloc[:split_point]
        current_data = sample_intraday_data.iloc[split_point:]

        # Add drift to current data
        current_data_drifted = current_data.copy()
        current_data_drifted["f__vwap_30"] += 5.0  # Significant shift

        # Test feature drift detection
        validator = ModelValidator()
        features_to_check = ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]

        drift_result = validator.detect_feature_drift(
            reference_data=reference_data,
            current_data=current_data_drifted,
            features=features_to_check,
            threshold=0.05,
        )

        assert isinstance(drift_result, dict)
        assert "drift_detected" in drift_result
        assert "feature_drift" in drift_result

        # Should detect drift in f__vwap_30 due to the 5-point shift
        assert drift_result["feature_drift"]["f__vwap_30"]["drift_detected"] is True


class TestConfigurationIntegration:
    """Test configuration integration."""

    def test_experiment_config_loading(self, sample_config):
        """Test loading and validating experiment configuration."""
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(sample_config, f)
            config_path = f.name

        try:
            # Load and validate config
            with open(config_path) as f:
                loaded_config = yaml.safe_load(f)

            # Verify required fields
            assert "model_type" in loaded_config
            assert "model_class" in loaded_config
            assert "hyperparameters" in loaded_config
            assert "features" in loaded_config
            assert "training" in loaded_config

            # Validate data types
            assert isinstance(loaded_config["features"], list)
            assert isinstance(loaded_config["hyperparameters"], dict)
            assert len(loaded_config["features"]) > 0

        finally:
            pathlib.Path(config_path).unlink()

    def test_monitoring_config_validation(self):
        """Test monitoring configuration validation."""
        monitoring_config = {
            "monitoring_config": {
                "name": "test_monitor",
                "models": {"include_models": ["test_model"]},
                "metrics": {"regression": {"primary": ["mse", "mae", "r2"]}},
                "drift_detection": {
                    "enable": True,
                    "thresholds": {"ks_test": 0.05, "kl_divergence": 0.1},
                },
                "alerts": {
                    "enable": True,
                    "thresholds": {"performance_degradation": 0.1},
                },
            }
        }

        # Validate configuration structure
        assert "monitoring_config" in monitoring_config
        config = monitoring_config["monitoring_config"]

        # Check required sections
        required_sections = ["models", "metrics", "drift_detection", "alerts"]
        for section in required_sections:
            assert section in config, f"Missing required section: {section}"

        # Validate metrics configuration
        assert "regression" in config["metrics"]
        assert isinstance(config["metrics"]["regression"]["primary"], list)

        # Validate drift detection thresholds
        assert isinstance(config["drift_detection"]["thresholds"], dict)
        assert "ks_test" in config["drift_detection"]["thresholds"]

    def test_features_config_validation(self):
        """Test features configuration validation."""
        features_config = {
            "feature_config": {
                "name": "advanced_features",
                "base_features": ["f__vwap_30", "f__rel_volume_30", "f__atr_14"],
                "lag_features": {"enable": True, "lags": [1, 2, 3]},
                "rolling_features": {
                    "enable": True,
                    "windows": [5, 10, 20],
                    "functions": ["mean", "std"],
                },
                "scaling": {"enable": True, "method": "robust"},
                "feature_selection": {"enable": True, "method": "mutual_info", "k": 15},
            }
        }

        # Validate configuration
        config = features_config["feature_config"]

        # Check required sections
        required_sections = ["base_features", "scaling", "feature_selection"]
        for section in required_sections:
            assert section in config, f"Missing required section: {section}"

        # Validate base features
        assert isinstance(config["base_features"], list)
        assert len(config["base_features"]) > 0

        # Validate optional features
        if config["lag_features"]["enable"]:
            assert isinstance(config["lag_features"]["lags"], list)

        if config["rolling_features"]["enable"]:
            assert isinstance(config["rolling_features"]["windows"], list)
            assert isinstance(config["rolling_features"]["functions"], list)


class TestPerformanceRequirements:
    """Test performance requirements and constraints."""

    def test_intraday_compliance_no_future_leak(self, sample_intraday_data):
        """Test that no future data is used in feature engineering."""
        # Test lag transformer
        lag_transformer = LagTransformer(lags=[1, 2, 3])
        lag_transformer.fit(sample_intraday_data)
        lagged_data = lag_transformer.transform(sample_intraday_data)

        # Verify lagged data doesn't contain future information
        for col in lagged_data.columns:
            if "_lag_1" in col:
                # First value should be NaN (or filled) due to lag
                assert (
                    pd.isna(lagged_data[col].iloc[0])
                    or lagged_data[col].iloc[0]
                    == sample_intraday_data[col.replace("_lag_1", "")].iloc[0]
                )

    def test_intraday_compliance_next_bar_execution(self, sample_intraday_data):
        """Test that predictions are made for next bar execution."""
        # Create target for next bar
        next_returns = sample_intraday_data["close"].pct_change().shift(-1).dropna()

        # Verify target length
        assert len(next_returns) == len(sample_intraday_data) - 1

        # Verify no NaN values in the middle
        assert not next_returns.iloc[:-1].isna().any()

    def test_memory_efficiency_large_dataset(self):
        """Test memory efficiency with larger datasets."""
        # Create larger dataset
        dates = pd.date_range("2024-01-01", periods=10000, freq="1min")
        large_data = pd.DataFrame(
            {
                "timestamp": dates,
                "feature1": np.random.normal(0, 1, 10000),
                "feature2": np.random.normal(0, 1, 10000),
                "feature3": np.random.normal(0, 1, 10000),
            }
        ).set_index("timestamp")

        # Test feature pipeline on large dataset
        pipeline = FeaturePipeline()
        pipeline.add_scaling_step(method="standard")

        # Should handle large dataset without memory issues
        result = pipeline.fit_transform(large_data)

        assert len(result) == 10000
        assert isinstance(result, pd.DataFrame)

    def test_reproducibility_with_seed(self, sample_intraday_data):
        """Test reproducibility with random seed."""
        # Set seed for reproducible results
        np.random.seed(42)

        # Create feature selector
        selector = FeatureSelector()
        target = sample_intraday_data["close"].pct_change(3).shift(-3).dropna()
        features = sample_intraday_data.drop(
            columns=["close", "open", "high", "low", "volume"]
        ).iloc[:-3]

        # Run selection twice with same seed
        result1 = selector.select_mutual_info(
            X=features, y=target, k=3, random_state=42
        )
        result2 = selector.select_mutual_info(
            X=features, y=target, k=3, random_state=42
        )

        # Results should be identical
        assert result1.selected_features == result2.selected_features
        assert np.allclose(
            [result1.feature_scores[f] for f in result1.selected_features],
            [result2.feature_scores[f] for f in result2.selected_features],
        )


if __name__ == "__main__":
    pytest.main([__file__])
