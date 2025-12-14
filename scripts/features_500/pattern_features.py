"""Pattern recognition features - 70 features for S/R, triangles, etc."""
import numpy as np
import pandas as pd

def compute_pattern_features(df: pd.DataFrame) -> pd.DataFrame:
    """Support/resistance, triangles, chart patterns."""
    f = {}
    
    # Support/Resistance levels (20)
    for lb in [10, 20, 30, 50, 100]:
        # Distance to recent high/low
        recent_high = df.groupby("symbol")["high"].transform(lambda x: x.rolling(lb, min_periods=1).max())
        recent_low = df.groupby("symbol")["low"].transform(lambda x: x.rolling(lb, min_periods=1).min())
        f[f"dist_to_high_{lb}"] = (recent_high - df["close"]) / df["close"]
        f[f"dist_to_low_{lb}"] = (df["close"] - recent_low) / df["close"]
        f[f"range_position_{lb}"] = (df["close"] - recent_low) / (recent_high - recent_low + 1e-8)
        f[f"breakout_high_{lb}"] = (df["close"] > recent_high.shift(1)).astype(int)
    
    # Pivot points (6)
    pivot = (df["high"].shift(1) + df["low"].shift(1) + df["close"].shift(1)) / 3
    f["pivot"] = pivot
    f["r1"] = 2 * pivot - df["low"].shift(1)
    f["s1"] = 2 * pivot - df["high"].shift(1)
    f["r2"] = pivot + (df["high"].shift(1) - df["low"].shift(1))
    f["s2"] = pivot - (df["high"].shift(1) - df["low"].shift(1))
    f["pivot_position"] = (df["close"] - f["s1"]) / (f["r1"] - f["s1"] + 1e-8)
    
    # Triangle detection - contracting range (8)
    for lb in [10, 20, 30, 50]:
        high_range = df.groupby("symbol")["high"].transform(lambda x: x.rolling(lb, min_periods=1).max() - x.rolling(lb, min_periods=1).min())
        prev_high_range = high_range.shift(lb)
        f[f"range_contraction_{lb}"] = (prev_high_range - high_range) / (prev_high_range + 1e-8)
        # Slope of highs vs lows (converging = triangle)
        high_slope = df.groupby("symbol")["high"].transform(lambda x: x.rolling(lb, min_periods=1).apply(lambda y: np.polyfit(range(len(y)), y, 1)[0] if len(y) > 1 else 0, raw=False))
        low_slope = df.groupby("symbol")["low"].transform(lambda x: x.rolling(lb, min_periods=1).apply(lambda y: np.polyfit(range(len(y)), y, 1)[0] if len(y) > 1 else 0, raw=False))
        f[f"triangle_score_{lb}"] = np.sign(high_slope) * np.sign(low_slope) * -1  # Converging = positive
    
    # Higher highs / lower lows (8)
    for lb in [3, 5, 10, 20]:
        f[f"higher_highs_{lb}"] = df.groupby("symbol")["high"].transform(
            lambda x: (x > x.shift(1)).rolling(lb, min_periods=1).sum() / lb
        )
        f[f"lower_lows_{lb}"] = df.groupby("symbol")["low"].transform(
            lambda x: (x < x.shift(1)).rolling(lb, min_periods=1).sum() / lb
        )
    
    # Trend line breaks (6)
    for lb in [10, 20, 30]:
        # Linear regression channel
        f[f"linreg_slope_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(lb, min_periods=2).apply(
                lambda y: np.polyfit(range(len(y)), y, 1)[0] / y.mean() if len(y) > 1 else 0, raw=False
            )
        )
        f[f"linreg_r2_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(lb, min_periods=2).apply(
                lambda y: np.corrcoef(range(len(y)), y)[0, 1] ** 2 if len(y) > 1 else 0, raw=False
            )
        )
    
    # Candlestick patterns (12)
    body = df["close"] - df["open"]
    body_size = abs(body)
    range_size = df["high"] - df["low"]
    
    f["doji"] = (body_size / (range_size + 1e-8) < 0.1).astype(int)
    f["hammer"] = ((df["close"] > df["open"]) & 
                   ((df["open"] - df["low"]) > 2 * body_size) &
                   ((df["high"] - df["close"]) < body_size * 0.5)).astype(int)
    f["shooting_star"] = ((df["close"] < df["open"]) & 
                          ((df["high"] - df["open"]) > 2 * body_size) &
                          ((df["close"] - df["low"]) < body_size * 0.5)).astype(int)
    f["engulfing_bull"] = ((body > 0) & (body.shift(1) < 0) & 
                           (df["close"] > df["open"].shift(1)) &
                           (df["open"] < df["close"].shift(1))).astype(int)
    f["engulfing_bear"] = ((body < 0) & (body.shift(1) > 0) & 
                           (df["close"] < df["open"].shift(1)) &
                           (df["open"] > df["close"].shift(1))).astype(int)
    f["morning_star"] = ((body.shift(2) < 0) & (body_size.shift(1) < body_size.shift(2) * 0.3) &
                         (body > 0) & (df["close"] > (df["open"].shift(2) + df["close"].shift(2)) / 2)).astype(int)
    f["evening_star"] = ((body.shift(2) > 0) & (body_size.shift(1) < body_size.shift(2) * 0.3) &
                         (body < 0) & (df["close"] < (df["open"].shift(2) + df["close"].shift(2)) / 2)).astype(int)
    f["three_white_soldiers"] = ((body > 0) & (body.shift(1) > 0) & (body.shift(2) > 0) &
                                  (df["close"] > df["close"].shift(1)) & 
                                  (df["close"].shift(1) > df["close"].shift(2))).astype(int)
    f["three_black_crows"] = ((body < 0) & (body.shift(1) < 0) & (body.shift(2) < 0) &
                               (df["close"] < df["close"].shift(1)) & 
                               (df["close"].shift(1) < df["close"].shift(2))).astype(int)
    f["inside_bar"] = ((df["high"] < df["high"].shift(1)) & 
                       (df["low"] > df["low"].shift(1))).astype(int)
    f["outside_bar"] = ((df["high"] > df["high"].shift(1)) & 
                        (df["low"] < df["low"].shift(1))).astype(int)
    f["pin_bar"] = (((df["high"] - df[["open", "close"]].max(axis=1)) > 2 * body_size) |
                    ((df[["open", "close"]].min(axis=1) - df["low"]) > 2 * body_size)).astype(int)
    
    # Consecutive patterns (10)
    for lb in [2, 3, 4, 5, 6]:
        f[f"consec_up_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: (x > x.shift(1)).rolling(lb, min_periods=1).sum()
        )
        f[f"consec_down_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: (x < x.shift(1)).rolling(lb, min_periods=1).sum()
        )
    
    return pd.DataFrame(f, index=df.index)
