"""Checksum computation utilities for experiment reproducibility."""

import hashlib
import json
from typing import Any, Dict

import pandas as pd

from qx_core.hashers import hash_dataframe, hash_sip_map


def compute_input_checksums(
    bars_df: pd.DataFrame,
    features_df: pd.DataFrame,
    config: Dict[str, Any],
    sip_map: Dict[int, set] | None = None,
    seed: int = 42,
) -> Dict[str, str]:
    """Compute comprehensive input checksums for experiment reproducibility."""
    checksums = {}

    # Bars normalization hash
    checksums["bars_norm_hash"] = hash_dataframe(
        bars_df, cols=["ts", "symbol", "open", "high", "low", "close", "volume"]
    )

    # Features hash
    feature_cols = [c for c in features_df.columns if c.startswith("f__")]
    if feature_cols:
        checksums["features_hash"] = hash_dataframe(features_df, cols=feature_cols)

    # SIP/Universe hash
    if sip_map:
        checksums["sip_hash"] = hash_sip_map(sip_map)
    else:
        # Empty universe hash
        empty_sip = json.dumps({}, sort_keys=True)
        checksums["sip_hash"] = hashlib.blake2b(
            empty_sip.encode(), digest_size=32
        ).hexdigest()

    # Configuration hash
    config_copy = json.loads(json.dumps(config, sort_keys=True, default=str))
    # Remove runtime-only fields
    for key in ["seed", "git_commit"]:
        config_copy.pop(key, None)
    config_str = json.dumps(config_copy, sort_keys=True)
    checksums["config_hash"] = hashlib.blake2b(
        config_str.encode(), digest_size=32
    ).hexdigest()

    # Seed hash
    seed_str = str(seed)
    checksums["seed"] = hashlib.blake2b(seed_str.encode(), digest_size=32).hexdigest()

    return checksums


def validate_checksum_consistency(
    expected: Dict[str, str], actual: Dict[str, str]
) -> list[str]:
    """Validate that checksums are consistent between expected and actual."""
    mismatches = []
    for key, expected_value in expected.items():
        if key not in actual:
            mismatches.append(f"missing_key_{key}")
        elif actual[key] != expected_value:
            mismatches.append(f"mismatch_{key}")
    return mismatches


def compute_data_hash(data: pd.DataFrame) -> str:
    """Compute hash of DataFrame for reproducibility."""
    return hash_dataframe(data, cols=data.columns.tolist())


def compute_config_hash(config: Dict[str, Any]) -> str:
    """Compute hash of configuration dictionary."""
    config_str = json.dumps(config, sort_keys=True, default=str)
    return hashlib.blake2b(config_str.encode(), digest_size=32).hexdigest()
