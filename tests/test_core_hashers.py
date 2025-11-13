"""Unit tests for core hashing functionality."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Add qx-core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-core", "src"))

from qx_core.hashers import (
    compute_consistent_checksum,
    hash_dataframe,
    hash_dict,
    hash_difference,
    hash_list,
    hash_string,
    verify_hash_stability,
)


class TestDataFrameHashing:
    """Test DataFrame hashing functionality."""

    def test_basic_dataframe_hashing(self):
        """Test basic DataFrame hashing."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL", "MSFT"],
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
                "close": [150.0, 2800.0, 300.0],
            }
        )

        hash_value = hash_dataframe(df)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64  # blake2b with digest_size=32
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_hash_stability_across_shuffles(self):
        """Test that hash is stable across row shuffles."""
        df1 = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL", "MSFT"],
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
                "close": [150.0, 2800.0, 300.0],
            }
        )

        # Shuffle rows
        df2 = df1.sample(frac=1, random_state=42).reset_index(drop=True)

        hash1 = hash_dataframe(df1)
        hash2 = hash_dataframe(df2)

        assert hash1 == hash2, f"Hashes differ after shuffle: {hash1} != {hash2}"

    def test_hash_stability_across_dtype_equivalents(self):
        """Test hash stability across equivalent dtypes."""
        df1 = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.0, 2800.0],
                "volume": [1000, 500],
            }
        )

        # Change dtypes to equivalent but different types
        df2 = df1.copy()
        df2["close"] = df2["close"].astype("float32")
        df2["volume"] = df2["volume"].astype("int32")

        hash1 = hash_dataframe(df1)
        hash2 = hash_dataframe(df2)

        assert hash1 == hash2, f"Hashes differ for dtype equivalent frames: {hash1} != {hash2}"

    def test_column_subset_hashing(self):
        """Test hashing with column subset."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.0, 2800.0],
                "volume": [1000, 500],
                "extra_col": ["ignore", "me"],
            }
        )

        hash_all = hash_dataframe(df)
        hash_subset = hash_dataframe(df, cols=["symbol", "ts", "close"])
        hash_different_subset = hash_dataframe(df, cols=["symbol", "volume"])

        assert hash_all != hash_subset, "Hash with all columns should differ from subset"
        assert hash_subset != hash_different_subset, (
            "Different subsets should have different hashes"
        )

    def test_datetime_handling(self):
        """Test datetime handling in hashing."""
        # Test that datetime objects are normalized correctly to UTC nanoseconds
        # Use explicit conversion to ensure same values
        timestamp1 = pd.Timestamp("2023-01-01 10:00:00", tz="UTC")
        timestamp2 = pd.Timestamp("2023-01-01 10:01:00", tz="UTC")

        df_dt = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [timestamp1, timestamp2],
                "close": [150.0, 2800.0],
            }
        )

        # Use the exact same timestamps converted to nanoseconds
        df_ns = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [int(timestamp1.value), int(timestamp2.value)],
                "close": [150.0, 2800.0],
            }
        )

        # Both should produce same hash after normalization
        hash_dt = hash_dataframe(df_dt)
        hash_ns = hash_dataframe(df_ns)

        assert hash_dt == hash_ns, (
            f"Datetime and nanosecond hashes should match: {hash_dt} != {hash_ns}"
        )

    def test_nan_handling(self):
        """Test NaN value handling."""
        df1 = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.0, np.nan],
            }
        )

        df2 = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.0, np.nan],
            }
        )

        hash1 = hash_dataframe(df1)
        hash2 = hash_dataframe(df2)

        assert hash1 == hash2, "Hashes should be equal for DataFrames with NaN values"

    def test_different_algorithms(self):
        """Test different hash algorithms."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.0, 2800.0],
            }
        )

        hash_blake = hash_dataframe(df, algo="blake2b")
        hash_sha = hash_dataframe(df, algo="sha256")

        assert hash_blake != hash_sha, "Different algorithms should produce different hashes"
        assert len(hash_blake) == 64, "blake2b should produce 64-character hash"
        assert len(hash_sha) == 64, "sha256 should produce 64-character hash"

    def test_empty_dataframe(self):
        """Test hashing empty DataFrame."""
        df = pd.DataFrame()
        hash_value = hash_dataframe(df)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64

    def test_complex_objects(self):
        """Test hashing DataFrames with complex objects."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "metadata": [
                    {"source": "feed1", "quality": "high"},
                    {"source": "feed2", "quality": "medium"},
                ],
            }
        )

        hash_value = hash_dataframe(df)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64

        # Test that same data produces same hash
        df2 = df.copy()
        hash2 = hash_dataframe(df2)
        assert hash_value == hash2


class TestDictHashing:
    """Test dictionary hashing functionality."""

    def test_basic_dict_hashing(self):
        """Test basic dictionary hashing."""
        data = {"symbol": "AAPL", "price": 150.0, "volume": 1000}
        hash_value = hash_dict(data)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64

    def test_dict_order_independence(self):
        """Test that dictionary order doesn't affect hash."""
        data1 = {"symbol": "AAPL", "price": 150.0, "volume": 1000}
        data2 = {"volume": 1000, "symbol": "AAPL", "price": 150.0}

        hash1 = hash_dict(data1)
        hash2 = hash_dict(data2)

        assert hash1 == hash2, "Dictionary order should not affect hash"

    def test_nested_dict_hashing(self):
        """Test nested dictionary hashing."""
        data = {
            "symbol": "AAPL",
            "metadata": {
                "source": "feed1",
                "quality": "high",
                "tags": ["tech", "large-cap"],
            },
        }

        hash_value = hash_dict(data)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64


class TestListHashing:
    """Test list hashing functionality."""

    def test_basic_list_hashing(self):
        """Test basic list hashing."""
        data = ["AAPL", "GOOGL", "MSFT"]
        hash_value = hash_list(data)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64

    def test_list_order_matters(self):
        """Test that list order affects hash."""
        data1 = ["AAPL", "GOOGL", "MSFT"]
        data2 = ["MSFT", "GOOGL", "AAPL"]

        hash1 = hash_list(data1)
        hash2 = hash_list(data2)

        assert hash1 != hash2, "List order should affect hash"


class TestStringHashing:
    """Test string hashing functionality."""

    def test_basic_string_hashing(self):
        """Test basic string hashing."""
        text = "Hello, QuantStack!"
        hash_value = hash_string(text)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64

    def test_string_case_sensitivity(self):
        """Test that string case affects hash."""
        text1 = "Hello, QuantStack!"
        text2 = "hello, quantstack!"

        hash1 = hash_string(text1)
        hash2 = hash_string(text2)

        assert hash1 != hash2, "String case should affect hash"


class TestConsistentChecksum:
    """Test consistent checksum computation."""

    def test_basic_checksum(self):
        """Test basic checksum computation."""
        bars_hash = hash_string("test_bars")
        features_hash = hash_string("test_features")
        config_hash = hash_string("test_config")

        checksum = compute_consistent_checksum(
            bars_hash=bars_hash,
            features_hash=features_hash,
            config_hash=config_hash,
            seed=42,
        )

        assert isinstance(checksum, str)
        assert len(checksum) == 64

    def test_checksum_consistency(self):
        """Test checksum consistency."""
        bars_hash = hash_string("test_bars")
        features_hash = hash_string("test_features")
        config_hash = hash_string("test_config")

        checksum1 = compute_consistent_checksum(
            bars_hash=bars_hash,
            features_hash=features_hash,
            config_hash=config_hash,
            seed=42,
        )

        checksum2 = compute_consistent_checksum(
            bars_hash=bars_hash,
            features_hash=features_hash,
            config_hash=config_hash,
            seed=42,
        )

        assert checksum1 == checksum2, "Checksum should be consistent"

    def test_checksum_seed_sensitivity(self):
        """Test that checksum is sensitive to seed."""
        bars_hash = hash_string("test_bars")
        features_hash = hash_string("test_features")
        config_hash = hash_string("test_config")

        checksum1 = compute_consistent_checksum(
            bars_hash=bars_hash,
            features_hash=features_hash,
            config_hash=config_hash,
            seed=42,
        )

        checksum2 = compute_consistent_checksum(
            bars_hash=bars_hash,
            features_hash=features_hash,
            config_hash=config_hash,
            seed=123,
        )

        assert checksum1 != checksum2, "Checksum should be sensitive to seed"


class TestHashStability:
    """Test hash stability verification."""

    def test_hash_stability_verification(self):
        """Test hash stability verification."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.0, 2800.0],
            }
        )

        is_stable = verify_hash_stability(df, iterations=5)
        assert is_stable, "Hash should be stable across multiple computations"

    def test_hash_difference_detection(self):
        """Test hash difference detection."""
        df1 = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.0, 2800.0],
            }
        )

        df2 = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "ts": [1640995200000000000, 1640995260000000000],
                "close": [150.1, 2800.0],  # Slightly different price
            }
        )

        is_different = hash_difference(df1, df2)
        assert is_different, "Hashes should be different for different DataFrames"

        # Test identical DataFrames
        df3 = df1.copy()
        is_different_identical = hash_difference(df1, df3)
        assert not is_different_identical, "Hashes should be identical for identical DataFrames"


class TestErrorHandling:
    """Test error handling in hashing functions."""

    def test_unsupported_algorithm(self):
        """Test unsupported algorithm handling."""
        df = pd.DataFrame({"symbol": ["AAPL"], "price": [150.0]})

        with pytest.raises(ValueError, match="Unsupported algo"):
            hash_dataframe(df, algo="unsupported_algo")

    def test_invalid_precision(self):
        """Test invalid precision parameter."""
        df = pd.DataFrame({"symbol": ["AAPL"], "price": [150.0]})

        # This should work fine - just test that precision parameter is accepted
        hash_value = hash_dataframe(df, precision=3)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
