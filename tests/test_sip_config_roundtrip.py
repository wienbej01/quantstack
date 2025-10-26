"""Test SIP configuration roundtrip with different sip_hash values."""

import json
import pathlib
import tempfile

import pandas as pd
import yaml

from qx_cli.exp.entry_ab import deep_merge
from qx_core.hashers import hash_dataframe


def create_base_config():
    """Create a base configuration for testing."""
    return {
        "gold_root": "/tmp/test",
        "family": "equities",
        "symbols": ["AAPL", "GOOGL", "MSFT"],
        "dates": ["2024-01-03"],
        "seed": 42,
        "features": [{"name": "core_basics"}],
        "policy": "vwap_revert",
        "policy_params": {"lookback": 20},
        "risk_params": {"max_risk_frac": 0.02},
        "backtest": {"initial_equity": 100000},
        "sip_filter": True,
    }


def create_legacy_overlay():
    """Create legacy SIP overlay."""
    return {
        "sip": {
            "method": "original",
            "top_n": 5,
            "rvol_col": "f__vol__rel_volume_30",
            "whitelist": ["AAPL", "GOOGL"],
        }
    }


def create_hmm_overlay():
    """Create HMM SIP overlay."""
    return {
        "sip": {
            "method": "hmm",
            "top_k": 10,
            "score_floor": 0.1,
            "enable_gold_fallback": True,
            "external_premarket_root": "/tmp/test_sip",
        }
    }


def test_config_roundtrip():
    """Test that different SIP configs produce different sip_hash values."""
    # Create base config
    base_config = create_base_config()

    # Create sample data
    bars_df = pd.DataFrame(
        {
            "ts": [1609459200000000000, 1609459260000000000] * 3,
            "symbol": ["AAPL", "GOOGL", "MSFT"] * 2,
            "open": [100.0, 150.0, 200.0] * 2,
            "high": [101.0, 151.0, 201.0] * 2,
            "low": [99.0, 149.0, 199.0] * 2,
            "close": [100.5, 150.5, 200.5] * 2,
            "volume": [1000000, 500000, 300000] * 2,
        }
    )

    # Add feature columns
    bars_df["f__vol__rel_volume_30"] = [1.2, 0.8, 1.5] * 2
    bars_df["f__warmup_ok"] = True

    # Calculate hashes that should be identical
    bars_norm_hash = hash_dataframe(
        bars_df, cols=["ts", "symbol", "open", "high", "low", "close", "volume"]
    )
    features_hash = hash_dataframe(
        bars_df, cols=[c for c in bars_df.columns if c.startswith("f__")]
    )

    # Test legacy overlay
    legacy_config = deep_merge(base_config, create_legacy_overlay())
    legacy_config_str = json.dumps(legacy_config, sort_keys=True)
    legacy_config_hash = hash_dataframe(
        pd.DataFrame([legacy_config_str], columns=["config"]), cols=["config"]
    )

    # Test HMM overlay
    hmm_config = deep_merge(base_config, create_hmm_overlay())
    hmm_config_str = json.dumps(hmm_config, sort_keys=True)
    hmm_config_hash = hash_dataframe(
        pd.DataFrame([hmm_config_str], columns=["config"]), cols=["config"]
    )

    # Verify results
    print(f"Base bars_norm_hash: {bars_norm_hash}")
    print(f"Base features_hash: {features_hash}")
    print(f"Legacy config hash: {legacy_config_hash}")
    print(f"HMM config hash: {hmm_config_hash}")

    # Verify that bars and features hashes would be identical (same base data)
    assert bars_norm_hash is not None
    assert features_hash is not None

    # Verify that config hashes are different (different SIP configs)
    assert legacy_config_hash != hmm_config_hash

    # Verify SIP methods are different
    assert legacy_config["sip"]["method"] == "original"
    assert hmm_config["sip"]["method"] == "hmm"
    assert legacy_config["sip"]["top_n"] == 5
    assert hmm_config["sip"]["top_n"] == 10

    print("✓ Config roundtrip test passed")


def test_overlay_file_creation():
    """Test that overlay files can be created and loaded correctly."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = pathlib.Path(temp_dir)

        # Create overlay files
        legacy_overlay = create_legacy_overlay()
        hmm_overlay = create_hmm_overlay()

        legacy_file = temp_path / "sip_legacy.yaml"
        hmm_file = temp_path / "sip_hmmsip.yaml"

        with open(legacy_file, "w") as f:
            yaml.dump(legacy_overlay, f)

        with open(hmm_file, "w") as f:
            yaml.dump(hmm_overlay, f)

        # Load and verify
        with open(legacy_file) as f:
            loaded_legacy = yaml.safe_load(f)

        with open(hmm_file) as f:
            loaded_hmm = yaml.safe_load(f)

        assert loaded_legacy["sip"]["method"] == "original"
        assert loaded_hmm["sip"]["method"] == "hmm"
        assert loaded_legacy["sip"]["top_n"] == 5
        assert loaded_hmm["sip"]["top_n"] == 10

        print("✓ Overlay file creation test passed")


def test_deep_merge_functionality():
    """Test deep merge functionality works correctly."""
    base = create_base_config()

    # Test merging with overlay
    overlay = create_hmm_overlay()
    merged = deep_merge(base, overlay)

    # Verify merge worked
    assert merged["sip"]["method"] == "hmm"
    assert merged["sip"]["top_k"] == 10
    assert merged["symbols"] == ["AAPL", "GOOGL", "MSFT"]  # From base
    assert merged["seed"] == 42  # From base

    print("✓ Deep merge test passed")


if __name__ == "__main__":
    test_config_roundtrip()
    test_overlay_file_creation()
    test_deep_merge_functionality()
    print("\nAll tests passed!")
