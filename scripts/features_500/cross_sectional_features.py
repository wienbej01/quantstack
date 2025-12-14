"""Cross-sectional and market features - 80 features."""
import numpy as np
import pandas as pd

def compute_cross_sectional_features(df: pd.DataFrame) -> pd.DataFrame:
    """Multi-ticker, market-relative, and comparative features."""
    f = {}
    
    # Cross-sectional ranks (12)
    for col in ["returns", "volume", "volatility_10"]:
        if col in df.columns or col == "returns":
            base = df.groupby("symbol")["close"].pct_change() if col == "returns" else df.get(col, df["volume"])
            for lb in [1, 5, 10, 20]:
                rolled = base.rolling(lb, min_periods=1).mean() if lb > 1 else base
                f[f"rank_{col}_{lb}"] = df.groupby("timestamp")[col if col in df.columns else "close"].rank(pct=True)
    
    # Market return proxy (6)
    market_ret = df.groupby("timestamp")["close"].transform(
        lambda x: x.pct_change().mean() if len(x) > 1 else 0
    )
    f["market_ret"] = market_ret
    for lb in [5, 10, 20, 30, 60]:
        f[f"market_ret_{lb}"] = market_ret.rolling(lb, min_periods=1).sum()
    
    # Relative strength vs market (6)
    stock_ret = df.groupby("symbol")["close"].pct_change()
    for lb in [5, 10, 20, 30, 60]:
        stock_cum = stock_ret.rolling(lb, min_periods=1).sum()
        f[f"rel_strength_{lb}"] = stock_cum - f.get(f"market_ret_{lb}", 0)
    f["rel_strength_1"] = stock_ret - market_ret
    
    # Cross-sectional dispersion (6)
    for lb in [1, 5, 10, 20, 30, 60]:
        f[f"cross_dispersion_{lb}"] = df.groupby("timestamp")["close"].transform(
            lambda x: x.pct_change().std() if len(x) > 1 else 0
        )
    
    # Market breadth (6)
    f["market_breadth"] = df.groupby("timestamp")["symbol"].transform("nunique")
    f["up_ratio"] = df.groupby("timestamp")["close"].transform(
        lambda x: (x.pct_change() > 0).mean() if len(x) > 1 else 0.5
    )
    f["down_ratio"] = 1 - f["up_ratio"]
    f["advance_decline"] = f["up_ratio"] - f["down_ratio"]
    for lb in [5, 10]:
        f[f"breadth_ma_{lb}"] = f["up_ratio"].rolling(lb, min_periods=1).mean()
    
    # Sector momentum (if sector available, else use all) (8)
    for lb in [5, 10, 20, 30]:
        sector_ret = df.groupby("timestamp")["close"].transform(
            lambda x: x.pct_change().mean() if len(x) > 1 else 0
        )
        f[f"sector_momentum_{lb}"] = sector_ret.rolling(lb, min_periods=1).sum()
        f[f"vs_sector_{lb}"] = stock_ret.rolling(lb, min_periods=1).sum() - f[f"sector_momentum_{lb}"]
    
    # Beta estimation (6)
    for lb in [20, 30, 60]:
        # Rolling covariance / variance
        f[f"beta_{lb}"] = df.groupby("symbol").apply(
            lambda g: g["close"].pct_change().rolling(lb, min_periods=5).cov(market_ret.loc[g.index]) / 
                      (market_ret.loc[g.index].rolling(lb, min_periods=5).var() + 1e-8)
        ).reset_index(level=0, drop=True)
        f[f"alpha_{lb}"] = stock_ret - f.get(f"beta_{lb}", 1) * market_ret
    
    # Correlation with market (6)
    for lb in [10, 20, 30]:
        f[f"market_corr_{lb}"] = df.groupby("symbol").apply(
            lambda g: g["close"].pct_change().rolling(lb, min_periods=5).corr(market_ret.loc[g.index])
        ).reset_index(level=0, drop=True)
        f[f"market_corr_change_{lb}"] = f[f"market_corr_{lb}"].diff(5)
    
    # Volume relative to market (6)
    market_vol = df.groupby("timestamp")["volume"].transform("mean")
    f["vol_vs_market"] = df["volume"] / (market_vol + 1)
    for lb in [5, 10, 20, 30, 60]:
        f[f"vol_vs_market_{lb}"] = f["vol_vs_market"].rolling(lb, min_periods=1).mean()
    
    # Percentile ranks (12)
    for col, name in [("close", "price"), ("volume", "volume")]:
        for lb in [10, 20, 30, 50, 100, 200]:
            f[f"{name}_pctl_{lb}"] = df.groupby("symbol")[col].transform(
                lambda x: x.rolling(lb, min_periods=1).apply(lambda y: (y[-1] > y[:-1]).mean() if len(y) > 1 else 0.5, raw=True)
            )
    
    # Z-scores (6)
    for lb in [10, 20, 30]:
        mean = df.groupby("symbol")["close"].transform(lambda x: x.rolling(lb, min_periods=1).mean())
        std = df.groupby("symbol")["close"].transform(lambda x: x.rolling(lb, min_periods=1).std())
        f[f"zscore_{lb}"] = (df["close"] - mean) / (std + 1e-8)
        f[f"zscore_ret_{lb}"] = df.groupby("symbol")["close"].transform(
            lambda x: (x.pct_change() - x.pct_change().rolling(lb, min_periods=1).mean()) / 
                      (x.pct_change().rolling(lb, min_periods=1).std() + 1e-8)
        )
    
    return pd.DataFrame(f, index=df.index)
