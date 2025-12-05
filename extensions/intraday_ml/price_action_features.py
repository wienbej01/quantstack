"""Price action features for directional prediction."""

import numpy as np
import pandas as pd


def add_all_price_action_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all price action features."""
    
    # Rate of Change (momentum)
    for period in [3, 6, 12]:
        df[f"f__momentum__roc_{period}"] = df["close"].pct_change(period) * 100
    
    # RSI
    for period in [6, 12]:
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss.replace(0, np.inf)
        df[f"f__momentum__rsi_{period}"] = 100 - (100 / (1 + rs))
    
    # Momentum (price difference)
    for period in [3, 6, 12]:
        df[f"f__momentum__diff_{period}"] = df["close"] - df["close"].shift(period)
    
    # EMA
    for period in [3, 6, 12, 18]:
        df[f"f__trend__ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    
    # Price vs EMA
    for period in [3, 6, 12]:
        ema_col = f"f__trend__ema_{period}"
        if ema_col in df.columns:
            df[f"f__trend__price_vs_ema_{period}"] = (df["close"] - df[ema_col]) / df[ema_col] * 100
    
    # EMA crosses
    if "f__trend__ema_3" in df.columns and "f__trend__ema_6" in df.columns:
        df["f__trend__ema_cross_3_6"] = df["f__trend__ema_3"] - df["f__trend__ema_6"]
    
    if "f__trend__ema_6" in df.columns and "f__trend__ema_12" in df.columns:
        df["f__trend__ema_cross_6_12"] = df["f__trend__ema_6"] - df["f__trend__ema_12"]
    
    # Trend strength (linear regression slope)
    for period in [6, 12]:
        df[f"f__trend__slope_{period}"] = df["close"].rolling(period).apply(
            lambda x: np.polyfit(np.arange(len(x)), x, 1)[0] if len(x) == period else np.nan,
            raw=True
        )
    
    # Bullish/bearish candles
    df["f__dir__bullish"] = (df["close"] > df["open"]).astype(int)
    df["f__dir__bearish"] = (df["close"] < df["open"]).astype(int)
    
    # Count consecutive bullish/bearish candles
    for period in [3, 6]:
        df[f"f__dir__bullish_count_{period}"] = df["f__dir__bullish"].rolling(period).sum()
        df[f"f__dir__bearish_count_{period}"] = df["f__dir__bearish"].rolling(period).sum()
    
    # Higher highs / lower lows
    for period in [3, 6]:
        df[f"f__dir__higher_high_{period}"] = (
            df["high"] > df["high"].shift(1)
        ).rolling(period).sum()
        df[f"f__dir__lower_low_{period}"] = (
            df["low"] < df["low"].shift(1)
        ).rolling(period).sum()
    
    # Price position in range
    for period in [6, 12]:
        high_max = df["high"].rolling(period).max()
        low_min = df["low"].rolling(period).min()
        range_size = high_max - low_min
        df[f"f__dir__range_position_{period}"] = (
            (df["close"] - low_min) / range_size.replace(0, np.inf)
        ).clip(0, 1)
    
    # Volume momentum
    for period in [3, 6]:
        df[f"f__vol__momentum_{period}"] = df["volume"].pct_change(period) * 100
    
    # Volume trend
    for period in [6, 12]:
        df[f"f__vol__trend_{period}"] = df["volume"].rolling(period).apply(
            lambda x: np.polyfit(np.arange(len(x)), x, 1)[0] if len(x) == period else np.nan,
            raw=True
        )
    
    # Price-volume correlation
    for period in [6, 12]:
        df[f"f__vol__price_corr_{period}"] = df["close"].rolling(period).corr(df["volume"])
    
    return df
