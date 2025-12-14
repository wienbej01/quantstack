"""Momentum and trend features - 60 features."""
import numpy as np
import pandas as pd

def compute_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    """RSI, MACD, momentum oscillators."""
    f = {}
    
    # RSI at multiple timeframes (6)
    for lb in [5, 9, 14, 21, 30, 60]:
        delta = df.groupby("symbol")["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.groupby(df["symbol"]).transform(lambda x: x.rolling(lb, min_periods=1).mean())
        avg_loss = loss.groupby(df["symbol"]).transform(lambda x: x.rolling(lb, min_periods=1).mean())
        rs = avg_gain / (avg_loss + 1e-8)
        f[f"rsi_{lb}"] = 100 - (100 / (1 + rs))
    
    # RSI derivatives (6)
    for lb in [5, 9, 14, 21, 30, 60]:
        if f"rsi_{lb}" in f:
            f[f"rsi_{lb}_slope"] = pd.Series(f[f"rsi_{lb}"]).diff(3)
    
    # Stochastic (8)
    for lb in [5, 9, 14, 21]:
        low_min = df.groupby("symbol")["low"].transform(lambda x: x.rolling(lb, min_periods=1).min())
        high_max = df.groupby("symbol")["high"].transform(lambda x: x.rolling(lb, min_periods=1).max())
        f[f"stoch_k_{lb}"] = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-8)
        f[f"stoch_d_{lb}"] = pd.Series(f[f"stoch_k_{lb}"]).rolling(3, min_periods=1).mean()
    
    # MACD variants (9)
    for fast, slow in [(8, 21), (12, 26), (5, 35)]:
        ema_fast = df.groupby("symbol")["close"].transform(lambda x: x.ewm(span=fast, adjust=False).mean())
        ema_slow = df.groupby("symbol")["close"].transform(lambda x: x.ewm(span=slow, adjust=False).mean())
        f[f"macd_{fast}_{slow}"] = (ema_fast - ema_slow) / df["close"]
        f[f"macd_signal_{fast}_{slow}"] = pd.Series(f[f"macd_{fast}_{slow}"]).ewm(span=9, adjust=False).mean()
        f[f"macd_hist_{fast}_{slow}"] = f[f"macd_{fast}_{slow}"] - f[f"macd_signal_{fast}_{slow}"]
    
    # Rate of change (6)
    for lb in [3, 5, 10, 20, 30, 60]:
        f[f"roc_{lb}"] = df.groupby("symbol")["close"].pct_change(lb)
    
    # Momentum (6)
    for lb in [3, 5, 10, 20, 30, 60]:
        f[f"momentum_{lb}"] = df.groupby("symbol")["close"].transform(lambda x: x - x.shift(lb))
    
    # Williams %R (4)
    for lb in [7, 14, 21, 28]:
        high_max = df.groupby("symbol")["high"].transform(lambda x: x.rolling(lb, min_periods=1).max())
        low_min = df.groupby("symbol")["low"].transform(lambda x: x.rolling(lb, min_periods=1).min())
        f[f"williams_r_{lb}"] = -100 * (high_max - df["close"]) / (high_max - low_min + 1e-8)
    
    # CCI (4)
    for lb in [10, 14, 20, 30]:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        tp_ma = df.groupby("symbol").apply(lambda g: tp.loc[g.index].rolling(lb, min_periods=1).mean()).reset_index(level=0, drop=True)
        tp_std = df.groupby("symbol").apply(lambda g: tp.loc[g.index].rolling(lb, min_periods=1).std()).reset_index(level=0, drop=True)
        f[f"cci_{lb}"] = (tp - tp_ma) / (0.015 * tp_std + 1e-8)
    
    # ADX approximation (4)
    for lb in [7, 14, 21, 28]:
        high_diff = df.groupby("symbol")["high"].diff()
        low_diff = -df.groupby("symbol")["low"].diff()
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
        tr = df["high"] - df["low"]
        f[f"plus_di_{lb}"] = pd.Series(plus_dm).rolling(lb, min_periods=1).sum() / (pd.Series(tr).rolling(lb, min_periods=1).sum() + 1e-8)
        f[f"minus_di_{lb}"] = pd.Series(minus_dm).rolling(lb, min_periods=1).sum() / (pd.Series(tr).rolling(lb, min_periods=1).sum() + 1e-8)
    
    # Trend strength (3)
    for lb in [10, 20, 30]:
        f[f"trend_strength_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: (x - x.rolling(lb, min_periods=1).min()) / (x.rolling(lb, min_periods=1).max() - x.rolling(lb, min_periods=1).min() + 1e-8)
        )
    
    return pd.DataFrame(f, index=df.index)
