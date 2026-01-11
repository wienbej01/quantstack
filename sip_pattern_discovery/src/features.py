"""Compute features for pattern discovery using qx-features."""

from functools import partial
from multiprocessing import Pool

import pandas as pd


def compute_momentum_features_for_symbol(symbol_group: tuple) -> pd.DataFrame:
    """Compute momentum features for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    for window in [5, 15, 30, 60]:
        ret = group["close"].pct_change(window)
        group[f"ret_{window}m"] = ret

    return group


def compute_momentum_features(df: pd.DataFrame, n_workers: int = 6) -> pd.DataFrame:
    """Compute momentum features (returns over various windows) in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    with Pool(n_workers) as pool:
        results = pool.map(compute_momentum_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_vwap_features_for_symbol(
    symbol_group: tuple, window: int = 30
) -> pd.DataFrame:
    """Compute VWAP features for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    # Rolling VWAP
    pv = (group["close"] * group["volume"]).rolling(window, min_periods=1).sum()
    vol_sum = group["volume"].rolling(window, min_periods=1).sum()
    vwap = pv / vol_sum.replace(0, 1)

    # Price vs VWAP
    price_vs_vwap = (group["close"] - vwap) / vwap * 100

    group[f"vwap_{window}"] = vwap
    group["price_vs_vwap_pct"] = price_vs_vwap

    return group


def compute_vwap_features(
    df: pd.DataFrame, window: int = 30, n_workers: int = 6
) -> pd.DataFrame:
    """Compute VWAP and price deviation in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing VWAP for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]
    compute_func = partial(compute_vwap_features_for_symbol, window=window)

    with Pool(n_workers) as pool:
        results = pool.map(compute_func, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_volume_features_for_symbol(symbol_group: tuple) -> pd.DataFrame:
    """Compute volume features for a single symbol."""
    symbol, group = symbol_group
    group = group.copy()

    # Convert ts to datetime
    group["dt"] = pd.to_datetime(group["ts"], unit="ns", utc=True)
    group["dt_et"] = group["dt"].dt.tz_convert("America/New_York")
    group["minute_of_day"] = group["dt_et"].dt.hour * 60 + group["dt_et"].dt.minute

    # Average volume per minute-of-day
    tod_avg = group.groupby("minute_of_day")["volume"].transform("mean")
    rvol = group["volume"] / tod_avg.replace(0, 1)
    group["rvol"] = rvol

    return group


def compute_volume_features(df: pd.DataFrame, n_workers: int = 6) -> pd.DataFrame:
    """Compute relative volume (time-of-day normalized) in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing volume for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    with Pool(n_workers) as pool:
        results = pool.map(compute_volume_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_atr_features_for_symbol(
    symbol_group: tuple, window: int = 14
) -> pd.DataFrame:
    """Compute ATR for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    # True range
    high_low = group["high"] - group["low"]
    high_close = abs(group["high"] - group["close"].shift(1))
    low_close = abs(group["low"] - group["close"].shift(1))

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window, min_periods=1).mean()
    group[f"atr_{window}"] = atr

    return group


def compute_atr_features(
    df: pd.DataFrame, window: int = 14, n_workers: int = 6
) -> pd.DataFrame:
    """Compute ATR (Average True Range) in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing ATR for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]
    compute_func = partial(compute_atr_features_for_symbol, window=window)

    with Pool(n_workers) as pool:
        results = pool.map(compute_func, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_session_features_for_symbol(symbol_group: tuple) -> pd.DataFrame:
    """Compute session features for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    # Ensure datetime columns exist
    if "dt_et" not in group.columns:
        group["dt"] = pd.to_datetime(group["ts"], unit="ns", utc=True)
        group["dt_et"] = group["dt"].dt.tz_convert("America/New_York")

    group["session_date"] = group["dt_et"].dt.date

    # Session AVWAP (cumulative from 9:30)
    for session_date, session_group in group.groupby("session_date"):
        pv_cumsum = (session_group["close"] * session_group["volume"]).cumsum()
        vol_cumsum = session_group["volume"].cumsum()
        session_avwap = pv_cumsum / vol_cumsum.replace(0, 1)

        price_vs_avwap = (session_group["close"] - session_avwap) / session_avwap * 100

        group.loc[session_group.index, "session_avwap"] = session_avwap
        group.loc[session_group.index, "price_vs_session_avwap_pct"] = price_vs_avwap

    return group


def compute_session_features(df: pd.DataFrame, n_workers: int = 6) -> pd.DataFrame:
    """Compute session-anchored features in parallel."""
    symbols = df["symbol"].unique()
    print(
        f"  Computing session features for {len(symbols)} symbols using {n_workers} workers..."
    )

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    with Pool(n_workers) as pool:
        results = pool.map(compute_session_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute time-of-day features."""
    result = df.copy()

    if "dt_et" not in result.columns:
        result["dt"] = pd.to_datetime(result["ts"], unit="ns", utc=True)
        result["dt_et"] = result["dt"].dt.tz_convert("America/New_York")

    result["hour_et"] = result["dt_et"].dt.hour
    result["minute_et"] = result["dt_et"].dt.minute

    # Kill zones
    result["is_first_hour"] = (
        (result["hour_et"] == 9) & (result["minute_et"] >= 30)
    ) | (result["hour_et"] == 10)
    result["is_power_hour"] = result["hour_et"] == 15

    return result


def compute_spy_regime_features(df: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
    """Add SPY regime features to dataframe."""
    result = df.copy()

    if spy_df.empty:
        # No SPY data - add neutral defaults
        result["spy_above_sma20"] = True
        result["spy_ret_60m"] = 0.0
        return result

    # Compute SPY features
    spy = spy_df.sort_values("ts").copy()
    spy["sma20"] = spy["close"].rolling(20, min_periods=1).mean()
    spy["spy_above_sma20"] = spy["close"] > spy["sma20"]
    spy["spy_ret_60m"] = spy["close"].pct_change(60)

    # Merge on ts (nearest match)
    spy_features = spy[["ts", "spy_above_sma20", "spy_ret_60m"]].copy()
    spy_features = spy_features.rename(columns={"ts": "spy_ts"})

    # Use merge_asof for time-based join
    result = result.sort_values("ts")
    spy_features = spy_features.sort_values("spy_ts")

    result = pd.merge_asof(
        result,
        spy_features,
        left_on="ts",
        right_on="spy_ts",
        direction="backward",
    )

    # Fill any missing values
    result["spy_above_sma20"] = result["spy_above_sma20"].fillna(True)
    result["spy_ret_60m"] = result["spy_ret_60m"].fillna(0.0)

    # Drop merge column
    if "spy_ts" in result.columns:
        result = result.drop(columns=["spy_ts"])

    return result


def compute_all_features(
    df: pd.DataFrame, spy_df: pd.DataFrame | None = None, n_workers: int = 6
) -> pd.DataFrame:
    """Compute all features for pattern discovery in parallel.

    Args:
        df: DataFrame with ts, symbol, OHLCV
        spy_df: Optional SPY 1m bars for regime features
        n_workers: Number of parallel workers (max 6)

    Returns:
        DataFrame with all features added
    """
    n_workers = min(n_workers, 6)  # Cap at 6 workers
    result = df.copy()

    print("Computing momentum features...")
    result = compute_momentum_features(result, n_workers)

    print("Computing VWAP features...")
    result = compute_vwap_features(result, n_workers=n_workers)

    print("Computing volume features...")
    result = compute_volume_features(result, n_workers)

    print("Computing ATR features...")
    result = compute_atr_features(result, n_workers=n_workers)

    print("Computing session features...")
    result = compute_session_features(result, n_workers)

    print("Computing time features...")
    result = compute_time_features(result)

    if spy_df is not None and not spy_df.empty:
        print("Computing SPY regime features...")
        result = compute_spy_regime_features(result, spy_df)

    return result
