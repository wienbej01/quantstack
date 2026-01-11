"""Compute features for pattern discovery using qx-features."""

import pandas as pd


def compute_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute momentum features (returns over various windows).

    Args:
        df: DataFrame with ts, symbol, close

    Returns:
        DataFrame with momentum features added
    """
    result = df.copy()

    symbols = result["symbol"].unique()
    print(f"  Computing for {len(symbols)} symbols...")

    for idx, (symbol, group) in enumerate(result.groupby("symbol"), 1):
        if idx % 10 == 0:
            print(f"    {idx}/{len(symbols)} symbols processed")

        group = group.sort_values("ts")

        # Returns over different windows
        for window in [5, 15, 30, 60]:
            ret = group["close"].pct_change(window)
            result.loc[group.index, f"ret_{window}m"] = ret

    return result


def compute_vwap_features(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Compute VWAP and price deviation.

    Args:
        df: DataFrame with ts, symbol, close, volume
        window: VWAP window in bars

    Returns:
        DataFrame with VWAP features added
    """
    result = df.copy()

    for symbol, group in result.groupby("symbol"):
        group = group.sort_values("ts")

        # Rolling VWAP
        pv = (group["close"] * group["volume"]).rolling(window, min_periods=1).sum()
        vol_sum = group["volume"].rolling(window, min_periods=1).sum()
        vwap = pv / vol_sum.replace(0, 1)

        # Price vs VWAP
        price_vs_vwap = (group["close"] - vwap) / vwap * 100

        result.loc[group.index, f"vwap_{window}"] = vwap
        result.loc[group.index, "price_vs_vwap_pct"] = price_vs_vwap

    return result


def compute_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute relative volume (time-of-day normalized).

    Args:
        df: DataFrame with ts, symbol, volume

    Returns:
        DataFrame with volume features added
    """
    result = df.copy()

    # Convert ts to datetime
    result["dt"] = pd.to_datetime(result["ts"], unit="ns", utc=True)
    result["dt_et"] = result["dt"].dt.tz_convert("America/New_York")
    result["minute_of_day"] = result["dt_et"].dt.hour * 60 + result["dt_et"].dt.minute

    for symbol, group in result.groupby("symbol"):
        # Average volume per minute-of-day
        tod_avg = group.groupby("minute_of_day")["volume"].transform("mean")
        rvol = group["volume"] / tod_avg.replace(0, 1)

        result.loc[group.index, "rvol"] = rvol

    return result


def compute_atr_features(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """Compute ATR (Average True Range).

    Args:
        df: DataFrame with ts, symbol, high, low, close
        window: ATR window in bars

    Returns:
        DataFrame with ATR features added
    """
    result = df.copy()

    for symbol, group in result.groupby("symbol"):
        group = group.sort_values("ts")

        # True range
        high_low = group["high"] - group["low"]
        high_close = abs(group["high"] - group["close"].shift(1))
        low_close = abs(group["low"] - group["close"].shift(1))

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window, min_periods=1).mean()

        result.loc[group.index, f"atr_{window}"] = atr

    return result


def compute_session_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute session-anchored features.

    Args:
        df: DataFrame with ts, symbol, close, volume

    Returns:
        DataFrame with session features added
    """
    result = df.copy()

    # Ensure datetime columns exist
    if "dt_et" not in result.columns:
        result["dt"] = pd.to_datetime(result["ts"], unit="ns", utc=True)
        result["dt_et"] = result["dt"].dt.tz_convert("America/New_York")

    result["session_date"] = result["dt_et"].dt.date

    for symbol, group in result.groupby("symbol"):
        group = group.sort_values("ts")

        # Session AVWAP (cumulative from 9:30)
        for session_date, session_group in group.groupby("session_date"):
            pv_cumsum = (session_group["close"] * session_group["volume"]).cumsum()
            vol_cumsum = session_group["volume"].cumsum()
            session_avwap = pv_cumsum / vol_cumsum.replace(0, 1)

            price_vs_avwap = (
                (session_group["close"] - session_avwap) / session_avwap * 100
            )

            result.loc[session_group.index, "session_avwap"] = session_avwap
            result.loc[session_group.index, "price_vs_session_avwap_pct"] = (
                price_vs_avwap
            )

    return result


def compute_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute time-of-day features.

    Args:
        df: DataFrame with ts

    Returns:
        DataFrame with time features added
    """
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


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all features for pattern discovery.

    Args:
        df: DataFrame with ts, symbol, OHLCV

    Returns:
        DataFrame with all features added
    """
    result = df.copy()

    print("Computing momentum features...")
    result = compute_momentum_features(result)

    print("Computing VWAP features...")
    result = compute_vwap_features(result)

    print("Computing volume features...")
    result = compute_volume_features(result)

    print("Computing ATR features...")
    result = compute_atr_features(result)

    print("Computing session features...")
    result = compute_session_features(result)

    print("Computing time features...")
    result = compute_time_features(result)

    return result
