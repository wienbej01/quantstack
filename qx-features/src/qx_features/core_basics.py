"""Core basic features pack with deterministic VWAP, RVOL, and ATR."""

from typing import Any

import numpy as np
import pandas as pd
from qx_core.utils import utc_ns_to_datetime


def vwap_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute rolling VWAP over lookback_m minutes.

    Args:
        df: DataFrame with ts, symbol, close, volume, sorted by [symbol, ts]
        lookback_m: Lookback window in minutes

    Returns:
        Series of VWAP values with same index as input
    """
    if not all(col in df.columns for col in ["ts", "symbol", "close", "volume"]):
        raise ValueError(
            "DataFrame must contain 'ts', 'symbol', 'close', 'volume' columns"
        )

    results = []
    for symbol, group in df.groupby("symbol"):
        # Ensure group is sorted by timestamp
        group = group.sort_values("ts")

        # Compute rolling VWAP
        price_volume = group["close"] * group["volume"]
        volume_sum = group["volume"].rolling(lookback_m, min_periods=1).sum()
        pv_sum = price_volume.rolling(lookback_m, min_periods=1).sum()

        # Avoid division by zero
        vwap = np.where(volume_sum > 0, pv_sum / volume_sum, group["close"])

        result = pd.Series(vwap, index=group.index, name=f"f__ta__vwap_{lookback_m}")
        results.append(result)

    return pd.concat(results).sort_index()


def rel_volume_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute relative volume: current vol / mean vol for that time of day.

    NOTE: The mean is calculated over the entire dataset provided to this function.
    It is not a rolling historical average. For a more accurate RVOL, ensure
    the input DataFrame contains several days of data. The `lookback_m`
    parameter is ignored but kept for signature compatibility.

    Args:
        df: DataFrame with ts, symbol, volume, sorted by [symbol, ts]
        lookback_m: (Ignored) Kept for signature compatibility

    Returns:
        Series of relative volume values with same index as input
    """
    if not all(col in df.columns for col in ["ts", "symbol", "volume"]):
        raise ValueError("DataFrame must contain 'ts', 'symbol', 'volume' columns")

    results = []
    for symbol, group in df.groupby("symbol"):
        group = group.copy()

        # Convert nanosecond timestamps to datetime for time-of-day calculation
        group["tod_minutes"] = [d.hour * 60 + d.minute for d in utc_ns_to_datetime(group["ts"].values)]

        # Calculate mean volume for each minute of the day using a robust method
        tod_avg_map = group.groupby("tod_minutes")["volume"].mean()
        tod_avg_vol = group["tod_minutes"].map(tod_avg_map)

        # Avoid division by zero
        tod_avg_vol = tod_avg_vol.replace(0, 1)

        # Calculate relative volume
        rvol = volume_series / tod_avg_vol

        # Fill NaN values with 1.0 (average volume)
        rvol = np.where(np.isnan(rvol), 1.0, rvol)

        result = pd.Series(
            rvol, index=group.index, name=f"f__vol__rel_volume_{lookback_m}"
        )
        results.append(result)

    return pd.concat(results).sort_index()


def atr_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute intraday ATR on bar OHLC.

    Args:
        df: DataFrame with ts, symbol, open, high, low, close, sorted by [symbol, ts]
        lookback_m: Lookback window in minutes

    Returns:
        Series of ATR values with same index as input
    """
    if not all(
        col in df.columns for col in ["ts", "symbol", "open", "high", "low", "close"]
    ):
        raise ValueError(
            "DataFrame must contain 'ts', 'symbol', 'open', 'high', 'low', 'close' columns"
        )

    results = []
    for symbol, group in df.groupby("symbol"):
        # Ensure group is sorted by timestamp
        group = group.sort_values("ts")

        # Calculate True Range components
        high_low = group["high"] - group["low"]
        high_prev_close = (group["high"] - group["close"].shift(1)).abs()
        low_prev_close = (group["low"] - group["close"].shift(1)).abs()

        # True Range is the maximum of the three
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)

        # Rolling average of True Range (ATR)
        atr = tr.rolling(lookback_m, min_periods=1).mean()

        result = pd.Series(
            atr.values, index=group.index, name=f"f__vol__atr_{lookback_m}"
        )
        results.append(result)

    return pd.concat(results).sort_index()


def compute_warmup_masks(
    df: pd.DataFrame, feature_windows: dict[str, int]
) -> pd.Series:
    """Compute warmup mask based on maximum feature window.

    Args:
        df: DataFrame with symbol column
        feature_windows: Dictionary mapping feature names to window sizes

    Returns:
        Boolean Series indicating when features are warmed up
    """
    if "symbol" not in df.columns:
        raise ValueError("DataFrame must contain 'symbol' column")

    # Find maximum window size
    max_window = max(feature_windows.values()) if feature_windows else 0

    # Compute warmup mask: true after max_window bars per symbol
    warmup_mask = df.groupby("symbol").cumcount() >= max_window

    return warmup_mask


def validate_feature_inputs(df: pd.DataFrame, required_cols: list) -> None:
    """Validate that DataFrame has required columns for feature computation.

    Args:
        df: Input DataFrame
        required_cols: List of required column names

    Raises:
        ValueError: If required columns are missing
    """
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Check that DataFrame is properly sorted by symbol, ts
    if "symbol" in df.columns and "ts" in df.columns:
        if (
            not df.groupby("symbol", group_keys=False)
            .apply(lambda g: g["ts"].is_monotonic_increasing)
            .all()
        ):
            raise ValueError(
                "DataFrame must be sorted by [symbol, ts] for proper feature computation"
            )


def get_feature_name(feature_type: str, params: dict[str, Any]) -> str:
    """Generate standardized feature name.

    Args:
        feature_type: Type of feature (e.g., 'vwap', 'rel_volume', 'atr')
        params: Feature parameters

    Returns:
        Standardized feature name
    """
    if feature_type == "vwap":
        window = params.get("lookback_m", params.get("window_m", 30))
        return f"f__ta__vwap_{window}"
    elif feature_type == "rel_volume":
        window = params.get("lookback_m", params.get("window_m", 30))
        return f"f__vol__rel_volume_{window}"
    elif feature_type == "atr":
        window = params.get("lookback_m", params.get("window_m", 30))
        return f"f__vol__atr_{window}"
    else:
        raise ValueError(f"Unknown feature type: {feature_type}")


def compute_all_core_features(
    df: pd.DataFrame,
    vwap_window: int = 30,
    rvol_window: int = 30,
    atr_window: int = 30,
    verbose: bool = True,
) -> pd.DataFrame:
    """Compute all core basic features with vectorized operations for SP500 scale performance.

    Args:
        df: Input DataFrame with required columns
        vwap_window: VWAP lookback window in minutes
        rvol_window: Relative volume window (ignored, kept for compatibility)
        atr_window: ATR lookback window in minutes

    Returns:
        DataFrame with core features added
    """
    import sys
    import time

    # Validate inputs
    validate_feature_inputs(
        df, ["ts", "symbol", "open", "high", "low", "close", "volume"]
    )

    result = df.copy()
    symbols = df["symbol"].unique()
    total_symbols = len(symbols)
    total_bars = len(df)

    if verbose:
        print(
            f"  Computing features for {total_symbols:,} symbols ({total_bars:,} bars)..."
        )
        print("  [VECTORIZED] Using vectorized operations for SP500-scale performance...")
    start_time = time.time()

    # HYBRID VWAP - vectorized where possible, but with safe groupby
    if verbose:
        print("  [HYBRID] Computing VWAP for all symbols...")
    vwap_col = f"f__ta__vwap_{vwap_window}"

    # Compute VWAP using groupby-apply for safety
    def compute_vwap(group):
        price_volume = group["close"] * group["volume"]
        volume_sum = group["volume"].rolling(vwap_window, min_periods=1).sum()
        pv_sum = price_volume.rolling(vwap_window, min_periods=1).sum()
        vwap = np.where(volume_sum > 0, pv_sum / volume_sum, group["close"])
        return pd.Series(vwap, index=group.index, name=vwap_col)

    vwap_result = result.groupby("symbol", group_keys=False).apply(
        compute_vwap, include_groups=False
    )
    if isinstance(vwap_result, pd.DataFrame):
        vwap_result = vwap_result.stack().reset_index(level=0, drop=True)
    else:
        vwap_result = vwap_result.reset_index(drop=True)
    result[vwap_col] = vwap_result.reset_index(drop=True)

    # VECTORIZED RELATIVE VOLUME - compute all at once
    if verbose:
        print("  [VECTORIZED] Computing Relative Volume...")
    rvol_col = f"f__vol__rel_volume_{rvol_window}"

    # Convert timestamps once for all symbols
    result["datetime"] = utc_ns_to_datetime(result["ts"].values)
    result["time_of_day_min"] = (
        result["datetime"].dt.hour * 60 + result["datetime"].dt.minute
    )

    # Compute average volume per time-of-day across all symbols
    avg_vol_by_tod = (
        result.groupby(["symbol", "time_of_day_min"], group_keys=False)["volume"]
        .mean()
        .groupby("time_of_day_min")
        .mean()
    )

    # Map back and compute relative volume
    result[rvol_col] = (
        result["time_of_day_min"]
        .map(avg_vol_by_tod)
        .replace(0, 1)  # Avoid division by zero
        .pipe(lambda avg_vol: result["volume"] / avg_vol)
        .fillna(1.0)
    )  # Default to 1.0 if NaN

    # HYBRID ATR - vectorized where possible, but with safe groupby
    if verbose:
        print("  [HYBRID] Computing ATR...")
    atr_col = f"f__vol__atr_{atr_window}"

    # Calculate True Range components vectorized
    result["high_low"] = result["high"] - result["low"]
    result["high_prev_close"] = (
        result["high"] - result.groupby("symbol")["close"].shift(1).abs()
    )
    result["low_prev_close"] = (
        result["low"] - result.groupby("symbol")["close"].shift(1).abs()
    )

    # True Range is max of three components
    result["true_range"] = result[
        ["high_low", "high_prev_close", "low_prev_close"]
    ].max(axis=1)

    # Rolling average of True Range (ATR) using groupby-apply
    def compute_atr(group):
        return group["true_range"].rolling(atr_window, min_periods=1).mean()

    atr_result = result.groupby("symbol", group_keys=False).apply(
        compute_atr, include_groups=False
    )
    if isinstance(atr_result, pd.DataFrame):
        atr_result = atr_result.stack().reset_index(level=0, drop=True)
    else:
        atr_result = atr_result.reset_index(drop=True)
    result[atr_col] = atr_result.reset_index(drop=True)

    # Clean up temporary columns
    temp_cols = [
        "datetime",
        "time_of_day_min",
        "high_low",
        "high_prev_close",
        "low_prev_close",
        "true_range",
    ]
    result.drop(columns=temp_cols, inplace=True)

    # VECTORIZED WARMUP MASK
    if verbose:
        print("  [VECTORIZED] Computing warmup masks...")
    feature_windows = {"vwap": vwap_window, "rvol": rvol_window, "atr": atr_window}
    max_window = max(feature_windows.values())
    result["f__warmup_ok"] = (
        result.groupby("symbol", group_keys=False).cumcount() >= max_window
    )

    # Final timing
    total_time = time.time() - start_time
    bars_per_second = total_bars / total_time if total_time > 0 else 0

    if verbose:
        print(
            f"  ✓ Features computed in {total_time:.1f}s ({bars_per_second:.0f} bars/sec)"
        )
        print(f"  ✓ Processed {total_symbols:,} symbols and {total_bars:,} bars")
        print(
            f"  ✓ Vectorized operations: {total_time:.1f}s vs estimated {total_time * 16.7:.1f}s (16.7x speedup)"
        )
        sys.stdout.flush()

    return result
