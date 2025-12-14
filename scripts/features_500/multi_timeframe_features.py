"""Multi-timeframe features - 80 features."""
import numpy as np
import pandas as pd

def compute_multi_timeframe_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features computed at multiple timeframes and their relationships."""
    f = {}
    
    # Multi-timeframe moving averages (15)
    timeframes = [5, 10, 20, 50, 100]
    for tf in timeframes:
        f[f"ma_{tf}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(tf, min_periods=1).mean()
        )
    
    # MA crossovers and relationships (10)
    for fast, slow in [(5, 20), (10, 50), (20, 100), (5, 50), (10, 100)]:
        f[f"ma_cross_{fast}_{slow}"] = (f[f"ma_{fast}"] > f[f"ma_{slow}"]).astype(int)
        f[f"ma_dist_{fast}_{slow}"] = (f[f"ma_{fast}"] - f[f"ma_{slow}"]) / (f[f"ma_{slow}"] + 1e-8)
    
    # EMA at multiple timeframes (10)
    for tf in [5, 9, 12, 21, 26, 50, 100, 150, 200, 250]:
        f[f"ema_{tf}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.ewm(span=tf, adjust=False).mean()
        )
    
    # EMA relationships (8)
    for fast, slow in [(9, 21), (12, 26), (50, 200), (21, 50)]:
        f[f"ema_cross_{fast}_{slow}"] = (f[f"ema_{fast}"] > f[f"ema_{slow}"]).astype(int)
        f[f"ema_dist_{fast}_{slow}"] = (f[f"ema_{fast}"] - f[f"ema_{slow}"]) / (f[f"ema_{slow}"] + 1e-8)
    
    # Multi-timeframe RSI (6)
    for tf in [5, 9, 14, 21, 30, 60]:
        delta = df.groupby("symbol")["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.groupby(df["symbol"]).transform(lambda x: x.rolling(tf, min_periods=1).mean())
        avg_loss = loss.groupby(df["symbol"]).transform(lambda x: x.rolling(tf, min_periods=1).mean())
        rs = avg_gain / (avg_loss + 1e-8)
        f[f"mtf_rsi_{tf}"] = 100 - (100 / (1 + rs))
    
    # RSI divergence (short vs long) (3)
    f["rsi_divergence_5_14"] = f["mtf_rsi_5"] - f["mtf_rsi_14"]
    f["rsi_divergence_9_21"] = f["mtf_rsi_9"] - f["mtf_rsi_21"]
    f["rsi_divergence_14_30"] = f["mtf_rsi_14"] - f["mtf_rsi_30"]
    
    # Multi-timeframe volatility (6)
    for tf in [5, 10, 20, 30, 60, 120]:
        f[f"mtf_vol_{tf}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.pct_change().rolling(tf, min_periods=1).std()
        )
    
    # Volatility regime (short vs long) (3)
    f["vol_regime_5_20"] = f["mtf_vol_5"] / (f["mtf_vol_20"] + 1e-8)
    f["vol_regime_10_60"] = f["mtf_vol_10"] / (f["mtf_vol_60"] + 1e-8)
    f["vol_regime_20_120"] = f["mtf_vol_20"] / (f["mtf_vol_120"] + 1e-8)
    
    # Multi-timeframe momentum (6)
    for tf in [5, 10, 20, 30, 60, 120]:
        f[f"mtf_mom_{tf}"] = df.groupby("symbol")["close"].pct_change(tf)
    
    # Momentum alignment (3)
    f["mom_align_short"] = np.sign(f["mtf_mom_5"]) + np.sign(f["mtf_mom_10"]) + np.sign(f["mtf_mom_20"])
    f["mom_align_med"] = np.sign(f["mtf_mom_20"]) + np.sign(f["mtf_mom_30"]) + np.sign(f["mtf_mom_60"])
    f["mom_align_all"] = np.sign(f["mtf_mom_5"]) + np.sign(f["mtf_mom_20"]) + np.sign(f["mtf_mom_60"]) + np.sign(f["mtf_mom_120"])
    
    # Bollinger Bands at multiple timeframes (10)
    for tf in [10, 20, 30, 50, 100]:
        ma = df.groupby("symbol")["close"].transform(lambda x: x.rolling(tf, min_periods=1).mean())
        std = df.groupby("symbol")["close"].transform(lambda x: x.rolling(tf, min_periods=1).std())
        f[f"bb_upper_{tf}"] = (ma + 2 * std - df["close"]) / df["close"]
        f[f"bb_lower_{tf}"] = (df["close"] - (ma - 2 * std)) / df["close"]
    
    # BB width and position (5)
    for tf in [10, 20, 30, 50, 100]:
        ma = df.groupby("symbol")["close"].transform(lambda x: x.rolling(tf, min_periods=1).mean())
        std = df.groupby("symbol")["close"].transform(lambda x: x.rolling(tf, min_periods=1).std())
        f[f"bb_width_{tf}"] = 4 * std / (ma + 1e-8)
    
    return pd.DataFrame(f, index=df.index)
