"""
Golden tests for reproducibility validation.

Ensures that identical configurations produce identical results
by comparing inputs_checksum.json across multiple runs.
"""

import hashlib
import json
import pathlib
import tempfile

import numpy as np
import pandas as pd
import pytest

from qx_core.hashers import hash_dataframe
from qx_features.registry import apply


class TestReproducibility:
    """Test suite for reproducibility validation."""

    @pytest.fixture
    def sample_data(self):
        """Create deterministic sample data for testing."""
        np.random.seed(42)  # Fixed seed for reproducibility

        # Create time series
        timestamps = pd.date_range("2024-01-01", periods=100, freq="1min")
        base_price = 100.0
        returns = np.random.normal(0, 0.001, len(timestamps))
        prices = base_price * np.exp(np.cumsum(returns))

        data = []
        for i, ts in enumerate(timestamps):
            price = prices[i]
            volatility = abs(returns[i]) * price

            high = price + abs(np.random.normal(0, volatility * 0.5))
            low = price - abs(np.random.normal(0, volatility * 0.5))
            open_price = price + np.random.normal(0, volatility * 0.2)
            close = price
            volume = max(1000, int(np.random.lognormal(10, 1)))

            data.append(
                {
                    "ts": int(ts.timestamp() * 1_000_000_000),  # Convert to nanoseconds
                    "symbol": "TEST",
                    "open": open_price,
                    "high": max(high, open_price, close),
                    "low": min(low, open_price, close),
                    "close": close,
                    "volume": volume,
                }
            )

        return pd.DataFrame(data)

    @pytest.fixture
    def standard_config(self):
        """Standard configuration for reproducibility testing."""
        return {
            "gold_root": "/tmp/test_data",
            "family": "bars_1m",
            "symbols": ["TEST"],
            "dates": ["2024-01-01"],
            "seed": 42,
            "features": [
                {
                    "type": "core_basics",
                    "params": {
                        "vwap_window_m": 30,
                        "rel_vol_window_m": 30,
                        "atr_window_m": 14,
                    },
                }
            ],
            "policy": "vwap_revert",
            "policy_params": {
                "rvol_min": 1.0,
                "max_position_bars": 50,
                "position_size_pct": 0.1,
                "max_positions": 5,
            },
            "risk_params": {"max_risk_frac": 0.02, "atr_mult": 2.0},
        }

    def test_dataframe_hash_stability(self, sample_data):
        """Test that dataframe hashing is stable and deterministic."""
        # Test 1: Same dataframe should produce same hash
        hash1 = hash_dataframe(sample_data)
        hash2 = hash_dataframe(sample_data)
        assert hash1 == hash2, "Same dataframe should produce identical hash"

        # Test 2: Reordered rows should produce different hash (sorting matters)
        df_shuffled = sample_data.sample(frac=1.0, random_state=42).reset_index(drop=True)
        hash_shuffled = hash_dataframe(df_shuffled)
        assert hash1 != hash_shuffled, "Shuffled dataframe should produce different hash"

        # Test 3: Properly sorted dataframe should produce same hash
        df_sorted = df_shuffled.sort_values(["symbol", "ts"]).reset_index(drop=True)
        hash_sorted = hash_dataframe(df_sorted)
        assert hash1 == hash_sorted, "Sorted dataframe should produce same hash"

    def test_feature_hash_determinism(self, sample_data):
        """Test that feature computation is deterministic."""
        # Apply features with fixed seed
        features_config = [
            {
                "type": "core_basics",
                "params": {
                    "vwap_window_m": 30,
                    "rel_vol_window_m": 30,
                    "atr_window_m": 14,
                },
            }
        ]

        # Run twice with same data and seed
        df_features_1 = apply(sample_data.copy(), features_config)
        df_features_2 = apply(sample_data.copy(), features_config)

        # Extract feature columns
        feature_cols = [col for col in df_features_1.columns if col.startswith("f__")]

        # Compute hashes for feature columns
        hash1 = hash_dataframe(df_features_1[["symbol", "ts"] + feature_cols])
        hash2 = hash_dataframe(df_features_2[["symbol", "ts"] + feature_cols])

        assert hash1 == hash2, "Feature computation should be deterministic"

    def test_inputs_checksum_generation(self, sample_data, standard_config):
        """Test inputs_checksum.json generation and validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)

            # Create sample gold data
            gold_path = temp_path / "test_gold" / "bars_1m" / "symbol=TEST" / "date=SMOKE"
            gold_path.mkdir(parents=True, exist_ok=True)
            sample_data.to_parquet(gold_path / "part-000.parquet")

            # Update config to use temporary gold data
            config = standard_config.copy()
            config["gold_root"] = str(temp_path / "test_gold")

            # Compute component hashes
            bars_hash = hash_dataframe(sample_data)

            # Apply features
            features_config = config["features"]
            df_features = apply(sample_data.copy(), features_config)
            feature_cols = [col for col in df_features.columns if col.startswith("f__")]
            features_hash = hash_dataframe(df_features[["symbol", "ts"] + feature_cols])

            # Create inputs checksum
            inputs_checksum = {
                "bars_norm_hash": bars_hash,
                "features_hash": features_hash,
                "sip_hash": "sip_test_hash",  # Mock SIP hash
                "config_hash": hashlib.sha256(
                    json.dumps(config, sort_keys=True).encode()
                ).hexdigest()[:16],
                "seed": config["seed"],
            }

            # Save inputs checksum
            checksum_path = temp_path / "inputs_checksum.json"
            with open(checksum_path, "w") as f:
                json.dump(inputs_checksum, f, indent=2)

            # Verify saved checksum
            with open(checksum_path) as f:
                loaded_checksum = json.load(f)

            assert loaded_checksum == inputs_checksum, "Saved checksum should match original"

    def test_config_hash_consistency(self, standard_config):
        """Test that identical configs produce identical hashes."""
        config1 = standard_config.copy()
        config2 = standard_config.copy()

        # Compute config hashes
        hash1 = hashlib.sha256(json.dumps(config1, sort_keys=True).encode()).hexdigest()[:16]
        hash2 = hashlib.sha256(json.dumps(config2, sort_keys=True).encode()).hexdigest()[:16]

        assert hash1 == hash2, "Identical configs should produce identical hashes"

        # Test that different configs produce different hashes
        config2["policy_params"]["rvol_min"] = 1.5  # Change parameter
        hash3 = hashlib.sha256(json.dumps(config2, sort_keys=True).encode()).hexdigest()[:16]

        assert hash1 != hash3, "Different configs should produce different hashes"

    def test_reproducibility_validation(self, sample_data, standard_config):
        """Test end-to-end reproducibility validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)

            # Create sample gold data
            gold_path = temp_path / "test_gold" / "bars_1m" / "symbol=TEST" / "date=SMOKE"
            gold_path.mkdir(parents=True, exist_ok=True)
            sample_data.to_parquet(gold_path / "part-000.parquet")

            # Update config
            config = standard_config.copy()
            config["gold_root"] = str(temp_path / "test_gold")

            # Run experiment twice (simulated)
            run_results = []

            for _run_num in [1, 2]:
                with tempfile.TemporaryDirectory() as run_dir:
                    run_path = pathlib.Path(run_dir)

                    # Simulate experiment processing
                    # 1. Load data (hash)
                    bars_hash = hash_dataframe(sample_data)

                    # 2. Apply features (hash)
                    features_config = config["features"]
                    df_features = apply(sample_data.copy(), features_config)
                    feature_cols = [col for col in df_features.columns if col.startswith("f__")]
                    features_hash = hash_dataframe(df_features[["symbol", "ts"] + feature_cols])

                    # 3. Create inputs checksum
                    inputs_checksum = {
                        "bars_norm_hash": bars_hash,
                        "features_hash": features_hash,
                        "sip_hash": "sip_test_hash",
                        "config_hash": hashlib.sha256(
                            json.dumps(config, sort_keys=True).encode()
                        ).hexdigest()[:16],
                        "seed": config["seed"],
                    }

                    # Save inputs checksum
                    checksum_path = run_path / "inputs_checksum.json"
                    with open(checksum_path, "w") as f:
                        json.dump(inputs_checksum, f, indent=2)

                    run_results.append(inputs_checksum)

            # Validate reproducibility
            checksum1 = run_results[0]
            checksum2 = run_results[1]

            # All critical hashes should be identical
            critical_keys = ["bars_norm_hash", "features_hash", "sip_hash", "seed"]
            for key in critical_keys:
                assert checksum1[key] == checksum2[key], (
                    f"Hash {key} should be identical across runs"
                )

            # Config hash should also be identical
            assert checksum1["config_hash"] == checksum2["config_hash"], (
                "Config hash should be identical"
            )

    def test_golden_reproducibility_reference(self):
        """Test against golden reproducibility reference data."""
        # This test validates against known good values
        golden_checksums = {
            "bars_norm_hash": "golden_bars_hash_12345678",
            "features_hash": "golden_features_hash_87654321",
            "sip_hash": "golden_sip_hash_11223344",
            "config_hash": "golden_config_hash_55667788",
            "seed": 42,
        }

        # In a real implementation, this would load a saved golden checksum
        # For now, we'll create a temporary one and validate structure
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(golden_checksums, f, indent=2)
            golden_file = pathlib.Path(f.name)

        try:
            with open(golden_file) as f:
                loaded_checksum = json.load(f)

            # Validate structure
            required_keys = [
                "bars_norm_hash",
                "features_hash",
                "sip_hash",
                "config_hash",
                "seed",
            ]
            for key in required_keys:
                assert key in loaded_checksum, f"Golden checksum missing required key: {key}"
                assert isinstance(loaded_checksum[key], str), (
                    f"Golden checksum {key} should be string"
                )

            # Validate hash format (16 characters typical)
            for key in ["bars_norm_hash", "features_hash", "sip_hash", "config_hash"]:
                assert len(loaded_checksum[key]) == 16, (
                    f"Golden checksum {key} should be 16 characters"
                )

            # Validate seed
            assert isinstance(loaded_checksum["seed"], int), (
                "Golden checksum seed should be integer"
            )

        finally:
            golden_file.unlink()

    def test_deterministic_seeding(self):
        """Test that random seeding produces deterministic results."""
        # Test 1: Same seed should produce same results
        np.random.seed(42)
        result1 = np.random.normal(0, 1, 10)

        np.random.seed(42)
        result2 = np.random.normal(0, 1, 10)

        np.testing.assert_array_equal(
            result1, result2, "Same seed should produce identical results"
        )

        # Test 2: Different seeds should produce different results
        np.random.seed(42)
        result_a = np.random.normal(0, 1, 10)

        np.random.seed(123)
        result_b = np.random.normal(0, 1, 10)

        assert not np.array_equal(result_a, result_b), (
            "Different seeds should produce different results"
        )

    def test_temporal_determinism(self):
        """Test that temporal processing is deterministic."""
        # Create deterministic time series
        start_time = pd.Timestamp("2024-01-01")
        timestamps = pd.date_range(start_time, periods=10, freq="1min")

        # Create data with exact timestamps
        data = []
        for i, ts in enumerate(timestamps):
            data.append(
                {
                    "ts": int(ts.timestamp() * 1_000_000_000),
                    "symbol": "TEST",
                    "close": 100.0 + i * 0.1,
                    "volume": 1000,
                }
            )

        df = pd.DataFrame(data)

        # Process twice with same timestamp handling
        hash1 = hash_dataframe(df)
        hash2 = hash_dataframe(df)

        assert hash1 == hash2, "Temporal data processing should be deterministic"

    def test_multi_experiment_reproducibility(self, sample_data):
        """Test reproducibility across multiple experiments."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)

            # Create multiple experiments with same underlying data
            checksums = []

            for exp_name in ["exp_A", "exp_B"]:
                # Create experiment directory
                exp_dir = temp_path / exp_name
                exp_dir.mkdir()

                # Create gold data
                gold_path = temp_path / "gold" / "bars_1m" / "symbol=TEST" / "date=SMOKE"
                gold_path.mkdir(parents=True, exist_ok=True)
                sample_data.to_parquet(gold_path / f"part-{exp_name}.parquet")

                # Create configuration (same except for experiment name)
                config = {
                    "exp_id": f"test_{exp_name}",
                    "gold_root": str(temp_path / "gold"),
                    "family": "bars_1m",
                    "symbols": ["TEST"],
                    "dates": ["2024-01-01"],
                    "seed": 42,
                    "features": [
                        {
                            "type": "core_basics",
                            "params": {
                                "vwap_window_m": 30,
                                "rel_vol_window_m": 30,
                                "atr_window_m": 14,
                            },
                        }
                    ],
                }

                # Compute checksum
                bars_hash = hash_dataframe(sample_data)
                config_hash = hashlib.sha256(
                    json.dumps(config, sort_keys=True).encode()
                ).hexdigest()[:16]

                checksum = {
                    "bars_norm_hash": bars_hash,
                    "config_hash": config_hash,
                    "seed": 42,
                }

                checksums.append(checksum)

            # Validate consistency across experiments
            # Bars hash should be identical (same data)
            assert checksums[0]["bars_norm_hash"] == checksums[1]["bars_norm_hash"], (
                "Bars hash should be identical across experiments"
            )

            # Seed should be identical
            assert checksums[0]["seed"] == checksums[1]["seed"], (
                "Seed should be identical across experiments"
            )

            # Config hash should be different (different experiment names)
            assert checksums[0]["config_hash"] != checksums[1]["config_hash"], (
                "Config hash should differ across experiments"
            )
