"""First and second order derivative features - 60 features."""
import numpy as np
import pandas as pd

def compute_derivative_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rate of change, acceleration, jerk features."""
    f = {}
    
    # First derivatives (velocity) - 15 features
    for col in ["close", "volume", "high", "low"]:
        if col in df.columns:
            for lb in [1, 3, 5]:
                f[f"d1_{col}_{lb}"] = df.groupby("symbol")[col].transform(
                    lambda x: x.diff(lb) / (x.shift(lb) + 1e-8)
                )
    
    # Second derivatives (acceleration) - 15 features
    for col in ["close", "volume", "high"]:
        if col in df.columns:
            d1 = df.groupby("symbol")[col].transform(lambda x: x.diff())
            for lb in [1, 3, 5, 10, 20]:
                f[f"d2_{col}_{lb}"] = d1.diff(lb) / (df[col] + 1e-8)
    
    # Third derivatives (jerk) - 6 features
    d1_close = df.groupby("symbol")["close"].transform(lambda x: x.diff())
    d2_close = d1_close.diff()
    for lb in [1, 3, 5, 10, 20, 30]:
        f[f"d3_close_{lb}"] = d2_close.diff(lb) / (df["close"] + 1e-8)
    
    # Momentum derivatives - 8 features
    for lb in [5, 10, 20, 30]:
        mom = df.groupby("symbol")["close"].transform(lambda x: x - x.shift(lb))
        f[f"mom_d1_{lb}"] = mom.diff()
        f[f"mom_d2_{lb}"] = mom.diff().diff()
    
    # Volume derivatives - 6 features
    for lb in [1, 3, 5]:
        f[f"vol_d1_{lb}"] = df.groupby("symbol")["volume"].transform(lambda x: x.diff(lb))
        f[f"vol_d2_{lb}"] = f[f"vol_d1_{lb}"].diff(lb)
    
    # Volatility derivatives - 6 features
    vol = df.groupby("symbol")["close"].transform(lambda x: x.pct_change().rolling(10, min_periods=1).std())
    for lb in [1, 3, 5]:
        f[f"vol_change_{lb}"] = vol.diff(lb)
        f[f"vol_accel_{lb}"] = vol.diff(lb).diff(lb)
    
    # Curvature (second derivative normalized) - 4 features
    for lb in [5, 10, 20, 30]:
        d1 = df.groupby("symbol")["close"].transform(lambda x: x.diff(lb))
        d2 = d1.diff(lb)
        f[f"curvature_{lb}"] = d2 / (1 + d1 ** 2) ** 1.5
    
    return pd.DataFrame(f, index=df.index)
