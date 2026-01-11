"""Feature pipeline with discretization for pattern matching."""

import sys
from pathlib import Path

import pandas as pd

# Import feature computation from sip_pattern_discovery
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "sip_pattern_discovery"))
from src.features import (
    compute_atr_features,
    compute_momentum_features,
    compute_session_features,
    compute_time_features,
    compute_volume_features,
    compute_vwap_features,
)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all features (same as discovery).

    Args:
        df: DataFrame with ts, symbol, OHLCV

    Returns:
        DataFrame with features added
    """
    result = df.copy()

    result = compute_momentum_features(result)
    result = compute_vwap_features(result)
    result = compute_volume_features(result)
    result = compute_atr_features(result)
    result = compute_session_features(result)
    result = compute_time_features(result)

    return result


def discretize_feature(series: pd.Series, n_bins: int = 5) -> pd.Series:
    """Discretize a continuous feature into bins.

    Args:
        series: Feature values
        n_bins: Number of bins

    Returns:
        Discretized series with bin labels
    """
    # Skip if already binary
    if series.nunique() <= 2:
        return series

    # Quantile-based binning
    try:
        return pd.qcut(series, q=n_bins, labels=False, duplicates="drop")
    except Exception:
        # Fall back to equal-width
        return pd.cut(series, bins=n_bins, labels=False)


def discretize_features(
    df: pd.DataFrame, feature_cols: list, n_bins: int = 5
) -> pd.DataFrame:
    """Discretize features for pattern matching.

    Args:
        df: DataFrame with features
        feature_cols: List of feature columns to discretize
        n_bins: Number of bins per feature

    Returns:
        DataFrame with discretized features (suffix _bin)
    """
    result = df.copy()

    for col in feature_cols:
        if col not in df.columns:
            continue

        result[f"{col}_bin"] = discretize_feature(df[col], n_bins)

    return result


def compute_and_discretize_features(df: pd.DataFrame, n_bins: int = 5) -> pd.DataFrame:
    """Compute features and discretize for pattern matching.

    Args:
        df: DataFrame with ts, symbol, OHLCV
        n_bins: Number of bins for discretization

    Returns:
        DataFrame with features and discretized features
    """
    # Compute features
    result = compute_features(df)

    # Discretize relevant features
    feature_cols = [
        "ret_5m",
        "ret_15m",
        "ret_30m",
        "ret_60m",
        "price_vs_vwap_pct",
        "price_vs_session_avwap_pct",
        "rvol",
        "atr_14",
        "is_first_hour",
        "is_power_hour",
    ]

    result = discretize_features(result, feature_cols, n_bins)

    return result
