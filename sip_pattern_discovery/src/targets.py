"""Generate forward return targets for pattern discovery."""

import pandas as pd


def generate_targets(
    df: pd.DataFrame,
    horizons: list[int],
    inplace: bool = False,
) -> pd.DataFrame:
    """Generate forward return targets for pattern discovery.

    Args:
        df: DataFrame with ts, symbol, close
        horizons: List of forward horizons in minutes (e.g., [30, 60, 90, 180])

    Returns:
        DataFrame with fwd_ret_{horizon}m columns (actual % returns, not binary)
    """
    result = df if inplace else df.copy()

    for symbol, group in result.groupby("symbol"):
        group = group.sort_values("ts")

        for horizon in horizons:
            fwd_close = group["close"].shift(-horizon)
            fwd_ret = (fwd_close / group["close"] - 1) * 100  # Percentage
            result.loc[group.index, f"fwd_ret_{horizon}m"] = fwd_ret

    # Report stats
    for horizon in horizons:
        col = f"fwd_ret_{horizon}m"
        valid = result[col].dropna()
        print(
            f"  {col}: mean={valid.mean():.3f}%, std={valid.std():.3f}%, n={len(valid):,}"
        )

    return result
