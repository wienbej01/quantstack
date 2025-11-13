"""Tests for Intraday ML Feature Pack

Unit tests for feature computation, property tests for leakage prevention,
and validation tests for feature registry compliance.
"""

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml.feature_pack import IntradayMLFeaturePack
from extensions.intraday_ml.feature_registry import IntradayMLFeatureRegistry


class TestIntradayMLFeaturePack:
    """Unit tests for feature pack functionality."""

    @pytest.fixture
    def sample_config(self):
        """Sample feature configuration for testing."""
        return {
            "families": {
                "returns_trend": {
                    "enabled": True,
                    "windows": [1, 5, 10],
                    "include_log": True,
                },
                "volatility_ranges": {
                    "enabled": True,
                    "atr_windows": [5, 14],
                    "volatility_windows": [5, 10],
                    "range_ratios": [0.5, 1.0],
                },
                "volume_flow": {
                    "enabled": True,
                    "volume_windows": [5, 10],
                    "vwap_windows": [5, 10],
                    "relative_volume_windows": [10],
                },
                "time_seasonality": {
                    "enabled": True,
                    "include_hour": True,
                    "include_minute": False,
                    "include_day_of_week": True,
                    "cyclical_encoding": True,
                },
                "price_momentum": {
                    "enabled": True,
                    "roc_windows": [1, 5],
                    "rsi_windows": [14],
                    "ma_windows": [5, 10],
                },
            },
            "max_total_features": 150,
        }

    @pytest.fixture
    def sample_data(self):
        """Sample OHLCV data for testing."""
        np.random.seed(42)
        dates = pd.date_range("2024-01-02 09:30:00", periods=100, freq="1min")
        symbols = ["AAPL", "MSFT"]

        data = []
        for symbol in symbols:
            base_price = 150.0 if symbol == "AAPL" else 250.0
            for i, ts in enumerate(dates):
                # Simulate price movement
                price_change = np.random.normal(0, 0.001) * base_price
                close = base_price + price_change + (i * 0.01)
                high = close * (1 + abs(np.random.normal(0, 0.001)))
                low = close * (1 - abs(np.random.normal(0, 0.001)))
                open_price = low + (high - low) * np.random.random()
                volume = max(1000, int(np.random.normal(100000, 20000)))

                data.append(
                    {
                        "ts": ts,
                        "symbol": symbol,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    }
                )

        df = pd.DataFrame(data)
        return df.sort_values(["symbol", "ts"]).reset_index(drop=True)

    def test_feature_pack_initialization(self, sample_config):
        """Test feature pack initializes correctly."""
        pack = IntradayMLFeaturePack(sample_config)
        assert pack.config == sample_config
        assert pack.max_features == 150

    def test_returns_trend_features(self, sample_config, sample_data):
        """Test returns and trend feature computation."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()  # Use max timestamp to avoid time discipline issues

        features = pack.compute_features(sample_data, ts_cut)

        # Check that return features exist
        assert "f__ret__simple_1" in features.columns
        assert "f__ret__simple_5" in features.columns
        assert "f__ret__log_1" in features.columns
        assert "f__ret__log_5" in features.columns

        # Check data types
        assert pd.api.types.is_float_dtype(features["f__ret__simple_1"])
        assert pd.api.types.is_float_dtype(features["f__ret__log_1"])

    def test_volatility_features(self, sample_config, sample_data):
        """Test volatility feature computation."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        features = pack.compute_features(sample_data, ts_cut)

        # Check that volatility features exist
        assert "f__vol__atr_5" in features.columns
        assert "f__vol__atr_14" in features.columns
        assert "f__vol__rolling_std_5" in features.columns
        assert "f__range__ratio_0.5" in features.columns

        # Check non-negative values for ranges and volatility
        assert (features["f__vol__atr_5"] >= 0).all()
        assert (features["f__vol__rolling_std_5"] >= 0).all()

    def test_volume_flow_features(self, sample_config, sample_data):
        """Test volume and flow feature computation."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        features = pack.compute_features(sample_data, ts_cut)

        # Check that volume features exist
        assert "f__vol__sum_5" in features.columns
        assert "f__vwap__value_5" in features.columns
        assert "f__vol__rel_10" in features.columns

        # Check VWAP is reasonable (should be between min and max price)
        for symbol in sample_data["symbol"].unique():
            symbol_mask = sample_data["symbol"] == symbol
            symbol_features = features[symbol_mask]
            symbol_data = sample_data[symbol_mask]

            if len(symbol_features) > 0 and symbol_features["f__vwap__value_5"].notna().any():
                vwap_values = symbol_features["f__vwap__value_5"].dropna()
                min_prices = symbol_data["low"].min()
                max_prices = symbol_data["high"].max()
                assert (vwap_values >= min_prices).all()
                assert (vwap_values <= max_prices).all()

    def test_time_seasonality_features(self, sample_config, sample_data):
        """Test time seasonality feature computation."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        features = pack.compute_features(sample_data, ts_cut)

        # Check cyclical encoding
        assert "f__time__hour_sin" in features.columns
        assert "f__time__hour_cos" in features.columns
        assert "f__time__dow_sin" in features.columns
        assert "f__time__dow_cos" in features.columns

        # Check cyclical properties (sin^2 + cos^2 = 1)
        hour_sin = features["f__time__hour_sin"]
        hour_cos = features["f__time__hour_cos"]
        hour_magnitude = np.sqrt(hour_sin**2 + hour_cos**2)
        assert np.allclose(hour_magnitude.dropna(), 1.0, atol=1e-10)

    def test_price_momentum_features(self, sample_config, sample_data):
        """Test price momentum feature computation."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        features = pack.compute_features(sample_data, ts_cut)

        # Check momentum features exist
        assert "f__mom__roc_1" in features.columns
        assert "f__mom__roc_5" in features.columns
        assert "f__mom__rsi_14" in features.columns
        assert "f__ma__ratio_5" in features.columns

        # Check RSI bounds (should be between 0 and 100)
        rsi_values = features["f__mom__rsi_14"].dropna()
        if len(rsi_values) > 0:
            assert (rsi_values >= 0).all()
            assert (rsi_values <= 100).all()

    def test_time_discipline_validation(self, sample_config, sample_data):
        """Test that time discipline validation works."""
        pack = IntradayMLFeaturePack(sample_config)

        # Test with valid ts_cut (should not raise)
        valid_ts_cut = sample_data["ts"].max()
        features = pack.compute_features(sample_data, valid_ts_cut, validate_time_discipline=True)
        assert len(features) > 0

        # Test with invalid ts_cut (should raise)
        invalid_ts_cut = sample_data["ts"].iloc[5]  # Too early
        with pytest.raises(ValueError, match="Input data contains timestamps after ts_cut"):
            pack.compute_features(sample_data, invalid_ts_cut, validate_time_discipline=True)

    def test_feature_count_limit(self, sample_config, sample_data):
        """Test that feature count limit is enforced."""
        # Set very low limit
        sample_config["max_total_features"] = 5
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        with pytest.raises(ValueError, match="exceeding maximum of 5"):
            pack.compute_features(sample_data, ts_cut)

    def test_disabled_families(self, sample_config, sample_data):
        """Test that disabled families are not computed."""
        # Disable returns_trend
        sample_config["families"]["returns_trend"]["enabled"] = False
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        features = pack.compute_features(sample_data, ts_cut)

        # Check that return features are not present
        assert not any(col.startswith("f__ret__") for col in features.columns)
        # Check that other features are still present
        assert any(col.startswith("f__vol__") for col in features.columns)

    def test_empty_dataframe_handling(self, sample_config):
        """Test handling of empty or minimal DataFrames."""
        pack = IntradayMLFeaturePack(sample_config)

        # Empty DataFrame
        empty_df = pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
        ts_cut = pd.Timestamp("2024-01-02 16:00:00")

        features = pack.compute_features(empty_df, ts_cut)
        assert len(features) == 0
        assert features.index.empty

    def test_feature_determinism(self, sample_config, sample_data):
        """Test that feature computation is deterministic."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        # Compute features twice
        features1 = pack.compute_features(sample_data, ts_cut)
        features2 = pack.compute_features(sample_data, ts_cut)

        # Should be identical
        pd.testing.assert_frame_equal(features1, features2)


class TestFeatureProperties:
    """Property tests for feature characteristics."""

    @pytest.fixture
    def sample_config(self):
        """Sample feature configuration."""
        return {
            "families": {
                "returns_trend": {
                    "enabled": True,
                    "windows": [1, 5],
                    "include_log": True,
                },
                "volatility_ranges": {
                    "enabled": True,
                    "atr_windows": [5],
                    "volatility_windows": [5],
                },
                "time_seasonality": {"enabled": True, "cyclical_encoding": True},
            },
            "max_total_features": 150,
        }

    @pytest.fixture
    def sample_data(self):
        """Sample data for property testing."""
        np.random.seed(42)
        dates = pd.date_range("2024-01-02 09:30:00", periods=50, freq="1min")

        data = []
        base_price = 150.0
        for i, ts in enumerate(dates):
            close = base_price + (i * 0.01) + np.random.normal(0, 0.1)
            data.append(
                {
                    "ts": ts,
                    "symbol": "AAPL",
                    "open": close * 0.999,
                    "high": close * 1.001,
                    "low": close * 0.998,
                    "close": close,
                    "volume": 100000,
                }
            )

        return pd.DataFrame(data)

    def test_no_leakage_property(self, sample_config, sample_data):
        """Property test: features should not leak future information."""
        pack = IntradayMLFeaturePack(sample_config)

        # Test with multiple cut times
        for i in range(10, 40, 5):
            ts_cut = sample_data["ts"].iloc[i]

            # Compute features with data up to ts_cut
            features = pack.compute_features(sample_data, ts_cut)

            # For each row, features should only depend on past data
            for j, row_idx in enumerate(sample_data.index):
                if sample_data.loc[row_idx, "ts"] > ts_cut:
                    continue

                # Get feature values at this timestamp
                if row_idx in features.index:
                    feature_row = features.loc[row_idx]

                    # Simple returns: should be NaN for first few rows
                    if "f__ret__simple_5" in feature_row:
                        # First 5 rows should have NaN for 5-minute return
                        if j < 5:
                            assert pd.isna(feature_row["f__ret__simple_5"])
                        else:
                            # Should have a valid value
                            assert not pd.isna(feature_row["f__ret__simple_5"])

    def test_feature_bounds_property(self, sample_config, sample_data):
        """Property test: features should respect expected bounds."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        features = pack.compute_features(sample_data, ts_cut)

        # Test cyclical features are bounded [-1, 1]
        cyclical_features = [col for col in features.columns if "sin" in col or "cos" in col]
        for col in cyclical_features:
            values = features[col].dropna()
            if len(values) > 0:
                assert (values >= -1.01).all()  # Small tolerance for floating point
                assert (values <= 1.01).all()

        # Test log returns are reasonable (should be small)
        log_return_features = [col for col in features.columns if "log" in col and "ret" in col]
        for col in log_return_features:
            values = features[col].dropna()
            if len(values) > 0:
                # Log returns for 1-minute bars should be small
                assert (values.abs() < 1.0).all()

    def test_feature_continuity_property(self, sample_config, sample_data):
        """Property test: features should evolve smoothly over time."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].iloc[-5]

        features = pack.compute_features(sample_data, ts_cut)

        # Select a continuous feature
        if "f__vol__atr_5" in features.columns:
            atr_series = features["f__vol__atr_5"].dropna()

            if len(atr_series) > 5:
                # ATR should not jump dramatically between consecutive values
                atr_diff = atr_series.diff().dropna()
                # Allow for some volatility but shouldn't be extreme
                assert (atr_diff.abs() < atr_series.mean() * 10).all()

    def test_feature_nan_propagation(self, sample_config, sample_data):
        """Property test: NaN handling should be consistent."""
        pack = IntradayMLFeaturePack(sample_config)
        ts_cut = sample_data["ts"].max()

        features = pack.compute_features(sample_data, ts_cut)

        # Check that early rows have expected NaN values for windowed features
        for col in features.columns:
            if any(window in col for window in ["_5", "_10", "_14"]):
                # Windowed features should have NaN in early rows
                early_values = features[col].head(5)
                assert early_values.isna().any(), f"Expected NaN values in early rows for {col}"

                # Later values should be mostly non-NaN
                later_values = features[col].tail(10)
                assert later_values.notna().any(), (
                    f"Expected non-NaN values in later rows for {col}"
                )


class TestFeatureRegistry:
    """Tests for feature registry functionality."""

    @pytest.fixture
    def registry_config(self):
        """Configuration for registry testing."""
        return {
            "families": {
                "returns_trend": {
                    "enabled": True,
                    "windows": [1, 5],
                    "include_log": True,
                },
                "volatility_ranges": {"enabled": True, "atr_windows": [5, 14]},
            },
            "max_total_features": 150,
        }

    def test_registry_initialization(self, registry_config):
        """Test registry initializes correctly."""
        registry = IntradayMLFeatureRegistry(registry_config)
        assert registry.config == registry_config
        assert len(registry.get_feature_names()) > 0

    def test_feature_metadata_creation(self, registry_config):
        """Test feature metadata is created correctly."""
        registry = IntradayMLFeatureRegistry(registry_config)

        # Check that expected features exist
        expected_features = [
            "f__ret__simple_1",
            "f__ret__simple_5",
            "f__ret__log_1",
            "f__ret__log_5",
            "f__vol__atr_5",
            "f__vol__atr_14",
        ]

        for feature in expected_features:
            assert feature in registry.get_feature_names()
            metadata = registry.get_feature_metadata(feature)
            assert metadata is not None
            assert metadata.name == feature
            assert metadata.family in ["returns_trend", "volatility_ranges"]

    def test_features_by_family(self, registry_config):
        """Test grouping features by family."""
        registry = IntradayMLFeatureRegistry(registry_config)

        returns_features = registry.get_features_by_family("returns_trend")
        vol_features = registry.get_features_by_family("volatility_ranges")

        assert len(returns_features) > 0
        assert len(vol_features) > 0
        assert all("ret" in f for f in returns_features)
        assert all("vol" in f for f in vol_features)

    def test_feature_validation(self, registry_config):
        """Test feature validation functionality."""
        registry = IntradayMLFeatureRegistry(registry_config)

        # Create mock feature data
        feature_names = registry.get_feature_names()
        feature_data = pd.DataFrame(np.random.randn(100, len(feature_names)), columns=feature_names)

        # Add some NaN values
        feature_data.iloc[0, 0] = np.nan

        validation = registry.validate_features(feature_data)

        assert validation["feature_count"] == len(feature_names)
        assert validation["expected_count"] == len(feature_names)
        assert len(validation["missing_features"]) == 0
        assert len(validation["unexpected_features"]) == 0

    def test_max_window_calculation(self, registry_config):
        """Test maximum window calculation."""
        registry = IntradayMLFeatureRegistry(registry_config)
        max_window = registry.get_max_window()

        # Should be the maximum of all windows in config
        expected_max = max([5, 14, 1, 5])  # atr_windows + returns windows
        assert max_window == expected_max

    def test_feature_count_by_family(self, registry_config):
        """Test feature counting by family."""
        registry = IntradayMLFeatureRegistry(registry_config)
        counts = registry.count_features_by_family()

        assert "returns_trend" in counts
        assert "volatility_ranges" in counts
        assert counts["returns_trend"] > 0
        assert counts["volatility_ranges"] > 0

    def test_disabled_family_metadata(self, registry_config):
        """Test that disabled families don't create metadata."""
        registry_config["families"]["returns_trend"]["enabled"] = False
        registry = IntradayMLFeatureRegistry(registry_config)

        returns_features = registry.get_features_by_family("returns_trend")
        assert len(returns_features) == 0

        # Other families should still work
        vol_features = registry.get_features_by_family("volatility_ranges")
        assert len(vol_features) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
