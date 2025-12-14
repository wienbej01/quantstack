"""Base price/volume features - 80 features."""
import numpy as np
import pandas as pd

def compute_base_features(df: pd.DataFrame) -> pd.DataFrame:
    """Price, volume, and basic technical features."""
    f = {}
    
    # Returns at multiple timeframes (10)
    for lb in [1, 2, 3, 5, 10, 15, 20, 30, 60, 120]:
        f[f"ret_{lb}"] = df.groupby("symbol")["close"].pct_change(lb)
    
    # Log returns (5)
    for lb in [1, 5, 10, 20, 60]:
        f[f"log_ret_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: np.log(x / x.shift(lb))
        )
    
    # Volume features (10)
    for lb in [5, 10, 20, 30, 60]:
        f[f"vol_ma_{lb}"] = df.groupby("symbol")["volume"].transform(
            lambda x: x.rolling(lb, min_periods=1).mean()
        )
        f[f"vol_ratio_{lb}"] = df["volume"] / (f[f"vol_ma_{lb}"] + 1)
    
    # Price relative to moving averages (10)
    for lb in [5, 10, 20, 50, 100]:
        ma = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(lb, min_periods=1).mean()
        )
        f[f"price_ma_{lb}"] = (df["close"] - ma) / (ma + 1e-8)
        f[f"ma_slope_{lb}"] = df.groupby("symbol")[f"price_ma_{lb}"].transform(
            lambda x: x.diff(5)
        ) if f"price_ma_{lb}" in f else 0
    
    # Volatility (10)
    for lb in [5, 10, 20, 30, 60]:
        f[f"volatility_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.pct_change().rolling(lb, min_periods=1).std()
        )
        f[f"vol_of_vol_{lb}"] = df.groupby("symbol")[f"volatility_{lb}"].transform(
            lambda x: x.rolling(lb, min_periods=1).std()
        ) if f"volatility_{lb}" in f else 0
    
    # High-Low range (10)
    for lb in [5, 10, 20, 30, 60]:
        f[f"range_{lb}"] = df.groupby("symbol").apply(
            lambda g: (g["high"].rolling(lb).max() - g["low"].rolling(lb).min()) / g["close"]
        ).reset_index(level=0, drop=True)
        f[f"range_pct_{lb}"] = (df["high"] - df["low"]) / df["close"]
    
    # OHLC relationships (10)
    f["body"] = (df["close"] - df["open"]) / (df["high"] - df["low"] + 1e-8)
    f["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / (df["high"] - df["low"] + 1e-8)
    f["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / (df["high"] - df["low"] + 1e-8)
    f["close_position"] = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-8)
    f["open_position"] = (df["open"] - df["low"]) / (df["high"] - df["low"] + 1e-8)
    f["gap"] = df.groupby("symbol")["open"].transform(lambda x: x / x.shift(1) - 1)
    f["intraday_ret"] = (df["close"] - df["open"]) / df["open"]
    f["high_ret"] = (df["high"] - df["open"]) / df["open"]
    f["low_ret"] = (df["low"] - df["open"]) / df["open"]
    f["true_range"] = df[["high", "low", "close"]].apply(
        lambda r: max(r["high"] - r["low"], abs(r["high"] - r["close"]), abs(r["low"] - r["close"])), axis=1
    ) / df["close"]
    
    # ATR (5)
    for lb in [5, 10, 14, 20, 30]:
        f[f"atr_{lb}"] = df.groupby("symbol")["true_range"].transform(
            lambda x: x.rolling(lb, min_periods=1).mean()
        ) if "true_range" in f else 0
    
    return pd.DataFrame(f, index=df.index)
