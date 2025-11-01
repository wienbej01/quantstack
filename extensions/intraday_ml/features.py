"""Intraday ML features extension (Sprint 3).

This module wraps existing qx-features functionality while providing
Sprint 3 interface for feature engineering and enrichment.
"""

from typing import Any

import pandas as pd
from qx_core.hashers import hash_dataframe
from qx_features.registry import apply


def intraday_ml_apply_features(
    bars: pd.DataFrame,
    feature_pack: str = "core_basics",
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Apply feature engineering using existing qx-features.

    Args:
        bars: DataFrame with OHLCV data
        feature_pack: Name of feature pack to apply
        config: Optional configuration for feature parameters

    Returns:
        DataFrame with added feature columns
    """
    if config is None:
        config = {}

    # Use existing feature pack application
    pack_config = {"type": feature_pack, "params": config}
    return apply(bars, [pack_config])


def intraday_ml_get_features_hash(
    bars: pd.DataFrame,
    feature_pack: str = "core_basics",
    config: dict[str, Any] | None = None,
) -> str:
    """Get deterministic hash of feature engineering parameters.

    Args:
        bars: Input bars DataFrame
        feature_pack: Name of feature pack to apply
        config: Optional configuration for feature parameters

    Returns:
        Deterministic hash string
    """
    if config is None:
        config = {}

    # Create hash from inputs and feature parameters
    input_hash = hash_dataframe(bars)
    feature_params = {
        "feature_pack": feature_pack,
        "config": config,
    }
    config_hash = hash_dataframe(pd.DataFrame([feature_params]))

    # Combine hashes (simple concatenation for now)
    return f"{input_hash}_{config_hash}"
