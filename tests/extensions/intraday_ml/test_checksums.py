"""Tests for checksum computation utilities."""


import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml.utils.checksums import (
    compute_input_checksums,
    validate_checksum_consistency,
)


class TestComputeInputChecksums:
    """Test input checksum computation."""

    @pytest.fixture
    def sample_bars_df(self):
        """Create sample bars DataFrame."""
        np.random.seed(42)
        timestamps = pd.date_range(
            "2024-01-02 09:30:00", periods=100, freq="1min", tz="UTC"
        )

        data = {
            "ts": timestamps.astype(np.int64),
            "symbol": ["AAPL"] * 50 + ["MSFT"] * 50,
            "open": np.random.uniform(100, 200, 100),
            "high": np.random.uniform(100, 200, 100),
            "low": np.random.uniform(100, 200, 100),
            "close": np.random.uniform(100, 200, 100),
            "volume": np.random.randint(1000, 10000, 100),
        }
        return pd.DataFrame(data)

    @pytest.fixture
    def sample_features_df(self):
        """Create sample features DataFrame."""
        np.random.seed(42)
        timestamps = pd.date_range(
            "2024-01-02 09:30:00", periods=100, freq="1min", tz="UTC"
        )

        data = {
            "ts": timestamps.astype(np.int64),
            "symbol": ["AAPL"] * 50 + ["MSFT"] * 50,
            "f__ta__vwap_10": np.random.uniform(100, 200, 100),
            "f__vol__rel_volume_30": np.random.uniform(0.5, 2.0, 100),
            "f__vol__atr_14": np.random.uniform(1.0, 5.0, 100),
        }
        return pd.DataFrame(data)

    @pytest.fixture
    def sample_config(self):
        """Create sample configuration."""
        return {
            "policy": "vwap_revert",
            "policy_params": {
                "vwap_lookback_m": 10,
                "min_rvol": 1.0,
            },
            "backtest": {
                "initial_equity": 100000.0,
                "cost_per_share": 0.003,
            },
        }

    def test_checksum_computation_basic(
        self, sample_bars_df, sample_features_df, sample_config
    ):
        """Test basic checksum computation."""
        checksums = compute_input_checksums(
            sample_bars_df, sample_features_df, sample_config
        )

        # Check required checksums are present
        required_keys = ["bars_norm_hash", "features_hash", "config_hash", "seed"]
        for key in required_keys:
            assert key in checksums
            assert isinstance(checksums[key], str)
            assert len(checksums[key]) == 64  # blake2b digest_size=32

    def test_bars_hash_deterministic(self, sample_bars_df, sample_features_df):
        """Test that bars hash is deterministic."""
        config1 = {"test": "config1"}
        config2 = {"test": "config2"}

        checksums1 = compute_input_checksums(
            sample_bars_df, sample_features_df, config1
        )
        checksums2 = compute_input_checksums(
            sample_bars_df, sample_features_df, config2
        )

        # Bars hash should be same regardless of config
        assert checksums1["bars_norm_hash"] == checksums2["bars_norm_hash"]

    def test_features_hash_deterministic(self, sample_bars_df, sample_features_df):
        """Test that features hash is deterministic."""
        config = {"test": "config"}

        checksums1 = compute_input_checksums(sample_bars_df, sample_features_df, config)
        checksums2 = compute_input_checksums(sample_bars_df, sample_features_df, config)

        # Features hash should be identical for same input
        assert checksums1["features_hash"] == checksums2["features_hash"]

    def test_config_hash_sensitivity(self, sample_bars_df, sample_features_df):
        """Test that config hash changes with config changes."""
        config1 = {"policy_params": {"min_rvol": 1.0}}
        config2 = {"policy_params": {"min_rvol": 1.5}}

        checksums1 = compute_input_checksums(
            sample_bars_df, sample_features_df, config1
        )
        checksums2 = compute_input_checksums(
            sample_bars_df, sample_features_df, config2
        )

        # Config hashes should be different
        assert checksums1["config_hash"] != checksums2["config_hash"]

    def test_seed_hash(self, sample_bars_df, sample_features_df):
        """Test seed hash computation."""
        config = {"test": "config"}

        checksums1 = compute_input_checksums(
            sample_bars_df, sample_features_df, config, seed=42
        )
        checksums2 = compute_input_checksums(
            sample_bars_df, sample_features_df, config, seed=123
        )

        # Seed hashes should be different
        assert checksums1["seed"] != checksums2["seed"]

    def test_sip_hash_with_universe(self, sample_bars_df, sample_features_df):
        """Test SIP hash computation with universe."""
        config = {"test": "config"}
        sip_map = {1641024000000000000: {"AAPL", "MSFT"}}  # timestamp -> symbols

        checksums = compute_input_checksums(
            sample_bars_df, sample_features_df, config, sip_map=sip_map
        )

        assert "sip_hash" in checksums
        assert len(checksums["sip_hash"]) >= 32  # SIP hash may be different length

    def test_sip_hash_without_universe(self, sample_bars_df, sample_features_df):
        """Test SIP hash computation without universe."""
        config = {"test": "config"}

        checksums = compute_input_checksums(sample_bars_df, sample_features_df, config)

        assert "sip_hash" in checksums
        assert len(checksums["sip_hash"]) >= 32  # SIP hash may be different length

    def test_config_sanitization(self, sample_bars_df, sample_features_df):
        """Test that runtime-only fields are removed from config hash."""
        config1 = {
            "policy_params": {"min_rvol": 1.0},
            "seed": 42,  # Should be ignored
            "git_commit": "abc123",  # Should be ignored
        }
        config2 = {
            "policy_params": {"min_rvol": 1.0},
            "seed": 123,  # Different seed
            "git_commit": "def456",  # Different commit
        }

        checksums1 = compute_input_checksums(
            sample_bars_df, sample_features_df, config1
        )
        checksums2 = compute_input_checksums(
            sample_bars_df, sample_features_df, config2
        )

        # Config hashes should be same despite different seeds/commits
        assert checksums1["config_hash"] == checksums2["config_hash"]


class TestValidateChecksumConsistency:
    """Test checksum consistency validation."""

    def test_perfect_match(self):
        """Test validation with perfect checksum match."""
        expected = {"hash1": "value1", "hash2": "value2"}
        actual = {"hash1": "value1", "hash2": "value2"}

        mismatches = validate_checksum_consistency(expected, actual)
        assert len(mismatches) == 0

    def test_missing_key(self):
        """Test validation with missing key in actual."""
        expected = {"hash1": "value1", "hash2": "value2"}
        actual = {"hash1": "value1"}

        mismatches = validate_checksum_consistency(expected, actual)
        assert len(mismatches) == 1
        assert "missing_key_hash2" in mismatches

    def test_value_mismatch(self):
        """Test validation with mismatched values."""
        expected = {"hash1": "value1", "hash2": "value2"}
        actual = {"hash1": "value1", "hash2": "different_value"}

        mismatches = validate_checksum_consistency(expected, actual)
        assert len(mismatches) == 1
        assert "mismatch_hash2" in mismatches

    def test_multiple_issues(self):
        """Test validation with multiple issues."""
        expected = {"hash1": "value1", "hash2": "value2", "hash3": "value3"}
        actual = {"hash1": "value1", "hash2": "different_value"}

        mismatches = validate_checksum_consistency(expected, actual)
        assert len(mismatches) == 2
        assert "missing_key_hash3" in mismatches
        assert "mismatch_hash2" in mismatches

    def test_extra_keys_in_actual(self):
        """Test validation with extra keys in actual (should be ignored)."""
        expected = {"hash1": "value1"}
        actual = {"hash1": "value1", "hash2": "extra_value"}

        mismatches = validate_checksum_consistency(expected, actual)
        assert len(mismatches) == 0  # Extra keys should not cause mismatches
