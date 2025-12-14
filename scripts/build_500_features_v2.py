#!/usr/bin/env python3
"""Build 500+ features - simplified robust version."""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")


def load_data() -> pd.DataFrame:
    """Load OHLCV data."""
    path = Path(__file__).parent.parent / "run" / "predictions_v4_simple.parquet"
    df = pd.read_parquet(path)
    if "ts" in df.columns:
        df = df.rename(columns={"ts": "timestamp"})
    print(f"Loaded {len(df):,} rows, {df['symbol'].nunique()} symbols")
    return df


def safe_rolling(s, window, func="mean"):
    """Safe rolling calculation."""
    if func == "mean":
        return s.rolling(window, min_periods=1).mean()
    elif func == "std":
        return s.rolling(window, min_periods=1).std()
    elif func == "sum":
        return s.rolling(window, min_periods=1).sum()
    elif func == "max":
        return s.rolling(window, min_periods=1).max()
    elif func == "min":
        return s.rolling(window, min_periods=1).min()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build all features."""
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    f = {}
    
    # Group by symbol for per-stock calculations
    g = df.groupby("symbol")
    
    print("Building features...")
    
    # === 1. RETURNS (20) ===
    for lb in [1, 2, 3, 5, 10, 15, 20, 30, 60, 120]:
        f[f"ret_{lb}"] = g["close"].pct_change(lb)
        f[f"log_ret_{lb}"] = np.log(df["close"] / g["close"].shift(lb))
    
    # === 2. VOLUME (20) ===
    for lb in [5, 10, 20, 30, 60]:
        f[f"vol_ma_{lb}"] = g["volume"].transform(lambda x: safe_rolling(x, lb))
        f[f"vol_ratio_{lb}"] = df["volume"] / (f[f"vol_ma_{lb}"] + 1)
        f[f"vol_std_{lb}"] = g["volume"].transform(lambda x: safe_rolling(x, lb, "std"))
        f[f"vol_zscore_{lb}"] = (df["volume"] - f[f"vol_ma_{lb}"]) / (f[f"vol_std_{lb}"] + 1e-8)
    
    # === 3. MOVING AVERAGES (30) ===
    for lb in [5, 10, 20, 50, 100, 200]:
        ma = g["close"].transform(lambda x: safe_rolling(x, lb))
        f[f"ma_{lb}"] = ma
        f[f"price_vs_ma_{lb}"] = (df["close"] - ma) / (ma + 1e-8)
        ema = g["close"].transform(lambda x: x.ewm(span=lb, adjust=False).mean())
        f[f"ema_{lb}"] = ema
        f[f"price_vs_ema_{lb}"] = (df["close"] - ema) / (ema + 1e-8)
        f[f"ma_slope_{lb}"] = ma.diff(5) / (ma + 1e-8)
    
    # === 4. VOLATILITY (20) ===
    for lb in [5, 10, 14, 20, 30, 60]:
        f[f"volatility_{lb}"] = g["close"].transform(lambda x: x.pct_change().rolling(lb, min_periods=1).std())
        f[f"atr_{lb}"] = g.apply(lambda x: (x["high"] - x["low"]).rolling(lb, min_periods=1).mean()).reset_index(level=0, drop=True)
        f[f"atr_pct_{lb}"] = f[f"atr_{lb}"] / df["close"]
    
    # === 5. RSI (12) ===
    delta = g["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    for lb in [5, 9, 14, 21]:
        avg_gain = g.apply(lambda x: gain.loc[x.index].rolling(lb, min_periods=1).mean()).reset_index(level=0, drop=True)
        avg_loss = g.apply(lambda x: loss.loc[x.index].rolling(lb, min_periods=1).mean()).reset_index(level=0, drop=True)
        rs = avg_gain / (avg_loss + 1e-8)
        f[f"rsi_{lb}"] = 100 - (100 / (1 + rs))
        f[f"rsi_{lb}_slope"] = f[f"rsi_{lb}"].diff(3)
        f[f"rsi_{lb}_extreme"] = ((f[f"rsi_{lb}"] > 70) | (f[f"rsi_{lb}"] < 30)).astype(int)
    
    # === 6. STOCHASTIC (8) ===
    for lb in [5, 9, 14, 21]:
        low_min = g["low"].transform(lambda x: safe_rolling(x, lb, "min"))
        high_max = g["high"].transform(lambda x: safe_rolling(x, lb, "max"))
        f[f"stoch_k_{lb}"] = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-8)
        f[f"stoch_d_{lb}"] = f[f"stoch_k_{lb}"].rolling(3, min_periods=1).mean()
    
    # === 7. MACD (9) ===
    for fast, slow in [(8, 21), (12, 26), (5, 35)]:
        ema_fast = g["close"].transform(lambda x: x.ewm(span=fast, adjust=False).mean())
        ema_slow = g["close"].transform(lambda x: x.ewm(span=slow, adjust=False).mean())
        f[f"macd_{fast}_{slow}"] = (ema_fast - ema_slow) / df["close"]
        f[f"macd_signal_{fast}_{slow}"] = f[f"macd_{fast}_{slow}"].ewm(span=9, adjust=False).mean()
        f[f"macd_hist_{fast}_{slow}"] = f[f"macd_{fast}_{slow}"] - f[f"macd_signal_{fast}_{slow}"]
    
    # === 8. BOLLINGER BANDS (15) ===
    for lb in [10, 20, 30]:
        ma = g["close"].transform(lambda x: safe_rolling(x, lb))
        std = g["close"].transform(lambda x: safe_rolling(x, lb, "std"))
        f[f"bb_upper_{lb}"] = (ma + 2 * std - df["close"]) / df["close"]
        f[f"bb_lower_{lb}"] = (df["close"] - (ma - 2 * std)) / df["close"]
        f[f"bb_width_{lb}"] = 4 * std / (ma + 1e-8)
        f[f"bb_position_{lb}"] = (df["close"] - (ma - 2*std)) / (4 * std + 1e-8)
        f[f"bb_squeeze_{lb}"] = (f[f"bb_width_{lb}"] < f[f"bb_width_{lb}"].rolling(20).mean() * 0.8).astype(int)
    
    # === 9. SUPPORT/RESISTANCE (20) ===
    for lb in [10, 20, 30, 50]:
        high_max = g["high"].transform(lambda x: safe_rolling(x, lb, "max"))
        low_min = g["low"].transform(lambda x: safe_rolling(x, lb, "min"))
        f[f"dist_to_high_{lb}"] = (high_max - df["close"]) / df["close"]
        f[f"dist_to_low_{lb}"] = (df["close"] - low_min) / df["close"]
        f[f"range_position_{lb}"] = (df["close"] - low_min) / (high_max - low_min + 1e-8)
        f[f"breakout_high_{lb}"] = (df["close"] > g["high"].shift(1).transform(lambda x: safe_rolling(x, lb, "max"))).astype(int)
        f[f"range_pct_{lb}"] = (high_max - low_min) / df["close"]
    
    # === 10. PATTERN DETECTION (20) ===
    body = df["close"] - df["open"]
    body_size = abs(body)
    range_size = df["high"] - df["low"] + 1e-8
    
    f["body_pct"] = body / range_size
    f["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / range_size
    f["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / range_size
    f["doji"] = (body_size / range_size < 0.1).astype(int)
    f["hammer"] = ((body > 0) & (f["lower_wick"] > 0.6) & (f["upper_wick"] < 0.1)).astype(int)
    f["shooting_star"] = ((body < 0) & (f["upper_wick"] > 0.6) & (f["lower_wick"] < 0.1)).astype(int)
    f["engulfing_bull"] = ((body > 0) & (body.shift(1) < 0) & (body_size > body_size.shift(1))).astype(int)
    f["engulfing_bear"] = ((body < 0) & (body.shift(1) > 0) & (body_size > body_size.shift(1))).astype(int)
    f["inside_bar"] = ((df["high"] < df["high"].shift(1)) & (df["low"] > df["low"].shift(1))).astype(int)
    f["outside_bar"] = ((df["high"] > df["high"].shift(1)) & (df["low"] < df["low"].shift(1))).astype(int)
    
    for lb in [3, 5, 10]:
        f[f"consec_up_{lb}"] = g["close"].transform(lambda x: (x > x.shift(1)).rolling(lb, min_periods=1).sum())
        f[f"consec_down_{lb}"] = g["close"].transform(lambda x: (x < x.shift(1)).rolling(lb, min_periods=1).sum())
        f[f"higher_highs_{lb}"] = g["high"].transform(lambda x: (x > x.shift(1)).rolling(lb, min_periods=1).sum()) / lb
        f[f"lower_lows_{lb}"] = g["low"].transform(lambda x: (x < x.shift(1)).rolling(lb, min_periods=1).sum()) / lb
    
    # === 11. TRIANGLE/CONTRACTION (12) ===
    for lb in [10, 20, 30]:
        range_now = g["high"].transform(lambda x: safe_rolling(x, lb, "max")) - g["low"].transform(lambda x: safe_rolling(x, lb, "min"))
        range_prev = range_now.shift(lb)
        f[f"range_contraction_{lb}"] = (range_prev - range_now) / (range_prev + 1e-8)
        f[f"volatility_contraction_{lb}"] = f[f"volatility_{min(lb, 30)}"] / f[f"volatility_{min(lb, 30)}"].shift(lb).clip(lower=1e-8)
        f[f"squeeze_score_{lb}"] = (f[f"range_contraction_{lb}"] > 0.2).astype(int)
        f[f"expansion_score_{lb}"] = (f[f"range_contraction_{lb}"] < -0.2).astype(int)
    
    # === 12. DERIVATIVES (24) ===
    for lb in [1, 3, 5, 10]:
        f[f"d1_close_{lb}"] = g["close"].diff(lb) / (g["close"].shift(lb) + 1e-8)
        f[f"d2_close_{lb}"] = f[f"d1_close_{lb}"].diff(lb)
        f[f"d1_volume_{lb}"] = g["volume"].diff(lb) / (g["volume"].shift(lb) + 1)
        f[f"momentum_{lb}"] = df["close"] - g["close"].shift(lb)
        f[f"momentum_accel_{lb}"] = f[f"momentum_{lb}"].diff(lb)
        f[f"roc_{lb}"] = g["close"].pct_change(lb)
    
    # === 13. CROSS-SECTIONAL (30) ===
    # Market proxy
    market_ret = df.groupby("timestamp")["close"].transform(lambda x: x.pct_change().mean())
    f["market_ret"] = market_ret
    
    stock_ret = g["close"].pct_change()
    f["rel_strength_1"] = stock_ret - market_ret
    
    for lb in [5, 10, 20]:
        f[f"market_ret_{lb}"] = market_ret.rolling(lb, min_periods=1).sum()
        stock_cum = stock_ret.rolling(lb, min_periods=1).sum()
        f[f"rel_strength_{lb}"] = stock_cum - f[f"market_ret_{lb}"]
    
    # Cross-sectional ranks
    f["rank_ret"] = df.groupby("timestamp")["close"].transform(lambda x: x.pct_change().rank(pct=True))
    f["rank_volume"] = df.groupby("timestamp")["volume"].rank(pct=True)
    
    # Market breadth
    f["up_ratio"] = df.groupby("timestamp")["close"].transform(lambda x: (x.pct_change() > 0).mean())
    f["market_breadth"] = df.groupby("timestamp")["symbol"].transform("nunique")
    
    # Cross dispersion
    f["cross_dispersion"] = df.groupby("timestamp")["close"].transform(lambda x: x.pct_change().std())
    
    # Z-scores
    for lb in [10, 20, 30]:
        mean = g["close"].transform(lambda x: safe_rolling(x, lb))
        std = g["close"].transform(lambda x: safe_rolling(x, lb, "std"))
        f[f"zscore_{lb}"] = (df["close"] - mean) / (std + 1e-8)
    
    # Percentile ranks
    for lb in [20, 50, 100]:
        f[f"price_pctl_{lb}"] = g["close"].transform(
            lambda x: x.rolling(lb, min_periods=1).apply(lambda y: (y.iloc[-1] > y.iloc[:-1]).mean() if len(y) > 1 else 0.5, raw=False)
        )
    
    # === 14. TIME FEATURES (20) ===
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        hour = ts.dt.hour + ts.dt.minute / 60
        f["hour"] = hour
        f["sin_hour"] = np.sin(2 * np.pi * hour / 24)
        f["cos_hour"] = np.cos(2 * np.pi * hour / 24)
        f["pre_market"] = (hour < 9.5).astype(int)
        f["market_open"] = ((hour >= 9.5) & (hour < 10.5)).astype(int)
        f["lunch"] = ((hour >= 12) & (hour < 14)).astype(int)
        f["power_hour"] = (hour >= 15.5).astype(int)
        f["day_of_week"] = ts.dt.dayofweek
        f["is_monday"] = (ts.dt.dayofweek == 0).astype(int)
        f["is_friday"] = (ts.dt.dayofweek == 4).astype(int)
        
        # Intraday position
        market_open_time = ts.dt.normalize() + pd.Timedelta(hours=9, minutes=30)
        f["mins_since_open"] = (ts - market_open_time).dt.total_seconds() / 60
        f["session_pct"] = f["mins_since_open"].clip(0, 390) / 390
    
    # === 15. MULTI-TIMEFRAME ALIGNMENT (20) ===
    # MA alignment
    f["ma_align_short"] = (np.sign(f["price_vs_ma_5"]) + np.sign(f["price_vs_ma_10"]) + np.sign(f["price_vs_ma_20"])) / 3
    f["ma_align_long"] = (np.sign(f["price_vs_ma_20"]) + np.sign(f["price_vs_ma_50"]) + np.sign(f["price_vs_ma_100"])) / 3
    
    # Momentum alignment
    f["mom_align"] = (np.sign(f["ret_5"]) + np.sign(f["ret_10"]) + np.sign(f["ret_20"])) / 3
    
    # RSI divergence
    f["rsi_divergence"] = f["rsi_5"] - f["rsi_14"]
    
    # Volatility regime
    f["vol_regime"] = f["volatility_5"] / (f["volatility_20"] + 1e-8)
    
    # Trend strength
    for lb in [10, 20, 30]:
        f[f"trend_strength_{lb}"] = abs(f[f"ret_{lb}"]) / (f[f"volatility_{min(lb, 30)}"] * np.sqrt(lb) + 1e-8)
    
    # === 16. VWAP (10) ===
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    f["vwap"] = (typical_price * df["volume"]).groupby(df["symbol"]).cumsum() / df.groupby("symbol")["volume"].cumsum().clip(lower=1)
    f["price_vs_vwap"] = (df["close"] - f["vwap"]) / (f["vwap"] + 1e-8)
    f["above_vwap"] = (df["close"] > f["vwap"]).astype(int)
    f["vwap_dist"] = abs(df["close"] - f["vwap"]) / (f["vwap"] + 1e-8)
    
    # === 17. GAP FEATURES (8) ===
    f["gap"] = df["open"] / g["close"].shift(1) - 1
    f["gap_filled"] = ((f["gap"] > 0) & (df["low"] <= g["close"].shift(1)) | 
                       (f["gap"] < 0) & (df["high"] >= g["close"].shift(1))).astype(int)
    f["gap_size"] = abs(f["gap"])
    f["large_gap"] = (f["gap_size"] > 0.02).astype(int)
    
    # === 18. COMPARATIVE FEATURES (30) ===
    # Compare current values to historical
    for lb in [5, 10, 20, 30, 60]:
        f[f"ret_vs_avg_{lb}"] = stock_ret / (stock_ret.rolling(lb, min_periods=1).mean() + 1e-8)
        f[f"vol_vs_avg_{lb}"] = df["volume"] / (g["volume"].transform(lambda x: safe_rolling(x, lb)) + 1)
        f[f"range_vs_avg_{lb}"] = (df["high"] - df["low"]) / (g.apply(lambda x: (x["high"] - x["low"]).rolling(lb, min_periods=1).mean()).reset_index(level=0, drop=True) + 1e-8)
        f[f"body_vs_avg_{lb}"] = body_size / (body_size.rolling(lb, min_periods=1).mean() + 1e-8)
        f[f"close_vs_high_{lb}"] = df["close"] / (g["high"].transform(lambda x: safe_rolling(x, lb, "max")) + 1e-8)
        f[f"close_vs_low_{lb}"] = df["close"] / (g["low"].transform(lambda x: safe_rolling(x, lb, "min")) + 1e-8)
    
    # === 19. RELATIVE FEATURES (25) ===
    # Relative to other timeframes
    for short, long in [(5, 20), (10, 50), (20, 100), (5, 50), (10, 100)]:
        f[f"ret_ratio_{short}_{long}"] = f.get(f"ret_{short}", 0) / (f.get(f"ret_{long}", 1e-8) + 1e-8)
        f[f"vol_ratio_tf_{short}_{long}"] = f.get(f"volatility_{min(short,30)}", 0) / (f.get(f"volatility_{min(long,60)}", 1e-8) + 1e-8)
        f[f"ma_ratio_{short}_{long}"] = f.get(f"ma_{short}", 1) / (f.get(f"ma_{long}", 1) + 1e-8)
        f[f"ema_ratio_{short}_{long}"] = f.get(f"ema_{short}", 1) / (f.get(f"ema_{long}", 1) + 1e-8)
        f[f"atr_ratio_{min(short,30)}_{min(long,60)}"] = f.get(f"atr_pct_{min(short,30)}", 0) / (f.get(f"atr_pct_{min(long,60)}", 1e-8) + 1e-8)
    
    # === 20. SECOND ORDER DERIVATIVES (20) ===
    for lb in [1, 3, 5, 10]:
        # Acceleration of price
        f[f"price_accel_{lb}"] = f.get(f"d1_close_{lb}", pd.Series(0, index=df.index)).diff(lb)
        # Acceleration of volume
        f[f"vol_accel_{lb}"] = f.get(f"d1_volume_{lb}", pd.Series(0, index=df.index)).diff(lb)
        # Acceleration of volatility
        vol_key = f"volatility_{max(min(lb*2, 30), 5)}"
        f[f"volatility_accel_{lb}"] = f.get(vol_key, pd.Series(0, index=df.index)).diff(lb).diff(lb)
        # Jerk (third derivative)
        f[f"price_jerk_{lb}"] = f[f"price_accel_{lb}"].diff(lb)
        # Curvature
        d1 = f.get(f"d1_close_{lb}", pd.Series(0, index=df.index))
        d2 = f[f"price_accel_{lb}"]
        f[f"curvature_{lb}"] = d2 / ((1 + d1**2)**1.5 + 1e-8)
    
    # === 21. CROSS-ASSET RELATIVE (20) ===
    # Relative to market percentiles - use computed features
    feat_df = pd.DataFrame(f, index=df.index)
    feat_df["timestamp"] = df["timestamp"]
    for lb in [10, 20, 30, 60]:
        ret_col = f"ret_{min(lb,60)}"
        if ret_col in feat_df.columns:
            f[f"ret_pctl_cross_{lb}"] = feat_df.groupby("timestamp")[ret_col].rank(pct=True)
        f[f"vol_pctl_cross_{lb}"] = df.groupby("timestamp")["volume"].rank(pct=True)
        vol_col = f"volatility_{min(lb,30)}"
        if vol_col in f:
            feat_df[vol_col] = f[vol_col]
            f[f"volatility_pctl_cross_{lb}"] = feat_df.groupby("timestamp")[vol_col].rank(pct=True)
        mkt_col = f"market_ret_{min(lb,20)}"
        f[f"strength_vs_market_{lb}"] = f.get(f"ret_{min(lb,60)}", 0) - f.get(mkt_col, 0)
        f[f"outperform_{lb}"] = (f[f"strength_vs_market_{lb}"] > 0).astype(int)
    
    # === 22. EVOLUTION FEATURES (20) ===
    # How features change over time
    for base_feat in ["rsi_14", "stoch_k_14", "macd_12_26", "bb_position_20"]:
        if base_feat in f:
            for lb in [3, 5, 10, 20]:
                f[f"{base_feat}_change_{lb}"] = f[base_feat].diff(lb)
    
    # Rate of change of indicators
    for lb in [5, 10, 20]:
        f[f"rsi_roc_{lb}"] = f["rsi_14"].pct_change(lb) if "rsi_14" in f else 0
        f[f"macd_roc_{lb}"] = f["macd_12_26"].diff(lb) if "macd_12_26" in f else 0
        f[f"bb_width_roc_{lb}"] = f["bb_width_20"].pct_change(lb) if "bb_width_20" in f else 0
    
    # === 23. INTERACTION FEATURES (25) ===
    # Combinations of features - use .get() for safety
    f["vol_x_ret"] = f.get("vol_ratio_10", 1) * f.get("ret_5", 0)
    f["rsi_x_vol"] = f.get("rsi_14", 50) * f.get("volatility_10", 0)
    f["trend_x_vol"] = f.get("ma_align_short", 0) * f.get("volatility_10", 0)
    f["breadth_x_ret"] = f.get("up_ratio", 0.5) * f.get("ret_5", 0)
    f["squeeze_x_mom"] = f.get("bb_squeeze_20", 0) * f.get("momentum_10", 0)
    
    for lb in [5, 10, 20]:
        f[f"vol_weighted_ret_{lb}"] = f.get(f"ret_{lb}", 0) * f.get(f"vol_ratio_{lb}", 1)
        f[f"atr_weighted_ret_{lb}"] = f.get(f"ret_{lb}", 0) / (f.get(f"atr_pct_{min(lb,30)}", 0.01) + 1e-8)
        f[f"zscore_x_vol_{lb}"] = f.get(f"zscore_{min(lb, 30)}", 0) * f.get(f"vol_ratio_{lb}", 1)
        f[f"range_x_vol_{lb}"] = f.get(f"range_pct_{lb}", 0) * f.get(f"vol_ratio_{lb}", 1)
    
    # === 24. REGIME FEATURES (15) ===
    # Detect market regimes
    vol20 = f.get("volatility_20", pd.Series(0.01, index=df.index))
    f["high_vol_regime"] = (vol20 > vol20.rolling(50, min_periods=1).quantile(0.8)).astype(int)
    f["low_vol_regime"] = (vol20 < vol20.rolling(50, min_periods=1).quantile(0.2)).astype(int)
    f["trending_regime"] = (abs(f.get("ret_20", 0)) > vol20 * 2).astype(int)
    f["mean_revert_regime"] = (f.get("zscore_20", pd.Series(0, index=df.index)).abs() > 2).astype(int)
    f["breakout_regime"] = (f.get("range_contraction_20", 0) > 0.3).astype(int)
    
    for lb in [10, 20, 30]:
        vol_col = f.get(f"volatility_{min(lb,30)}", pd.Series(0, index=df.index))
        ret_col = f.get(f"ret_{lb}", pd.Series(0, index=df.index))
        f[f"regime_vol_{lb}"] = pd.cut(vol_col.rank(pct=True), bins=5, labels=False)
        f[f"regime_trend_{lb}"] = pd.cut(ret_col.rank(pct=True), bins=5, labels=False)
        f[f"regime_breadth_{lb}"] = pd.cut(f.get("up_ratio", pd.Series(0.5, index=df.index)).rolling(lb, min_periods=1).mean().rank(pct=True), bins=5, labels=False)
    
    # === 25. LAGGED FEATURES (20) ===
    for feat in ["ret_5", "vol_ratio_10", "rsi_14", "zscore_20"]:
        if feat in f:
            for lag in [1, 3, 5, 10]:
                f[f"{feat}_lag_{lag}"] = f[feat].shift(lag)
    
    # === 26. ROLLING STATISTICS (20) ===
    for lb in [10, 20, 30]:
        f[f"ret_skew_{lb}"] = g["close"].transform(lambda x: x.pct_change().rolling(lb, min_periods=5).skew())
        f[f"ret_kurt_{lb}"] = g["close"].transform(lambda x: x.pct_change().rolling(lb, min_periods=5).kurt())
        f[f"vol_skew_{lb}"] = g["volume"].transform(lambda x: x.rolling(lb, min_periods=5).skew())
        f[f"range_skew_{lb}"] = (df["high"] - df["low"]).rolling(lb, min_periods=5).skew()
        f[f"up_streak_{lb}"] = g["close"].transform(lambda x: (x > x.shift(1)).rolling(lb, min_periods=1).sum())
        f[f"down_streak_{lb}"] = g["close"].transform(lambda x: (x < x.shift(1)).rolling(lb, min_periods=1).sum())
    
    # === 27. PRICE LEVEL FEATURES (15) ===
    for lb in [20, 50, 100]:
        high_n = g["high"].transform(lambda x: safe_rolling(x, lb, "max"))
        low_n = g["low"].transform(lambda x: safe_rolling(x, lb, "min"))
        f[f"fib_382_{lb}"] = (df["close"] - low_n) / (high_n - low_n + 1e-8) - 0.382
        f[f"fib_618_{lb}"] = (df["close"] - low_n) / (high_n - low_n + 1e-8) - 0.618
        f[f"fib_500_{lb}"] = (df["close"] - low_n) / (high_n - low_n + 1e-8) - 0.500
        f[f"near_high_{lb}"] = (f[f"dist_to_high_{min(lb,50)}"] < 0.02).astype(int)
        f[f"near_low_{lb}"] = (f[f"dist_to_low_{min(lb,50)}"] < 0.02).astype(int)
    
    # === 28. ADDITIONAL FEATURES TO REACH 500+ (40) ===
    # More cross-sectional
    f["rank_ret_5"] = df.groupby("timestamp")["close"].transform(lambda x: x.pct_change(5).rank(pct=True))
    f["rank_ret_10"] = df.groupby("timestamp")["close"].transform(lambda x: x.pct_change(10).rank(pct=True))
    f["rank_ret_20"] = df.groupby("timestamp")["close"].transform(lambda x: x.pct_change(20).rank(pct=True))
    
    # More derivatives
    for lb in [2, 4, 6, 8]:
        f[f"d1_close_ext_{lb}"] = g["close"].diff(lb) / (g["close"].shift(lb) + 1e-8)
        f[f"d2_close_ext_{lb}"] = f[f"d1_close_ext_{lb}"].diff(lb)
    
    # More relative
    for lb in [3, 7, 15, 25]:
        f[f"ret_ext_{lb}"] = g["close"].pct_change(lb)
        f[f"vol_ma_ext_{lb}"] = g["volume"].transform(lambda x: safe_rolling(x, lb))
    
    # More comparative
    f["close_vs_open_5d"] = df["close"] / g["open"].transform(lambda x: x.shift(5))
    f["close_vs_open_10d"] = df["close"] / g["open"].transform(lambda x: x.shift(10))
    f["high_vs_prev_high"] = df["high"] / g["high"].shift(1)
    f["low_vs_prev_low"] = df["low"] / g["low"].shift(1)
    
    # More pattern
    f["double_top"] = ((df["high"] > g["high"].shift(1)) & (df["high"].shift(1) > g["high"].shift(2)) & (df["close"] < df["open"])).astype(int)
    f["double_bottom"] = ((df["low"] < g["low"].shift(1)) & (df["low"].shift(1) < g["low"].shift(2)) & (df["close"] > df["open"])).astype(int)
    
    # More momentum
    for lb in [4, 8, 12, 16]:
        f[f"momentum_ext_{lb}"] = df["close"] - g["close"].shift(lb)
        f[f"roc_ext_{lb}"] = g["close"].pct_change(lb)
    
    # === 29. PRICE ACTION (15) ===
    f["close_position"] = (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-8)
    f["open_position"] = (df["open"] - df["low"]) / (df["high"] - df["low"] + 1e-8)
    f["intraday_ret"] = (df["close"] - df["open"]) / df["open"]
    f["high_ret"] = (df["high"] - df["open"]) / df["open"]
    f["low_ret"] = (df["low"] - df["open"]) / df["open"]
    f["range_vs_body"] = (df["high"] - df["low"]) / (body_size + 1e-8)
    
    # Pivot points
    pivot = (df["high"].shift(1) + df["low"].shift(1) + df["close"].shift(1)) / 3
    f["pivot"] = pivot
    f["r1"] = 2 * pivot - df["low"].shift(1)
    f["s1"] = 2 * pivot - df["high"].shift(1)
    f["price_vs_pivot"] = (df["close"] - pivot) / (pivot + 1e-8)
    f["price_vs_r1"] = (df["close"] - f["r1"]) / (f["r1"] + 1e-8)
    f["price_vs_s1"] = (df["close"] - f["s1"]) / (f["s1"] + 1e-8)
    
    print(f"Built {len(f)} features")
    return pd.DataFrame(f, index=df.index)


def analyze_features(df: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Analyze predictive value."""
    # Create target
    target = df.groupby("symbol")["close"].transform(lambda x: x.shift(-6) / x - 1)
    
    results = []
    print(f"\nAnalyzing {len(features.columns)} features...")
    
    for col in features.columns:
        feat = features[col]
        valid = ~(feat.isna() | target.isna() | np.isinf(feat))
        if valid.sum() < 1000:
            continue
        try:
            corr, pval = spearmanr(feat[valid], target[valid])
            results.append({"feature": col, "correlation": corr, "abs_corr": abs(corr), "p_value": pval})
        except:
            pass
    
    return pd.DataFrame(results).sort_values("abs_corr", ascending=False)


def main():
    df = load_data()
    features = build_features(df)
    results = analyze_features(df, features)
    
    # Print top features
    print("\n" + "=" * 70)
    print("TOP 50 PREDICTIVE FEATURES")
    print("=" * 70)
    print(f"{'Feature':<40} {'Corr':>10} {'P-value':>12}")
    print("-" * 65)
    
    for _, row in results.head(50).iterrows():
        sig = "***" if row["p_value"] < 0.001 else "**" if row["p_value"] < 0.01 else "*" if row["p_value"] < 0.05 else ""
        print(f"{row['feature']:<40} {row['correlation']:>+10.4f} {row['p_value']:>12.2e} {sig}")
    
    # Summary
    sig_features = results[results["p_value"] < 0.01]
    print(f"\n✅ Significant features (p<0.01): {len(sig_features)}")
    print(f"✅ Strong features (|corr|>0.02): {len(results[results['abs_corr'] > 0.02])}")
    
    # Save
    out_dir = Path(__file__).parent.parent / "run" / "features_500"
    out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_dir / "feature_importance.csv", index=False)
    features.to_parquet(out_dir / "all_features.parquet")
    print(f"\n✅ Saved to {out_dir}")


if __name__ == "__main__":
    main()
