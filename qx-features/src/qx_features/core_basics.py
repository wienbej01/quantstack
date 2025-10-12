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
    # Assume df is sorted by symbol, ts
    # Group by symbol and compute rolling VWAP
    def _vwap_symbol(group):
        price_volume = group['close'] * group['volume']
        volume_sum = group['volume'].rolling(lookback_m, min_periods=1).sum()
        pv_sum = price_volume.rolling(lookback_m, min_periods=1).sum()
        return pv_sum / volume_sum

    return df.groupby('symbol', group_keys=False).transform(_vwap_symbol)


def rel_volume_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute relative volume: current vol / rolling mean vol.

    Args:
        df: DataFrame with ts, symbol, volume
        lookback_m: Lookback window in minutes

    Returns:
        Series of relative volume values
    """
    def _rel_vol_symbol(group):
        vol_mean = group['volume'].rolling(lookback_m, min_periods=1).mean()
        return group['volume'] / vol_mean

    return df.groupby('symbol', group_keys=False).transform(_rel_vol_symbol)


def atr_m(df: pd.DataFrame, lookback_m: int) -> pd.Series:
    """Compute intraday ATR on bar OHLC.

    Args:
        df: DataFrame with ts, symbol, open, high, low, close
        lookback_m: Lookback window in minutes

    Returns:
        Series of ATR values
    """
    def _atr(group):
        high_low = group['high'] - group['low']
        high_prev_close = (group['high'] - group['close'].shift(1)).abs()
        low_prev_close = (group['low'] - group['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        return tr.rolling(lookback_m, min_periods=1).mean()

    return df.groupby('symbol', group_keys=False).apply(_atr)