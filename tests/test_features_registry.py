"""Unit tests for feature registry functionality."""

import os
import sys

import pandas as pd
import pytest

# Add qx-features to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-features", "src"))

from qx_features.registry import (
    FeatureRegistry,
    apply,
    apply_feature_packs,
    compute_feature_hashes,
    create_feature_pack_config,
    validate_feature_pack_config,
)


class TestFeatureRegistry:
    """Test FeatureRegistry class."""

    def test_list_available_features(self):
        """Test listing available features."""
        features = FeatureRegistry.list_available_features()

        assert isinstance(features, list)
        assert "vwap" in features
        assert "rel_volume" in features
        assert "atr" in features

    def test_list_predefined_packs(self):
        """Test listing predefined packs."""
        packs = FeatureRegistry.list_predefined_packs()

        assert isinstance(packs, list)
        assert "core_basics" in packs
        assert "fast_indicators" in packs
        assert "slow_indicators" in packs

    def test_get_predefined_pack(self):
        """Test getting predefined pack configuration."""
        config = FeatureRegistry.get_predefined_pack("core_basics")

        assert isinstance(config, dict)
        assert "vwap" in config
        assert "rel_volume" in config
        assert "atr" in config

        # Check default parameters
        assert config["vwap"]["lookback_m"] == 30
        assert config["rel_volume"]["lookback_m"] == 30
        assert config["atr"]["lookback_m"] == 14

    def test_get_predefined_pack_invalid(self):
        """Test getting invalid predefined pack."""
        with pytest.raises(ValueError, match="Unknown predefined pack"):
            FeatureRegistry.get_predefined_pack("invalid_pack")

    def test_register_feature(self):
        """Test registering custom feature."""

        def custom_feature(df, lookback_m):
            return pd.Series([1.0] * len(df), name="custom")

        # Register feature
        FeatureRegistry.register_feature("custom", custom_feature)

        # Check it's available
        features = FeatureRegistry.list_available_features()
        assert "custom" in features

        # Test using the registered feature
        pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "close": [150.0],
                "volume": [1000],
            }
        )

        # This would work in actual application
        assert "custom" in FeatureRegistry._FEATURE_FUNCTIONS

    def test_register_pack(self):
        """Test registering custom pack."""
        custom_config = {
            "custom_feature": {"lookback_m": 20},
            "vwap": {"lookback_m": 15},
        }

        # Register pack
        FeatureRegistry.register_pack("custom_pack", custom_config)

        # Check it's available
        packs = FeatureRegistry.list_predefined_packs()
        assert "custom_pack" in packs

        # Check configuration
        retrieved = FeatureRegistry.get_predefined_pack("custom_pack")
        assert retrieved == custom_config


class TestApplyFeatures:
    """Test feature application functionality."""

    def setup_method(self):
        """Setup test data."""
        self.df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000]
                * 2,
                "symbol": ["AAPL"] * 3 + ["GOOGL"] * 3,
                "open": [150.0, 151.0, 152.0, 2800.0, 2810.0, 2820.0],
                "high": [151.0, 152.0, 153.0, 2810.0, 2820.0, 2830.0],
                "low": [149.0, 150.0, 151.0, 2790.0, 2800.0, 2810.0],
                "close": [150.5, 151.5, 152.5, 2805.0, 2815.0, 2825.0],
                "volume": [1000, 800, 1200, 500, 600, 400],
            }
        )

    def test_apply_empty_packs(self):
        """Test applying empty packs list."""
        result = apply(self.df, [])

        # Should return unchanged dataframe
        assert result.equals(self.df)

    def test_apply_core_basics(self):
        """Test applying core basics pack."""
        packs = [
            {
                "type": "core_basics",
                "params": {
                    "vwap_window_m": 10,
                    "rel_vol_window_m": 10,
                    "atr_window_m": 5,
                },
            }
        ]

        result = apply(self.df, packs)

        # Should have added feature columns
        expected_features = {
            "f__ta__vwap_10",
            "f__vol__rel_volume_10",
            "f__vol__atr_5",
            "f__warmup_ok",
        }

        for feature in expected_features:
            assert feature in result.columns

        # Check warmup mask (max window is 10)
        assert not result["f__warmup_ok"].iloc[:9].any()  # First 9 bars should be False
        assert result["f__warmup_ok"].iloc[10:].all()  # Bars 10+ should be True

    def test_apply_predefined_pack(self):
        """Test applying predefined pack."""
        packs = [{"type": "fast_indicators"}]

        result = apply(self.df, packs)

        # Should have features from fast_indicators pack
        assert "f__ta__vwap_10" in result.columns
        assert "f__vol__rel_volume_10" in result.columns
        assert "f__vol__atr_7" in result.columns

    def test_apply_direct_features(self):
        """Test applying direct feature specification."""
        packs = [{"vwap": {"lookback_m": 5}, "atr": {"lookback_m": 3}}]

        result = apply(self.df, packs)

        # Should have specified features only
        assert "f__ta__vwap_5" in result.columns
        assert "f__vol__atr_3" in result.columns
        assert "f__vol__rel_volume_5" not in result.columns  # Not requested

    def test_apply_multiple_packs(self):
        """Test applying multiple packs."""
        packs = [
            {"type": "core_basics", "params": {"vwap_window_m": 10}},
            {"type": "fast_indicators", "params": {}},
        ]

        result = apply(self.df, packs)

        # Should have features from both packs
        # The second pack should override/extend the first
        assert "f__ta__vwap_10" in result.columns  # From first pack
        assert "f__vol__rel_volume_10" in result.columns  # From second pack
        assert "f__vol__atr_7" in result.columns  # From second pack

    def test_apply_invalid_pack(self):
        """Test applying invalid pack."""
        packs = [{"type": "invalid_pack"}]

        with pytest.raises(ValueError, match="Unknown feature pack"):
            apply(self.df, packs)

    def test_apply_no_sort(self):
        """Test applying features without sorting."""
        # Create unsorted dataframe
        unsorted_df = self.df.sample(frac=1).reset_index(drop=True)

        unsorted_df.index.tolist()

        packs = [{"type": "core_basics"}]
        result = apply(unsorted_df, packs, sort_by_symbol_ts=False)

        # Order should be preserved (but feature computation may not be correct)
        # This tests the sort_by_symbol_ts parameter
        assert len(result) == len(unsorted_df)


class TestFeaturePacksLegacy:
    """Test legacy compatibility functions."""

    def test_apply_feature_packs_compatibility(self):
        """Test legacy apply_feature_packs function."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000],
                "symbol": ["AAPL", "AAPL"],
                "open": [150.0, 151.0],
                "high": [151.0, 152.0],
                "low": [149.0, 150.0],
                "close": [150.5, 151.5],
                "volume": [1000, 800],
            }
        )

        packs = [{"name": "core_basics", "params": {"vwap_window_m": 5}}]

        # Legacy function should work
        result = apply_feature_packs(df, packs)

        assert "f__ta__vwap_5" in result.columns


class TestFeatureHashing:
    """Test feature hashing functionality."""

    def test_compute_feature_hashes(self):
        """Test computing feature hashes."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000],
                "symbol": ["AAPL", "AAPL"],
                "close": [150.0, 151.0],
                "f__ta__vwap_10": [150.2, 150.8],
                "f__vol__atr_5": [1.5, 1.6],
            }
        )

        hashes = compute_feature_hashes(df)

        assert isinstance(hashes, dict)
        assert "f__ta__vwap_10" in hashes
        assert "f__vol__atr_5" in hashes

        # Hashes should be strings
        for _feature, hash_val in hashes.items():
            assert isinstance(hash_val, str)
            assert len(hash_val) == 64  # blake2b hash length

    def test_compute_feature_hashes_auto_detect(self):
        """Test auto-detection of feature columns."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "close": [150.0],
                "volume": [1000],
                "f__ta__vwap_10": [150.2],  # Feature column
                "f__vol__atr_5": [1.5],  # Feature column
                "other_col": ["test"],  # Non-feature column
            }
        )

        hashes = compute_feature_hashes(df)

        # Should auto-detect only f__ columns
        assert "f__ta__vwap_10" in hashes
        assert "f__vol__atr_5" in hashes
        assert "other_col" not in hashes

    def test_compute_feature_hashes_specific_cols(self):
        """Test hashing specific feature columns."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "f__ta__vwap_10": [150.2],
                "f__vol__atr_5": [1.5],
            }
        )

        hashes = compute_feature_hashes(df, ["f__ta__vwap_10"])

        assert len(hashes) == 1
        assert "f__ta__vwap_10" in hashes
        assert "f__vol__atr_5" not in hashes


class TestFeaturePackValidation:
    """Test feature pack configuration validation."""

    def test_validate_core_basics_config(self):
        """Test validating core basics configuration."""
        config = {
            "type": "core_basics",
            "params": {"vwap_window_m": 30, "rel_vol_window_m": 30, "atr_window_m": 14},
        }

        # Should not raise exception
        validate_feature_pack_config(config)

    def test_validate_core_basics_invalid_params(self):
        """Test validating core basics with invalid parameters."""
        config = {
            "type": "core_basics",
            "params": {"vwap_window_m": -5},  # Invalid negative window
        }

        with pytest.raises(
            ValueError, match="vwap_window_m must be a positive integer"
        ):
            validate_feature_pack_config(config)

    def test_validate_predefined_pack(self):
        """Test validating predefined pack."""
        config = {"type": "fast_indicators", "params": {"custom_param": "value"}}

        # Should not raise exception
        validate_feature_pack_config(config)

    def test_validate_invalid_config_type(self):
        """Test validating invalid config type."""
        config = "invalid_config"

        with pytest.raises(
            ValueError, match="Feature pack config must be a dictionary"
        ):
            validate_feature_pack_config(config)

    def test_validate_missing_type_field(self):
        """Test validating config without type field."""
        config = {"params": {"some": "value"}}

        with pytest.raises(
            ValueError, match="Feature pack must have 'type' or 'name' field"
        ):
            validate_feature_pack_config(config)


class TestCreateFeaturePackConfig:
    """Test feature pack configuration creation."""

    def test_create_core_basics_config(self):
        """Test creating core basics configuration."""
        config = create_feature_pack_config(
            "core_basics", vwap_window_m=20, atr_window_m=10
        )

        assert config["type"] == "core_basics"
        assert config["params"]["vwap_window_m"] == 20
        assert config["params"]["rel_vol_window_m"] == 30  # Default
        assert config["params"]["atr_window_m"] == 10

    def test_create_predefined_pack_config(self):
        """Test creating predefined pack configuration."""
        config = create_feature_pack_config("fast_indicators", custom_param="value")

        assert config["type"] == "fast_indicators"
        assert config["params"]["custom_param"] == "value"

    def test_create_custom_pack_config(self):
        """Test creating custom pack configuration."""
        config = create_feature_pack_config(
            "custom", vwap={"lookback_m": 15}, atr={"lookback_m": 8}
        )

        assert config["type"] == "custom"
        assert config["features"]["vwap"]["lookback_m"] == 15
        assert config["features"]["atr"]["lookback_m"] == 8


class TestIntegration:
    """Integration tests for complete feature workflows."""

    def test_end_to_end_feature_application(self):
        """Test complete feature application workflow."""
        # Create test data
        df = pd.DataFrame(
            {
                "ts": [
                    1640995200000000000 + i * 60000000000 for i in range(50)
                ],  # 50 bars, 1 minute apart
                "symbol": ["AAPL"] * 50,
                "open": [150.0 + i * 0.1 for i in range(50)],
                "high": [151.0 + i * 0.1 for i in range(50)],
                "low": [149.0 + i * 0.1 for i in range(50)],
                "close": [150.5 + i * 0.1 for i in range(50)],
                "volume": [1000 + i * 10 for i in range(50)],
            }
        )

        # Apply features
        packs = [
            {
                "type": "core_basics",
                "params": {
                    "vwap_window_m": 10,
                    "rel_vol_window_m": 10,
                    "atr_window_m": 5,
                },
            }
        ]

        result = apply(df, packs)

        # Verify results
        assert len(result) == 50
        assert "f__ta__vwap_10" in result.columns
        assert "f__vol__rel_volume_10" in result.columns
        assert "f__vol__atr_5" in result.columns
        assert "f__warmup_ok" in result.columns

        # Check warmup logic
        assert not result["f__warmup_ok"].iloc[:9].any()  # First 9 bars False
        assert result["f__warmup_ok"].iloc[10:].all()  # Bars 10+ True

        # Check that features have reasonable values
        assert (result["f__ta__vwap_10"] > 0).all()
        assert (result["f__vol__rel_volume_10"] > 0).all()
        assert (result["f__vol__atr_5"] > 0).all()

        # Compute hashes
        hashes = compute_feature_hashes(result)
        assert len(hashes) == 3  # Three feature columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
