"""Tests for advanced feature engineering functionality."""

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_features.pipeline import FeaturePipeline
from extensions.intraday_ml_features.selection import FeatureSelector, SelectionResult
from extensions.intraday_ml_features.transforms import (
    BinningTransformer,
    DifferenceTransformer,
    InteractionTransformer,
    LagTransformer,
    RollingTransformer,
    TechnicalIndicatorTransformer,
)


@pytest.fixture
def sample_feature_data():
    """Create sample feature data."""
    dates = pd.date_range("2024-01-01", periods=100, freq="1min")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "f__vwap_30": np.random.normal(150, 5, 100),
            "f__rel_volume_30": np.random.normal(1.0, 0.3, 100),
            "f__atr_14": np.random.normal(2.0, 0.5, 100),
            "close": np.random.normal(150, 5, 100),
            "volume": np.random.normal(1000000, 200000, 100),
            "high": np.random.normal(152, 5, 100),
            "low": np.random.normal(148, 5, 100),
            "open": np.random.normal(150, 5, 100),
        }
    ).set_index("timestamp")


@pytest.fixture
def sample_target_data():
    """Create sample target data."""
    return pd.Series(np.random.normal(0.001, 0.01, 100), name="target")


class TestFeaturePipeline:
    """Test feature engineering pipeline."""

    def setup_method(self):
        """Set up test environment."""
        self.pipeline = FeaturePipeline()

    def test_pipeline_initialization(self):
        """Test pipeline initialization."""
        assert self.pipeline.scalers == {}
        assert self.pipeline.pca is None
        assert self.pipeline.feature_selector is None
        assert not self.pipeline.fitted

    def test_add_scaling_step(self):
        """Test adding scaling step to pipeline."""
        self.pipeline.add_scaling_step(method="standard")
        assert "scaling" in self.pipeline.steps
        assert self.pipeline.steps["scaling"]["method"] == "standard"

    def test_add_pca_step(self):
        """Test adding PCA step to pipeline."""
        self.pipeline.add_pca_step(n_components=5)
        assert "pca" in self.pipeline.steps
        assert self.pipeline.steps["pca"]["n_components"] == 5

    def test_add_feature_selection_step(self):
        """Test adding feature selection step to pipeline."""
        self.pipeline.add_feature_selection_step(method="mutual_info", k=10)
        assert "feature_selection" in self.pipeline.steps
        assert self.pipeline.steps["feature_selection"]["method"] == "mutual_info"

    def test_fit_transform_pipeline(self, sample_feature_data, sample_target_data):
        """Test fitting and transforming pipeline."""
        # Add steps to pipeline
        self.pipeline.add_scaling_step(method="standard")
        self.pipeline.add_feature_selection_step(method="mutual_info", k=5)

        # Fit and transform
        result = self.pipeline.fit_transform(sample_feature_data, sample_target_data)

        assert isinstance(result, pd.DataFrame)
        assert len(result.columns) <= 5  # Feature selection should reduce features
        assert self.pipeline.fitted is True

    def test_transform_pipeline(self, sample_feature_data, sample_target_data):
        """Test transforming with fitted pipeline."""
        # Fit pipeline first
        self.pipeline.add_scaling_step(method="standard")
        self.pipeline.fit(sample_feature_data, sample_target_data)

        # Transform new data
        result = self.pipeline.transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(sample_feature_data)

    def test_pipeline_with_custom_transform(self, sample_feature_data):
        """Test pipeline with custom transform function."""

        def custom_transform(X):
            return X * 2

        self.pipeline.add_custom_transform(custom_transform, name="double_features")
        result = self.pipeline.fit_transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        # Values should be approximately doubled
        assert np.allclose(result.values, sample_feature_data.values * 2, rtol=1e-10)

    def test_get_feature_names(self, sample_feature_data, sample_target_data):
        """Test getting feature names from pipeline."""
        self.pipeline.add_scaling_step(method="standard")
        self.pipeline.fit(sample_feature_data, sample_target_data)

        feature_names = self.pipeline.get_feature_names()
        assert isinstance(feature_names, list)
        assert len(feature_names) == len(sample_feature_data.columns)


class TestFeatureSelector:
    """Test feature selector."""

    def setup_method(self):
        """Set up test environment."""
        self.selector = FeatureSelector()

    def test_select_univariate_regression(
        self, sample_feature_data, sample_target_data
    ):
        """Test univariate feature selection for regression."""
        result = self.selector.select_univariate(
            X=sample_feature_data,
            y=sample_target_data,
            method="k_best",
            k=3,
            task_type="regression",
        )

        assert isinstance(result, SelectionResult)
        assert len(result.selected_features) == 3
        assert len(result.feature_scores) == len(sample_feature_data.columns)
        assert result.selection_method == "univariate_k_best"

    def test_select_univariate_classification(
        self, sample_feature_data, sample_target_data
    ):
        """Test univariate feature selection for classification."""
        # Create binary target
        binary_target = (sample_target_data > 0).astype(int)

        result = self.selector.select_univariate(
            X=sample_feature_data,
            y=binary_target,
            method="percentile",
            percentile=50,
            task_type="classification",
        )

        assert isinstance(result, SelectionResult)
        assert len(result.selected_features) <= len(sample_feature_data.columns) // 2
        assert result.selection_method == "univariate_percentile"

    def test_select_mutual_info(self, sample_feature_data, sample_target_data):
        """Test mutual information feature selection."""
        result = self.selector.select_mutual_info(
            X=sample_feature_data, y=sample_target_data, k=4, task_type="regression"
        )

        assert isinstance(result, SelectionResult)
        assert len(result.selected_features) == 4
        assert result.selection_method == "mutual_info"

    def test_select_rfe(self, sample_feature_data, sample_target_data):
        """Test Recursive Feature Elimination."""
        result = self.selector.select_rfe(
            X=sample_feature_data,
            y=sample_target_data,
            n_features=3,
            task_type="regression",
        )

        assert isinstance(result, SelectionResult)
        assert len(result.selected_features) == 3
        assert "rfe_fixed" in result.selection_method

    def test_select_lasso(self, sample_feature_data, sample_target_data):
        """Test Lasso feature selection."""
        result = self.selector.select_lasso(
            X=sample_feature_data, y=sample_target_data, cv=3, max_features=5
        )

        assert isinstance(result, SelectionResult)
        assert len(result.selected_features) <= 5
        assert result.selection_method == "lasso"

    def test_select_correlation_filter(self, sample_feature_data):
        """Test correlation-based feature filtering."""
        # Add highly correlated feature
        sample_feature_data = sample_feature_data.copy()
        sample_feature_data["highly_correlated"] = sample_feature_data[
            "f__vwap_30"
        ] + np.random.normal(0, 0.1, len(sample_feature_data))

        result = self.selector.select_correlation_filter(
            X=sample_feature_data, threshold=0.95
        )

        assert isinstance(result, SelectionResult)
        # Should remove one of the highly correlated features
        assert len(result.selected_features) < len(sample_feature_data.columns)
        assert result.selection_method == "correlation_filter"

    def test_transform_with_fitted_selector(
        self, sample_feature_data, sample_target_data
    ):
        """Test transforming data with fitted selector."""
        # Fit selector
        self.selector.select_univariate(
            X=sample_feature_data, y=sample_target_data, method="k_best", k=3
        )

        # Transform data
        result = self.selector.transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        assert len(result.columns) == 3  # Should have only selected features
        assert len(result) == len(sample_feature_data)

    def test_get_selected_features(self, sample_feature_data, sample_target_data):
        """Test getting selected feature names."""
        self.selector.select_univariate(
            X=sample_feature_data, y=sample_target_data, method="k_best", k=3
        )

        selected_features = self.selector.get_selected_features()
        assert isinstance(selected_features, list)
        assert len(selected_features) == 3


class TestTransformers:
    """Test feature transformers."""

    def test_lag_transformer(self, sample_feature_data):
        """Test lag transformer."""
        transformer = LagTransformer(lags=[1, 2], fill_method="bfill")
        transformer.fit(sample_feature_data)

        result = transformer.transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        # Should have 2 lag features for each original feature
        expected_features = len(sample_feature_data.columns) * 2
        assert len(result.columns) == expected_features
        assert all("_lag_" in col for col in result.columns)

    def test_rolling_transformer(self, sample_feature_data):
        """Test rolling transformer."""
        transformer = RollingTransformer(windows=[5, 10], functions=["mean", "std"])
        transformer.fit(sample_feature_data)

        result = transformer.transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        # Should have 2 windows * 2 functions for each original feature
        expected_features = len(sample_feature_data.columns) * 2 * 2
        assert len(result.columns) == expected_features
        assert all("_roll_" in col for col in result.columns)

    def test_difference_transformer(self, sample_feature_data):
        """Test difference transformer."""
        transformer = DifferenceTransformer(periods=[1, 2])
        transformer.fit(sample_feature_data)

        result = transformer.transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        # Should have 2 difference features for each original feature
        expected_features = len(sample_feature_data.columns) * 2
        assert len(result.columns) == expected_features
        assert all("_diff_" in col for col in result.columns)

    def test_interaction_transformer(self, sample_feature_data, sample_target_data):
        """Test interaction transformer."""
        transformer = InteractionTransformer(max_features=5)
        transformer.fit(sample_feature_data, sample_target_data)

        result = transformer.transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        # Should have interaction features (multiply and divide for each pair)
        assert len(result.columns) <= 10  # 5 pairs * 2 operations
        assert any("_x_" in col or "_div_" in col for col in result.columns)

    def test_binning_transformer(self, sample_feature_data):
        """Test binning transformer."""
        transformer = BinningTransformer(n_bins=5, strategy="quantile")
        transformer.fit(sample_feature_data)

        result = transformer.transform(sample_feature_data)

        assert isinstance(result, pd.DataFrame)
        # Should have one-hot encoded bins
        assert len(result.columns) >= len(sample_feature_data.columns)

    def test_technical_indicator_transformer(self):
        """Test technical indicator transformer."""
        # Create OHLCV data
        dates = pd.date_range("2024-01-01", periods=100, freq="1min")
        ohlcv_data = pd.DataFrame(
            {
                "timestamp": dates,
                "open": np.random.normal(150, 5, 100),
                "high": np.random.normal(152, 5, 100),
                "low": np.random.normal(148, 5, 100),
                "close": np.random.normal(150, 5, 100),
                "volume": np.random.normal(1000000, 200000, 100),
            }
        ).set_index("timestamp")

        transformer = TechnicalIndicatorTransformer(indicators=["rsi", "macd"])
        transformer.fit(ohlcv_data)

        result = transformer.transform(ohlcv_data)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(ohlcv_data)
        # Should have RSI and MACD features
        assert any("rsi" in col for col in result.columns)
        assert any("macd" in col for col in result.columns)

    def test_transformer_with_datetime_index(self):
        """Test that transformers require datetime index."""
        # Create data with non-datetime index
        data = pd.DataFrame(
            {
                "feature1": np.random.normal(0, 1, 100),
                "feature2": np.random.normal(0, 1, 100),
            }
        )

        transformer = LagTransformer(lags=[1])

        # Should raise ValueError for non-datetime index when transforming
        with pytest.raises(ValueError, match="requires DatetimeIndex"):
            transformer.fit(data)
            transformer.transform(data)


if __name__ == "__main__":
    pytest.main([__file__])
