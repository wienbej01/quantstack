"""Feature pipeline with discretization for pattern matching."""

import sys
from pathlib import Path

import pandas as pd

# Import feature computation from sip_pattern_discovery
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent / "sip_pattern_discovery" / "src")
)
from features import compute_all_features


def compute_features(df: pd.DataFrame, spy_df: pd.DataFrame = None) -> pd.DataFrame:
    """Compute all features (same as discovery).

    Args:
        df: DataFrame with ts, symbol, OHLCV
        spy_df: Optional SPY data for regime features

    Returns:
        DataFrame with features added
    """
    return compute_all_features(df, spy_df, n_workers=2)  # Reduce workers for backtest


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
    # Compute features (without SPY for now)
    result = compute_features(df, spy_df=None)

    # Discretize relevant features based on the patterns we're using
    feature_cols = [
        "atr_14",
        "session_range_pct",
        "rvol",
        "rel_strength_60m",
        "ret_60m",
        "price_vs_vwap_pct",
        "is_first_hour",
        "is_power_hour",
        "rel_outperform_extreme",
        "rel_underperform_extreme",
        "price_up_vol_weak",
        "price_down_vol_weak",
        "price_up_vol_strong",
        "price_down_vol_strong",
    ]

    result = discretize_features(result, feature_cols, n_bins)

    return result
