"""Unit tests for core basic features."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Add qx-features to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-features", "src"))

from qx_features.core_basics import (
    atr_m,
    compute_all_core_features,
    compute_warmup_masks,
    get_feature_name,
    rel_volume_m,
    validate_feature_inputs,
    vwap_m,
)


class TestVWAPFeature:
    """Test VWAP feature computation."""

    def test_vwap_basic(self):
        """Test basic VWAP computation."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000]
                * 2,
                "symbol": ["AAPL"] * 3 + ["GOOGL"] * 3,
                "close": [150.0, 151.0, 152.0, 2800.0, 2810.0, 2820.0],
                "volume": [1000, 800, 1200, 500, 600, 400],
            }
        )

        result = vwap_m(df, 2)

        assert isinstance(result, pd.Series)
        assert len(result) == 6
        assert result.name == "f__ta__vwap_2"

        # Check first value (should be close to close due to insufficient data)
        assert np.isclose(result.iloc[0], 150.0)
        assert np.isclose(result.iloc[3], 2800.0)

        # Check VWAP calculation for second value
        # (150*1000 + 151*800) / (1000 + 800) = (150000 + 120800) / 1800 = 150.44
        expected_vwap = (150.0 * 1000 + 151.0 * 800) / (1000 + 800)
        assert np.isclose(result.iloc[1], expected_vwap)

    def test_vwap_zero_volume(self):
        """Test VWAP with zero volume."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000],
                "symbol": ["AAPL", "AAPL"],
                "close": [150.0, 151.0],
                "volume": [0, 1000],  # First bar has zero volume
            }
        )

        result = vwap_m(df, 2)

        # First value should equal close (no volume)
        assert result.iloc[0] == 150.0
        # Second value should be close to close of previous bar
        assert np.isclose(result.iloc[1], 150.0)

    def test_vwap_missing_columns(self):
        """Test VWAP with missing required columns."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "close": [150.0],
                # Missing volume
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            vwap_m(df, 2)


class TestRelativeVolumeFeature:
    """Test relative volume feature computation."""

    def test_rel_volume_basic(self):
        """Test basic relative volume computation."""
        # Create data with same time-of-day across multiple days
        base_ts = 1640995200000000000  # 2023-01-01 10:00:00 UTC
        minutes_in_day = 24 * 60

        df = pd.DataFrame(
            {
                "ts": [base_ts, base_ts + minutes_in_day * 1_000_000_000] * 2,
                "symbol": ["AAPL"] * 2 + ["GOOGL"] * 2,
                "volume": [1000, 800, 500, 600],  # Same time-of-day, different volumes
            }
        )

        result = rel_volume_m(df, 30)

        assert isinstance(result, pd.Series)
        assert len(result) == 4
        assert result.name == "f__vol__rel_volume_30"

        # For same time-of-day across two days, RVOL should be relative to average
        # AAPL: (1000 + 800) / 2 = 900 average
        # First day: 1000 / 900 = 1.11, second day: 800 / 900 = 0.89
        assert np.isclose(result.iloc[0], 1.11, atol=0.01)
        assert np.isclose(result.iloc[1], 0.89, atol=0.01)

    def test_rel_volume_single_day(self):
        """Test relative volume with single day of data."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000],
                "symbol": ["AAPL", "AAPL"],
                "volume": [1000, 800],
            }
        )

        result = rel_volume_m(df, 30)

        # With only one day, RVOL should be 1.0 (average equals current)
        assert result.iloc[0] == 1.0
        assert result.iloc[1] == 1.0

    def test_rel_volume_missing_columns(self):
        """Test relative volume with missing required columns."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                # Missing volume
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            rel_volume_m(df, 30)


class TestATRFeature:
    """Test ATR feature computation."""

    def test_atr_basic(self):
        """Test basic ATR computation."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
                "symbol": ["AAPL"] * 3,
                "open": [150.0, 151.0, 152.0],
                "high": [151.0, 152.0, 153.0],
                "low": [149.0, 150.0, 151.0],
                "close": [150.5, 151.5, 152.5],
            }
        )

        result = atr_m(df, 2)

        assert isinstance(result, pd.Series)
        assert len(result) == 3
        assert result.name == "f__vol__atr_2"

        # First value should be close to high-low (no previous close)
        assert np.isclose(result.iloc[0], 2.0)  # 151 - 149

        # Second value: TR = max(high-low, high-prev_close, low-prev_close)
        # high-low = 152 - 150 = 2.0
        # high-prev_close = abs(152 - 150.5) = 1.5
        # low-prev_close = abs(150 - 150.5) = 0.5
        # TR = max(2.0, 1.5, 0.5) = 2.0
        # ATR(2) = (2.0 + 2.0) / 2 = 2.0
        assert np.isclose(result.iloc[1], 2.0)

    def test_atr_multiple_symbols(self):
        """Test ATR with multiple symbols."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000] * 2,
                "symbol": ["AAPL", "AAPL", "GOOGL", "GOOGL"],
                "open": [150.0, 151.0, 2800.0, 2810.0],
                "high": [151.0, 152.0, 2810.0, 2820.0],
                "low": [149.0, 150.0, 2790.0, 2800.0],
                "close": [150.5, 151.5, 2805.0, 2815.0],
            }
        )

        result = atr_m(df, 2)

        # Should have separate ATR values for each symbol
        assert len(result) == 4
        # AAPL and GOOGL should have different ATR values due to different price ranges
        assert not np.isclose(result.iloc[0], result.iloc[2])

    def test_atr_missing_columns(self):
        """Test ATR with missing required columns."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "open": [150.0],
                "high": [151.0],
                # Missing low, close
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            atr_m(df, 2)


class TestFeatureUtilities:
    """Test feature utility functions."""

    def test_compute_warmup_masks(self):
        """Test warmup mask computation."""
        df = pd.DataFrame(
            {"symbol": ["AAPL"] * 5 + ["GOOGL"] * 3, "some_data": range(8)}
        )

        feature_windows = {"vwap": 3, "atr": 5}
        result = compute_warmup_masks(df, feature_windows)

        assert isinstance(result, pd.Series)
        assert len(result) == 8

        # Max window is 5, so first 5 bars per symbol should be False
        assert not result.iloc[0:5].any()  # AAPL first 5 bars
        assert result.iloc[5]  # AAPL 6th bar should be True
        assert not result.iloc[5:7].any()  # GOOGL first 2 bars should be False
        assert result.iloc[7]  # GOOGL 3rd bar should be True

    def test_compute_warmup_masks_empty(self):
        """Test warmup mask with empty feature windows."""
        df = pd.DataFrame({"symbol": ["AAPL", "GOOGL"], "some_data": [1, 2]})

        result = compute_warmup_masks(df, {})

        # With no features, all should be True
        assert result.all()

    def test_validate_feature_inputs_valid(self):
        """Test validation with valid inputs."""
        df = pd.DataFrame(
            {"ts": [1640995200000000000], "symbol": ["AAPL"], "close": [150.0]}
        )

        # Should not raise exception
        validate_feature_inputs(df, ["ts", "symbol", "close"])

    def test_validate_feature_inputs_missing(self):
        """Test validation with missing columns."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000]
                # Missing symbol, close
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            validate_feature_inputs(df, ["ts", "symbol", "close"])

    def test_get_feature_name(self):
        """Test feature name generation."""
        # Test different feature types
        assert get_feature_name("vwap", {"lookback_m": 10}) == "f__ta__vwap_10"
        assert get_feature_name("vwap", {"window_m": 30}) == "f__ta__vwap_30"
        assert (
            get_feature_name("rel_volume", {"lookback_m": 15})
            == "f__vol__rel_volume_15"
        )
        assert get_feature_name("atr", {"lookback_m": 14}) == "f__vol__atr_14"

        # Test defaults
        assert get_feature_name("vwap", {}) == "f__ta__vwap_30"
        assert get_feature_name("rel_volume", {}) == "f__vol__rel_volume_30"
        assert get_feature_name("atr", {}) == "f__vol__atr_14"

    def test_get_feature_name_invalid(self):
        """Test feature name generation with invalid feature type."""
        with pytest.raises(ValueError, match="Unknown feature type"):
            get_feature_name("invalid_feature", {})


class TestComputeAllCoreFeatures:
    """Test compute all core features function."""

    def test_compute_all_core_features_basic(self):
        """Test computing all core features."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
                "symbol": ["AAPL"] * 3,
                "open": [150.0, 151.0, 152.0],
                "high": [151.0, 152.0, 153.0],
                "low": [149.0, 150.0, 151.0],
                "close": [150.5, 151.5, 152.5],
                "volume": [1000, 800, 1200],
            }
        )

        result = compute_all_core_features(df)

        # Should have original columns + features + warmup
        expected_cols = {
            "ts",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "f__ta__vwap_30",
            "f__vol__rel_volume_30",
            "f__vol__atr_14",
            "f__warmup_ok",
        }

        assert set(result.columns) == expected_cols
        assert len(result) == 3

        # Check warmup mask (max window is 30, we have only 3 bars)
        assert not result[
            "f__warmup_ok"
        ].any()  # All should be False (insufficient data)

        # Check feature columns exist
        assert "f__ta__vwap_30" in result.columns
        assert "f__vol__rel_volume_30" in result.columns
        assert "f__vol__atr_14" in result.columns

    def test_compute_all_core_features_custom_windows(self):
        """Test computing all core features with custom windows."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000] * 40,  # 40 bars
                "symbol": ["AAPL"] * 40,
                "open": [150.0] * 40,
                "high": [151.0] * 40,
                "low": [149.0] * 40,
                "close": [150.5] * 40,
                "volume": [1000] * 40,
            }
        )

        result = compute_all_core_features(
            df, vwap_window=10, rvol_window=5, atr_window=7
        )

        # Should have features with custom names
        assert "f__ta__vwap_10" in result.columns
        assert "f__vol__rel_volume_5" in result.columns
        assert "f__vol__atr_7" in result.columns

        # Max window is 10, so first 10 bars should have warmup_ok = False
        assert not result["f__warmup_ok"].iloc[:9].any()
        assert result["f__warmup_ok"].iloc[10:].all()

    def test_compute_all_core_features_invalid_input(self):
        """Test computing all core features with invalid input."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                # Missing required OHLCV columns
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            compute_all_core_features(df)


class TestFeatureNaming:
    """Test standardized feature naming."""

    def test_feature_naming_consistency(self):
        """Test that feature naming is consistent."""
        # Test VWAP naming
        assert get_feature_name("vwap", {"lookback_m": 20}) == "f__ta__vwap_20"
        pd.Series([1.0, 2.0], name="test")
        # Note: vwap_m sets its own name, but should match the expected format

        # Test RVOL naming
        assert (
            get_feature_name("rel_volume", {"lookback_m": 15})
            == "f__vol__rel_volume_15"
        )

        # Test ATR naming
        assert get_feature_name("atr", {"lookback_m": 21}) == "f__vol__atr_21"

        # Check naming patterns
        ta_features = ["vwap"]
        vol_features = ["rel_volume", "atr"]

        for feature in ta_features:
            name = get_feature_name(feature, {"lookback_m": 10})
            assert name.startswith("f__ta__")

        for feature in vol_features:
            name = get_feature_name(feature, {"lookback_m": 10})
            assert name.startswith("f__vol__")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
