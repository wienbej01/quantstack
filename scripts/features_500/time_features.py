"""Time-based and evolution features - 70 features."""
import numpy as np
import pandas as pd

def compute_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Session, time-of-day, evolution features."""
    f = {}
    
    # Time of day features (12)
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        hour = ts.dt.hour + ts.dt.minute / 60
        f["hour"] = hour
        f["minute_of_day"] = ts.dt.hour * 60 + ts.dt.minute
        f["sin_hour"] = np.sin(2 * np.pi * hour / 24)
        f["cos_hour"] = np.cos(2 * np.pi * hour / 24)
        f["sin_minute"] = np.sin(2 * np.pi * f["minute_of_day"] / (24 * 60))
        f["cos_minute"] = np.cos(2 * np.pi * f["minute_of_day"] / (24 * 60))
        
        # Session indicators
        f["pre_market"] = (hour < 9.5).astype(int)
        f["market_open"] = ((hour >= 9.5) & (hour < 10.5)).astype(int)
        f["mid_morning"] = ((hour >= 10.5) & (hour < 12)).astype(int)
        f["lunch"] = ((hour >= 12) & (hour < 14)).astype(int)
        f["afternoon"] = ((hour >= 14) & (hour < 15.5)).astype(int)
        f["power_hour"] = (hour >= 15.5).astype(int)
    
    # Day of week (5)
    if "timestamp" in df.columns:
        dow = ts.dt.dayofweek
        f["day_of_week"] = dow
        f["is_monday"] = (dow == 0).astype(int)
        f["is_friday"] = (dow == 4).astype(int)
        f["sin_dow"] = np.sin(2 * np.pi * dow / 5)
        f["cos_dow"] = np.cos(2 * np.pi * dow / 5)
    
    # Time since open (6)
    if "timestamp" in df.columns:
        market_open = ts.dt.normalize() + pd.Timedelta(hours=9, minutes=30)
        f["mins_since_open"] = (ts - market_open).dt.total_seconds() / 60
        f["mins_since_open_sq"] = f["mins_since_open"] ** 2
        f["mins_to_close"] = 390 - f["mins_since_open"]  # 6.5 hours = 390 mins
        f["session_pct"] = f["mins_since_open"] / 390
        f["early_session"] = (f["mins_since_open"] < 60).astype(int)
        f["late_session"] = (f["mins_to_close"] < 60).astype(int)
    
    # Evolution features - how metrics change through day (18)
    for col in ["close", "volume", "high"]:
        if col in df.columns:
            # Cumulative intraday
            f[f"{col}_intraday_cum"] = df.groupby(["symbol", df["timestamp"].dt.date])[col].cumsum() if "timestamp" in df.columns else df.groupby("symbol")[col].cumsum()
            # Intraday percentile
            f[f"{col}_intraday_pctl"] = df.groupby(["symbol", df["timestamp"].dt.date])[col].rank(pct=True) if "timestamp" in df.columns else df.groupby("symbol")[col].rank(pct=True)
            # Change from day open
            day_open = df.groupby(["symbol", df["timestamp"].dt.date])[col].transform("first") if "timestamp" in df.columns else df.groupby("symbol")[col].transform("first")
            f[f"{col}_from_open"] = (df[col] - day_open) / (day_open + 1e-8)
            # Change from day high/low
            day_high = df.groupby(["symbol", df["timestamp"].dt.date])["high"].transform("max") if "timestamp" in df.columns else df.groupby("symbol")["high"].transform("max")
            day_low = df.groupby(["symbol", df["timestamp"].dt.date])["low"].transform("min") if "timestamp" in df.columns else df.groupby("symbol")["low"].transform("min")
            f[f"{col}_from_day_high"] = (df[col] - day_high) / (day_high + 1e-8)
            f[f"{col}_from_day_low"] = (df[col] - day_low) / (day_low + 1e-8)
            f[f"{col}_day_range_pos"] = (df[col] - day_low) / (day_high - day_low + 1e-8)
    
    # Intraday VWAP (6)
    if "volume" in df.columns:
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cum_vol = df.groupby(["symbol", df["timestamp"].dt.date])["volume"].cumsum() if "timestamp" in df.columns else df.groupby("symbol")["volume"].cumsum()
        cum_tp_vol = df.groupby(["symbol", df["timestamp"].dt.date]).apply(
            lambda g: (typical_price.loc[g.index] * g["volume"]).cumsum()
        ).reset_index(level=[0, 1], drop=True) if "timestamp" in df.columns else (typical_price * df["volume"]).groupby(df["symbol"]).cumsum()
        f["vwap"] = cum_tp_vol / (cum_vol + 1)
        f["price_vs_vwap"] = (df["close"] - f["vwap"]) / (f["vwap"] + 1e-8)
        f["vwap_slope"] = f["vwap"].diff(5) / (f["vwap"] + 1e-8)
        f["vwap_dist_pct"] = abs(df["close"] - f["vwap"]) / (f["vwap"] + 1e-8)
        f["above_vwap"] = (df["close"] > f["vwap"]).astype(int)
        f["vwap_cross"] = (f["above_vwap"].diff().abs()).fillna(0)
    
    # Rolling time-of-day patterns (12)
    if "timestamp" in df.columns:
        for lb in [5, 10, 20]:
            # Same time yesterday comparison
            f[f"vs_same_time_{lb}d"] = df.groupby("symbol")["close"].transform(
                lambda x: x / x.shift(lb * 78) - 1  # ~78 bars per day
            )
            # Hour-specific momentum
            f[f"hour_momentum_{lb}"] = df.groupby(["symbol", ts.dt.hour])["close"].transform(
                lambda x: x.pct_change(lb)
            )
            # Session-specific volatility
            f[f"session_vol_{lb}"] = df.groupby(["symbol", ts.dt.hour])["close"].transform(
                lambda x: x.pct_change().rolling(lb, min_periods=1).std()
            )
            # Time-weighted returns
            time_weight = 1 - (f.get("mins_since_open", 0) / 390)
            f[f"time_weighted_ret_{lb}"] = df.groupby("symbol")["close"].pct_change(lb) * time_weight
    
    # Month/week effects (5)
    if "timestamp" in df.columns:
        f["day_of_month"] = ts.dt.day
        f["week_of_month"] = (ts.dt.day - 1) // 7 + 1
        f["is_month_start"] = (ts.dt.day <= 3).astype(int)
        f["is_month_end"] = (ts.dt.day >= 28).astype(int)
        f["is_quarter_end"] = ((ts.dt.month % 3 == 0) & (ts.dt.day >= 28)).astype(int)
    
    return pd.DataFrame(f, index=df.index)
