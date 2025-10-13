"""Core basic features pack."""

import pandas as pd


def vwap_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute rolling VWAP over lookback_m minutes.

    Args:
        df: DataFrame with ts, symbol, close, volume
        lookback_m: Lookback window in minutes

    Returns:
        Series of VWAP values
    """
    all_symbols_results = []
    for symbol, group in df.groupby('symbol'):
        price_volume = group['close'] * group['volume']
        volume_sum = group['volume'].rolling(lookback_m, min_periods=1).sum()
        pv_sum = price_volume.rolling(lookback_m, min_periods=1).sum()
        all_symbols_results.append(pv_sum / volume_sum)

    return pd.concat(all_symbols_results).sort_index()


def rel_volume_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute relative volume: current vol / mean vol for that time of day.

    NOTE: The mean is calculated over the entire dataset provided to this function.
    It is not a rolling historical average. For a more accurate RVOL, ensure
    the input DataFrame contains several days of data. The `lookback_m`
    parameter is ignored.

    Args:
        df: DataFrame with ts, symbol, volume. Must have a DatetimeIndex.
        lookback_m: (Ignored) Kept for signature compatibility.

    Returns:
        Series of relative volume values
    """
    all_symbols_results = []
    for symbol, group in df.groupby('symbol'):
        group = group.copy()
        
        # Convert the 'ts' COLUMN to datetime objects to get time-of-day
        ts_datetime = pd.to_datetime(group['ts'])

        # Calculate the average volume for each time of day across the group
        tod_avg_vol = group.groupby(ts_datetime.dt.time)['volume'].transform('mean')

        # Avoid division by zero
        tod_avg_vol = tod_avg_vol.replace(0, 1)

        rvol = group['volume'] / tod_avg_vol
        
        # Ensure the resulting series has the original index to align correctly
        rvol.index = group.index
        
        all_symbols_results.append(rvol.fillna(1.0))

    return pd.concat(all_symbols_results).sort_index()


def atr_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute intraday ATR on bar OHLC.

    Args:
        df: DataFrame with ts, symbol, open, high, low, close
        lookback_m: Lookback window in minutes

    Returns:
        Series of ATR values
    """
    all_symbols_results = []
    for symbol, group in df.groupby('symbol'):
        high_low = group['high'] - group['low']
        high_prev_close = (group['high'] - group['close'].shift(1)).abs()
        low_prev_close = (group['low'] - group['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        all_symbols_results.append(tr.rolling(lookback_m, min_periods=1).mean())

    return pd.concat(all_symbols_results).sort_index()