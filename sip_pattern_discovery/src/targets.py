"""Generate forward return targets for pattern discovery."""

import pandas as pd


def compute_forward_returns(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Compute forward returns for multiple horizons.

    Args:
        df: DataFrame with ts, symbol, close
        horizons: List of forward horizons in minutes (e.g., [60, 120, 180])

    Returns:
        DataFrame with forward return columns added
    """
    result = df.copy()

    for symbol, group in result.groupby("symbol"):
        group = group.sort_values("ts")

        for horizon in horizons:
            # Forward return
            fwd_close = group["close"].shift(-horizon)
            fwd_ret = (fwd_close / group["close"] - 1) * 100  # Percentage

            result.loc[group.index, f"fwd_ret_{horizon}m"] = fwd_ret

    return result


def compute_binary_targets(
    df: pd.DataFrame, horizons: list[int], thresholds: dict
) -> pd.DataFrame:
    """Compute binary targets based on forward returns.

    Args:
        df: DataFrame with forward return columns
        horizons: List of horizons
        thresholds: Dict mapping horizon to threshold (e.g., {60: 0.5, 120: 0.8})

    Returns:
        DataFrame with binary target columns added
    """
    result = df.copy()

    for horizon in horizons:
        threshold = thresholds.get(horizon, 0.5)
        fwd_ret_col = f"fwd_ret_{horizon}m"

        if fwd_ret_col not in result.columns:
            continue

        # Binary targets
        result[f"up_{horizon}m"] = (result[fwd_ret_col] > threshold).astype(int)
        result[f"down_{horizon}m"] = (result[fwd_ret_col] < -threshold).astype(int)
        result[f"big_move_{horizon}m"] = (
            abs(result[fwd_ret_col]) > threshold * 2
        ).astype(int)

    return result


def generate_targets(
    df: pd.DataFrame, horizons: list[int], thresholds: dict | None = None
) -> pd.DataFrame:
    """Generate all targets for pattern discovery - BOTH UP AND DOWN.

    Args:
        df: DataFrame with ts, symbol, close
        horizons: List of forward horizons in minutes
        thresholds: Optional dict of thresholds per horizon

    Returns:
        DataFrame with target columns added
    """
    if thresholds is None:
        thresholds = {60: 0.5, 120: 0.8, 180: 1.0}

    print(f"Computing forward returns for horizons: {horizons}")
    result = compute_forward_returns(df, horizons)

    print("Computing binary targets (UP AND DOWN)...")
    result = compute_binary_targets(result, horizons, thresholds)

    return result
