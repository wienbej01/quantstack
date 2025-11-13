"""Basic integration test for S3 features functionality."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Add qx-features to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-features", "src"))

from qx_features.core_basics import atr_m, vwap_m
from qx_features.registry import FeatureRegistry, apply


class TestS3BasicIntegration:
    """Basic integration tests for S3 implementation."""

    def test_feature_registry_basic(self):
        """Test that FeatureRegistry is properly configured."""
        features = FeatureRegistry.list_available_features()
        packs = FeatureRegistry.list_predefined_packs()

        # Should have basic features
        assert "vwap" in features
        assert "rel_volume" in features
        assert "atr" in features

        # Should have predefined packs
        assert "core_basics" in packs
        assert "fast_indicators" in packs
        assert "slow_indicators" in packs

    def test_vwap_computation(self):
        """Test VWAP computation with realistic data."""
        # Create simple test data
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
                "symbol": ["AAPL"] * 3,
                "close": [150.0, 151.0, 152.0],
                "volume": [1000, 800, 1200],
            }
        )

        # Compute VWAP
        result = vwap_m(df, 2)

        # Should return a Series
        assert isinstance(result, pd.Series)
        assert len(result) == 3

        # First value should be close to close (insufficient data)
        assert np.isclose(result.iloc[0], 150.0)

        # Second value should be weighted average
        expected_vwap = (150.0 * 1000 + 151.0 * 800) / (1000 + 800)
        assert np.isclose(result.iloc[1], expected_vwap, rtol=0.01)

    def test_atr_computation(self):
        """Test ATR computation with realistic data."""
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

        # Compute ATR
        result = atr_m(df, 2)

        # Should return a Series
        assert isinstance(result, pd.Series)
        assert len(result) == 3

        # First value should be high-low range
        assert np.isclose(result.iloc[0], 2.0)  # 151 - 149

    def test_apply_core_basics_pack(self):
        """Test applying core basics feature pack."""
        # Create test data
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000 + i * 60000000000 for i in range(10)],  # 10 bars
                "symbol": ["AAPL"] * 10,
                "open": [150.0 + i * 0.1 for i in range(10)],
                "high": [151.0 + i * 0.1 for i in range(10)],
                "low": [149.0 + i * 0.1 for i in range(10)],
                "close": [150.5 + i * 0.1 for i in range(10)],
                "volume": [1000 + i * 10 for i in range(10)],
            }
        )

        # Apply core basics pack with small windows
        packs = [
            {
                "type": "core_basics",
                "params": {
                    "vwap_window_m": 3,
                    "rel_vol_window_m": 3,
                    "atr_window_m": 2,
                },
            }
        ]

        result = apply(df, packs)

        # Should have added feature columns
        assert "f__ta__vwap_3" in result.columns
        assert "f__vol__rel_volume_3" in result.columns
        assert "f__vol__atr_2" in result.columns
        assert "f__warmup_ok" in result.columns

        # Should have same number of rows
        assert len(result) == 10

        # Warmup mask: max window is 3, so first 3 bars should be False
        assert not result["f__warmup_ok"].iloc[:2].any()
        assert result["f__warmup_ok"].iloc[3:].all()

    def test_feature_naming_convention(self):
        """Test that features follow naming convention."""
        # Test VWAP naming
        vwap_result = vwap_m(
            pd.DataFrame({"ts": [1], "symbol": ["AAPL"], "close": [150.0], "volume": [1000]}),
            10,
        )
        assert "f__ta__vwap_10" in vwap_result.name

        # Test ATR naming
        atr_result = atr_m(
            pd.DataFrame(
                {
                    "ts": [1],
                    "symbol": ["AAPL"],
                    "open": [150.0],
                    "high": [151.0],
                    "low": [149.0],
                    "close": [150.5],
                }
            ),
            5,
        )
        assert "f__vol__atr_5" in atr_result.name

    def test_multiple_symbols(self):
        """Test feature computation with multiple symbols."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000] * 4,
                "symbol": ["AAPL", "AAPL", "GOOGL", "GOOGL"],
                "open": [150.0, 151.0, 2800.0, 2810.0],
                "high": [151.0, 152.0, 2810.0, 2820.0],
                "low": [149.0, 150.0, 2790.0, 2800.0],
                "close": [150.0, 151.0, 2800.0, 2810.0],
                "volume": [1000, 800, 500, 600],
            }
        )

        # Compute features
        vwap_result = vwap_m(df, 2)
        atr_result = atr_m(df, 2)

        # Should have results for both symbols
        assert len(vwap_result) == 4
        assert len(atr_result) == 4

        # AAPL and GOOGL should have different values due to different price ranges
        assert not np.isclose(vwap_result.iloc[0], vwap_result.iloc[2])
        assert not np.isclose(atr_result.iloc[0], atr_result.iloc[2])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
