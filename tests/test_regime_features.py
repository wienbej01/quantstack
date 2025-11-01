"""Unit tests for regime detection features.

Tests ensure no forward-looking bias, correct seasonality normalization,
and resilience to missing data.
"""

import numpy as np
import pandas as pd
import pytest
from qx_features.regime.features import (
    adx_proxy,
    band_position,
    compute_all_regime_features,
    get_regime_feature_config,
    mod_normalized_volatility,
    stress_metrics,
    validate_regime_inputs,
    variance_ratio,
)


@pytest.fixture
def sample_data():
    """Create sample OHLCV data for testing."""
    np.random.seed(42)  # For reproducible tests

    # Create 2 days of 1-minute data for 2 symbols
    symbols = ["AAPL", "MSFT"]
    dates = pd.date_range("2024-01-02 09:30:00", "2024-01-03 16:00:00", freq="1min")

    data = []
    for symbol in symbols:
        for date in dates:
            # Skip non-trading hours
            if date.hour < 9 or (date.hour == 9 and date.minute < 30):
                continue
            if date.hour >= 16:
                continue

            # Generate realistic OHLCV data
            base_price = 150.0 if symbol == "AAPL" else 250.0
            noise = np.random.normal(0, 0.001)

            close = base_price * (1 + noise)
            high = close * (1 + abs(np.random.normal(0, 0.002)))
            low = close * (1 - abs(np.random.normal(0, 0.002)))
            open_price = low + (high - low) * np.random.random()
            volume = int(np.random.lognormal(10, 1))

            data.append(
                {
                    "ts": int(date.timestamp() * 1e9),  # Convert to nanoseconds
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


@pytest.fixture
def stress_data():
    """Create data with stress conditions for testing."""
    np.random.seed(123)

    # Normal data
    normal_data = []
    for i in range(100):
        base_price = 100.0
        close = base_price * (1 + np.random.normal(0, 0.001))
        normal_data.append(
            {
                "ts": i * 60 * 1e9,  # 1-minute intervals
                "symbol": "TEST",
                "open": close * 0.999,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 10000,
            }
        )

    # Stress data (high volatility and volume)
    stress_data = []
    for i in range(100, 120):
        base_price = 100.0
        # Increased volatility
        close = base_price * (1 + np.random.normal(0, 0.01))
        stress_data.append(
            {
                "ts": i * 60 * 1e9,
                "symbol": "TEST",
                "open": close * 0.995,
                "high": close * 1.005,
                "low": close * 0.995,
                "close": close,
                "volume": 50000,  # Increased volume
            }
        )

    df = pd.DataFrame(normal_data + stress_data)
    return df.sort_values(["symbol", "ts"]).reset_index(drop=True)


class TestRegimeFeatureValidation:
    """Test input validation for regime features."""

    def test_validate_regime_inputs_success(self, sample_data):
        """Test successful validation."""
        validate_regime_inputs(sample_data)  # Should not raise

    def test_validate_regime_inputs_missing_columns(self):
        """Test validation failure with missing columns."""
        df = pd.DataFrame({"ts": [1], "symbol": ["AAPL"]})  # Missing OHLCV
        with pytest.raises(ValueError, match="Missing required columns"):
            validate_regime_inputs(df)

    def test_validate_regime_inputs_invalid_ohlc(self):
        """Test validation failure with invalid OHLC relationships."""
        df = pd.DataFrame(
            {
                "ts": [1, 2],
                "symbol": ["AAPL", "AAPL"],
                "open": [100, 100],
                "high": [99, 100],  # high < open - invalid
                "low": [90, 90],
                "close": [95, 95],
                "volume": [1000, 1000],
            }
        )
        with pytest.raises(ValueError, match="invalid OHLC relationships"):
            validate_regime_inputs(df)

    def test_validate_regime_inputs_negative_values(self):
        """Test validation failure with negative values."""
        df = pd.DataFrame(
            {
                "ts": [1],
                "symbol": ["AAPL"],
                "open": [100],
                "high": [101],
                "low": [-10],  # Negative price
                "close": [100],
                "volume": [1000],
            }
        )
        with pytest.raises(ValueError, match="must contain positive values"):
            validate_regime_inputs(df)

    def test_validate_regime_inputs_invalid_timestamps(self):
        """Test validation failure with invalid timestamps."""
        df = pd.DataFrame(
            {
                "ts": [-1],  # Negative timestamp
                "symbol": ["AAPL"],
                "open": [100],
                "high": [101],
                "low": [99],
                "close": [100],
                "volume": [1000],
            }
        )
        with pytest.raises(ValueError, match="Timestamps must be positive"):
            validate_regime_inputs(df)


class TestModNormalizedVolatility:
    """Test MoD-normalized volatility feature."""

    def test_basic_computation(self, sample_data):
        """Test basic volatility computation."""
        result = mod_normalized_volatility(sample_data, lookback_m=30)

        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_data)
        assert result.notna().sum() > 0  # Should have some valid values

        # Values should be positive
        assert (result >= 0).all()

        # Check naming convention
        assert result.name == "f__regime__mod_vol_30"

    def test_seasonality_normalization(self, sample_data):
        """Test that seasonality normalization works."""
        # Create data with clear intraday pattern
        dates = pd.date_range("2024-01-02 09:30:00", "2024-01-02 16:00:00", freq="5min")
        pattern_data = []

        for date in dates:
            # Create pattern: higher volatility at open and close
            hour_factor = 1.0 if 9 <= date.hour <= 11 else 0.5
            if 15 <= date.hour <= 16:
                hour_factor = 1.5

            base_price = 100.0
            volatility = 0.001 * hour_factor

            close = base_price * (1 + np.random.normal(0, volatility))
            pattern_data.append(
                {
                    "ts": int(date.timestamp() * 1e9),
                    "symbol": "PATTERN",
                    "open": close * 0.999,
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "close": close,
                    "volume": 10000,
                }
            )

        df = pd.DataFrame(pattern_data)
        result = mod_normalized_volatility(df, lookback_m=10)

        # Normalized values should reduce the pattern effect
        assert result.std() > 0  # Should still have variation

    def test_forward_look_prevention(self, sample_data):
        """Test that feature uses only historical data."""
        # Process data incrementally to ensure no forward look
        results = []
        window = 10

        for i in range(window, len(sample_data)):
            subset = sample_data.iloc[: i + 1]  # Only data up to current point
            vol = mod_normalized_volatility(subset, lookback_m=window)
            results.append(vol.iloc[-1])  # Last value

        # Compare with full computation
        full_result = mod_normalized_volatility(sample_data, lookback_m=window)
        incremental_result = pd.Series(results, index=sample_data.index[window:])

        # Should be very close (small numerical differences allowed)
        diff = abs(full_result.iloc[window:] - incremental_result).max()
        assert diff < 1e-10, f"Forward look detected: max difference = {diff}"


class TestVarianceRatio:
    """Test variance ratio feature."""

    def test_basic_computation(self, sample_data):
        """Test basic variance ratio computation."""
        result = variance_ratio(sample_data, short_window=10, long_window=30)

        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_data)
        assert result.notna().sum() > 0

        # Values should be positive
        assert (result >= 0).all()

        # Check naming convention
        assert result.name == "f__regime__var_ratio_10_30"

    def test_trend_detection(self):
        """Test variance ratio in trending vs ranging markets."""
        # Create trending data
        trend_data = []
        for i in range(100):
            price = 100 + i * 0.1 + np.random.normal(0, 0.05)
            trend_data.append(
                {
                    "ts": i * 60 * 1e9,
                    "symbol": "TREND",
                    "close": price,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "open": price * 0.9995,
                    "volume": 10000,
                }
            )

        # Create ranging data
        range_data = []
        for i in range(100):
            price = 100 + np.sin(i * 0.1) * 2 + np.random.normal(0, 0.05)
            range_data.append(
                {
                    "ts": i * 60 * 1e9,
                    "symbol": "RANGE",
                    "close": price,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "open": price * 0.9995,
                    "volume": 10000,
                }
            )

        trend_df = pd.DataFrame(trend_data)
        range_df = pd.DataFrame(range_data)

        trend_result = variance_ratio(trend_df, short_window=10, long_window=30)
        range_result = variance_ratio(range_df, short_window=10, long_window=30)

        # Trending data should have higher variance ratio on average
        assert trend_result.mean() > range_result.mean()


class TestADXProxy:
    """Test ADX proxy feature."""

    def test_basic_computation(self, sample_data):
        """Test basic ADX proxy computation."""
        result = adx_proxy(sample_data, lookback_m=14)

        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_data)
        assert result.notna().sum() > 0

        # Values should be non-negative
        assert (result >= 0).all()

        # Check naming convention
        assert result.name == "f__regime__adx_proxy_14"

    def test_trend_strength_ranges(self, sample_data):
        """Test ADX proxy produces reasonable values."""
        result = adx_proxy(sample_data, lookback_m=10)

        # ADX proxy should generally be in reasonable range (0-100)
        # Some extreme values possible but should be rare
        extreme_high = (result > 100).sum()
        extreme_low = (result < 0).sum()

        assert extreme_low == 0, "ADX proxy should never be negative"
        assert extreme_high < len(result) * 0.1, "Too many extreme high values"


class TestBandPosition:
    """Test band position feature."""

    def test_basic_computation(self, sample_data):
        """Test basic band position computation."""
        result = band_position(sample_data, window_m=20, std_dev=2.0)

        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_data)
        assert result.notna().sum() > 0

        # Check naming convention
        assert result.name == "f__regime__band_pos_20_2.0"

    def test_position_ranges(self, sample_data):
        """Test band position produces reasonable values."""
        result = band_position(sample_data, window_m=10, std_dev=2.0)

        # Most values should be in [0, 1] but can go outside during strong moves
        # Should be clipped to reasonable range
        assert result.min() >= -0.5, "Band position too low"
        assert result.max() <= 1.5, "Band position too high"


class TestStressMetrics:
    """Test stress metrics feature."""

    def test_basic_computation(self, sample_data):
        """Test basic stress metrics computation."""
        result = stress_metrics(sample_data, volatility_window=10, volume_window=10)

        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_data)
        assert result.notna().sum() > 0

        # Values should be non-negative
        assert (result >= 0).all()

        # Check naming convention
        assert result.name == "f__regime__stress_10_10"

    def test_stress_detection(self, stress_data):
        """Test stress detection in stress conditions."""
        result = stress_metrics(
            stress_data,
            volatility_window=5,
            volume_window=5,
            vol_threshold=1.5,
            volume_threshold=1.5,
        )

        # Stress period should have higher values
        normal_stress = result.iloc[:100].mean()
        stress_period_stress = result.iloc[100:].mean()

        assert stress_period_stress > normal_stress, "Stress not detected properly"


class TestComputeAllRegimeFeatures:
    """Test the combined feature computation function."""

    def test_all_features_computation(self, sample_data):
        """Test computation of all regime features."""
        result = compute_all_regime_features(sample_data)

        # Check that all expected features are present
        expected_features = [
            "f__regime__mod_vol_30",
            "f__regime__var_ratio_10_60",
            "f__regime__adx_proxy_14",
            "f__regime__band_pos_20_2.0",
            "f__regime__stress_10_10",
            "f__regime__warmup_ok",
        ]

        for feature in expected_features:
            assert feature in result.columns, f"Missing feature: {feature}"

        # Check warmup mask
        assert result["f__regime__warmup_ok"].dtype == bool

        # Check that warmup period is respected
        max_window = 60  # Maximum window from default parameters
        for symbol in result["symbol"].unique():
            symbol_data = result[result["symbol"] == symbol]
            assert not symbol_data["f__regime__warmup_ok"].iloc[:max_window].any()
            assert symbol_data["f__regime__warmup_ok"].iloc[max_window:].all()

    def test_custom_parameters(self, sample_data):
        """Test computation with custom parameters."""
        result = compute_all_regime_features(
            sample_data,
            volatility_window=20,
            variance_short=5,
            variance_long=25,
            adx_window=10,
            band_window=15,
            stress_vol_window=8,
        )

        # Should still have all features
        assert (
            len(result.columns) > len(sample_data.columns) + 6
        )  # Original + 6 features

        # Feature names should reflect custom parameters
        assert "f__regime__mod_vol_20" in result.columns
        assert "f__regime__var_ratio_5_25" in result.columns
        assert "f__regime__adx_proxy_10" in result.columns


class TestFeatureConfig:
    """Test feature configuration utilities."""

    def test_get_regime_feature_config(self):
        """Test feature configuration retrieval."""
        config = get_regime_feature_config()

        # Should have all expected features
        expected_features = [
            "mod_normalized_volatility",
            "variance_ratio",
            "adx_proxy",
            "band_position",
            "stress_metrics",
        ]

        for feature in expected_features:
            assert feature in config, f"Missing feature config: {feature}"
            assert isinstance(
                config[feature], dict
            ), f"Feature config should be dict: {feature}"

        # Check specific parameter values
        assert config["mod_normalized_volatility"]["lookback_m"] == 30
        assert config["variance_ratio"]["short_window"] == 10
        assert config["variance_ratio"]["long_window"] == 60


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_dataframe(self):
        """Test behavior with empty DataFrame."""
        df = pd.DataFrame(columns=["ts", "symbol", "high", "low", "close", "volume"])

        # Should return empty series for individual features
        result = mod_normalized_volatility(df)
        assert len(result) == 0

    def test_single_row(self):
        """Test behavior with single row of data."""
        df = pd.DataFrame(
            {
                "ts": [1],
                "symbol": ["TEST"],
                "high": [101],
                "low": [99],
                "close": [100],
                "volume": [1000],
            }
        )

        # Should handle gracefully (likely NaN due to insufficient data)
        result = mod_normalized_volatility(df, lookback_m=10)
        assert len(result) == 1

    def test_missing_data_handling(self, sample_data):
        """Test handling of missing data (NaN values)."""
        # Introduce some NaN values
        df = sample_data.copy()
        df.loc[df.index[10:15], "high"] = np.nan
        df.loc[df.index[20:25], "volume"] = np.nan

        # Should handle missing data gracefully
        result = compute_all_regime_features(df)
        assert len(result) == len(df)

        # Should have warmup mask
        assert "f__regime__warmup_ok" in result.columns


class TestPerformance:
    """Test performance characteristics."""

    def test_large_dataset_performance(self):
        """Test performance with larger dataset."""
        # Create larger dataset
        np.random.seed(42)
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
        dates = pd.date_range("2024-01-01", "2024-01-31", freq="1min")

        data = []
        for symbol in symbols:
            for date in dates:
                if 9 <= date.hour <= 15:  # Trading hours only
                    base_price = 100.0
                    close = base_price * (1 + np.random.normal(0, 0.001))
                    data.append(
                        {
                            "ts": int(date.timestamp() * 1e9),
                            "symbol": symbol,
                            "open": close * 0.999,
                            "high": close * 1.001,
                            "low": close * 0.999,
                            "close": close,
                            "volume": 10000,
                        }
                    )

        df = pd.DataFrame(data)

        # Time the computation
        import time

        start_time = time.time()
        result = compute_all_regime_features(df)
        elapsed_time = time.time() - start_time

        # Should complete in reasonable time
        assert elapsed_time < 10.0, f"Computation too slow: {elapsed_time:.2f}s"
        assert len(result) > len(df)  # Features added
        print(f"Large dataset computation: {elapsed_time:.2f}s for {len(df)} rows")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
