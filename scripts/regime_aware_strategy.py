#!/usr/bin/env python3
"""Regime-aware strategy with separate models per regime."""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

warnings.filterwarnings("ignore")

# Cross-sectional features (best performers)
CROSS_SECTIONAL_FEATURES = [
    "cross_rank_ret", "cross_rank_vol", "sector_momentum", "cross_dispersion",
    "market_breadth", "up_down_ratio", "rel_strength_5", "rel_strength_10",
    "rel_strength_20", "market_ret_5", "market_ret_10",
]


def detect_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Detect market regime (trend + volatility)."""
    market_ret = df.groupby("timestamp")["returns"].transform("mean")
    market_vol = df.groupby("timestamp")["returns"].transform("std")
    
    df["mkt_ret_20"] = market_ret.rolling(20, min_periods=1).sum()
    df["mkt_vol_20"] = market_vol.rolling(20, min_periods=1).mean()
    
    ret_high = df["mkt_ret_20"].quantile(0.67)
    ret_low = df["mkt_ret_20"].quantile(0.33)
    vol_high = df["mkt_vol_20"].quantile(0.67)
    
    df["trend"] = "sideways"
    df.loc[df["mkt_ret_20"] > ret_high, "trend"] = "bull"
    df.loc[df["mkt_ret_20"] < ret_low, "trend"] = "bear"
    df["high_vol"] = (df["mkt_vol_20"] > vol_high).astype(int)
    
    return df


def train_regime_models(df: pd.DataFrame, features: list, target: pd.Series) -> dict:
    """Train separate models for each regime."""
    models = {}
    for regime in ["bull", "bear", "sideways"]:
        mask = df["trend"] == regime
        if mask.sum() < 500:
            continue
        
        X = df.loc[mask, features].fillna(0).replace([np.inf, -np.inf], 0)
        y = target[mask]
        valid = ~y.isna()
        
        if valid.sum() < 300:
            continue
        
        model = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
        model.fit(X[valid], y[valid])
        models[regime] = model
    
    return models


def predict_with_regime(df: pd.DataFrame, models: dict, features: list) -> np.ndarray:
    """Predict using regime-specific models."""
    proba = np.full(len(df), 0.5)
    X = df[features].fillna(0).replace([np.inf, -np.inf], 0)
    
    for regime, model in models.items():
        mask = df["trend"] == regime
        if mask.sum() > 0:
            proba[mask] = model.predict_proba(X[mask])[:, 1]
    
    return proba


def run_regime_aware_backtest(data_path: str = None, train_days: int = 60, test_days: int = 20):
    """Run regime-aware backtest."""
    # Load data
    if data_path is None:
        data_path = Path(__file__).parent.parent / "run" / "cross_sectional_features" / "features.parquet"
    
    df = pd.read_parquet(data_path)
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    df = df[df["date"] < pd.Timestamp("2025-01-01").date()]
    
    # Detect regimes
    df = detect_regime(df)
    
    # Prepare features
    features = [f for f in CROSS_SECTIONAL_FEATURES if f in df.columns]
    y = (df["return_30min"] > 0).astype(int)
    
    dates = sorted(df["date"].unique())
    
    print("=" * 70)
    print("REGIME-AWARE BACKTEST")
    print("=" * 70)
    print(f"Features: {len(features)}")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    print("-" * 70)
    
    equity = 10000
    all_trades = []
    
    for i in range(train_days, len(dates) - test_days, test_days):
        train_start = dates[i - train_days]
        train_end = dates[i]
        test_start = dates[i]
        test_end = dates[min(i + test_days, len(dates) - 1)]
        
        train_mask = (df["date"] >= train_start) & (df["date"] < train_end)
        test_mask = (df["date"] >= test_start) & (df["date"] < test_end)
        
        if train_mask.sum() < 500 or test_mask.sum() < 100:
            continue
        
        # Train regime-specific models
        models = train_regime_models(df[train_mask], features, y[train_mask])
        
        if not models:
            continue
        
        # Predict on test set
        test_df = df[test_mask].copy()
        test_df["proba"] = predict_with_regime(test_df, models, features)
        
        # Adjust threshold based on volatility regime
        threshold = 0.55 if test_df["high_vol"].mean() > 0.5 else 0.58
        trades = test_df[test_df["proba"] > threshold]
        
        if len(trades) == 0:
            continue
        
        # Execute trades with position sizing
        for _, trade in trades.iterrows():
            ret = trade["return_30min"]
            if pd.isna(ret):
                continue
            
            # Reduce position in high vol
            vol_adj = 0.7 if trade["high_vol"] else 1.0
            position_size = equity * 0.01 / 0.02 * vol_adj
            position_size = min(position_size, equity * 0.20)
            
            pnl = position_size * ret
            equity += pnl
            equity = max(equity, 1000)
            
            all_trades.append({
                "date": trade["timestamp"],
                "symbol": trade["symbol"],
                "ret": ret,
                "pnl": pnl,
                "equity": equity,
                "regime": trade["trend"],
                "high_vol": trade["high_vol"],
            })
        
        win_rate = (trades["return_30min"] > 0).mean()
        print(f"{test_start} → {test_end}: {len(trades):4d} trades, {win_rate:.1%} win, ${equity:,.0f}")
    
    # Summary
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    if all_trades:
        trades_df = pd.DataFrame(all_trades)
        total_ret = (equity / 10000 - 1) * 100
        win_rate = (trades_df["ret"] > 0).mean()
        
        peak = trades_df["equity"].cummax()
        max_dd = ((trades_df["equity"] - peak) / peak).min()
        
        print(f"Final equity: ${equity:,.0f} ({total_ret:+.1f}%)")
        print(f"Win rate: {win_rate:.1%}")
        print(f"Max drawdown: {max_dd:.1%}")
        print(f"Total trades: {len(trades_df)}")
        
        # By regime
        print("\nBy regime:")
        for regime in ["bull", "bear", "sideways"]:
            r_trades = trades_df[trades_df["regime"] == regime]
            if len(r_trades) > 50:
                print(f"  {regime}: {(r_trades['ret'] > 0).mean():.1%} win ({len(r_trades)} trades)")
        
        # Save
        out_path = Path(__file__).parent.parent / "run" / "regime_aware_backtest.csv"
        trades_df.to_csv(out_path, index=False)
        print(f"\nSaved to {out_path}")
        
        return trades_df
    
    return None


if __name__ == "__main__":
    run_regime_aware_backtest()
