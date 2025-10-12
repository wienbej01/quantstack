"""Core basic features pack."""

import pandas as pd


def add_core_basics(df: pd.DataFrame, **params) -> pd.DataFrame:
    """Add core basic features to the dataframe.

    Args:
        df: DataFrame with bars (ts, symbol, open, high, low, close, volume)
        **params:
            vwap_window_m: int, window in minutes for VWAP (default 30)
            rel_vol_window_m: int, window in minutes for relative volume (default 30)
            atr_window: int, window for ATR (default 14)

    Returns:
        DataFrame with added feature columns
    """
    vwap_window = params.get('vwap_window_m', 30)
    rel_vol_window = params.get('rel_vol_window_m', 30)
    atr_window = params.get('atr_window', 14)

    # Ensure sorted
    df = df.sort_values(['symbol', 'ts']).reset_index(drop=True)

    # Group by symbol and apply features
    def _add_features(group):
        # VWAP
        price_volume = group['close'] * group['volume']  # Use close as price
        volume_sum = group['volume'].rolling(vwap_window, min_periods=1).sum()
        pv_sum = price_volume.rolling(vwap_window, min_periods=1).sum()
        group = group.assign(f__ta__vwap_m=pv_sum / volume_sum)

        # Relative volume
        vol_mean = group['volume'].rolling(rel_vol_window, min_periods=1).mean()
        group = group.assign(f__vol__rel_volume_m=group['volume'] / vol_mean)

        # ATR
        high_low = group['high'] - group['low']
        high_prev_close = (group['high'] - group['close'].shift(1)).abs()
        low_prev_close = (group['low'] - group['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        atr = tr.rolling(atr_window, min_periods=1).mean()
        group = group.assign(f__vol__atr_m=atr)

        return group

    result = df.groupby('symbol', group_keys=False).apply(_add_features)

    # Fill NaN for warmup periods
    result = result.fillna(method='bfill')  # Backward fill for initial NaN

    return result