#!/usr/bin/env python3
"""
Cross-Sectional Feature Engineering

Adds features based on academic research findings:
1. Market momentum (SPY/QQQ returns)
2. Sector momentum (peer stock returns)
3. Cross-sectional rank features
4. Relative strength vs market/sector
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data" / "src"))
from qx_data.gold_loader import load_bars


def load_market_data(root: str, dates: list[str]) -> pd.DataFrame:
    """Load SPY as market proxy."""
    try:
        df = load_bars(root, "bars_1m", ["SPY"], dates, validate=False)
        df["ts"] = pd.to_datetime(df["ts"], unit="ns")
        df = df.sort_values("ts")
        df["market_return"] = df["close"].pct_change()
        return df[["ts", "market_return", "close", "volume"]].rename(
            columns={"close": "market_close", "volume": "market_volume"}
        )
    except Exception as e:
        print(f"Warning: Could not load SPY: {e}")
        return None


def compute_cross_sectional_features(
    df: pd.DataFrame, market_df: pd.DataFrame = None
) -> pd.DataFrame:
    """
    Add cross-sectional features to existing feature dataframe.

    Features added:
    - market_ret_1/5/10/20: Market (SPY) returns at various lookbacks
    - rel_strength_5/10/20: Stock return relative to market
    - cross_rank_ret: Cross-sectional rank of return
    - cross_rank_vol: Cross-sectional rank of volume
    - sector_momentum: Average return of stocks at same timestamp
    - dispersion: Cross-sectional std of returns
    """
    print("Computing cross-sectional features...")

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Sort for rolling calculations
    df = df.sort_values(["symbol", "timestamp"])

    features_added = []

    # 1. Market momentum features (if market data available)
    if market_df is not None and len(market_df) > 0:
        print("  Adding market momentum features...")
        market_df = market_df.copy()
        market_df["ts"] = pd.to_datetime(market_df["ts"])

        # Compute market returns at various lookbacks
        for lb in [1, 5, 10, 20]:
            market_df[f"market_ret_{lb}"] = (
                market_df["market_return"].rolling(lb, min_periods=1).sum()
            )

        # Merge with main df
        df = df.merge(
            market_df[["ts"] + [f"market_ret_{lb}" for lb in [1, 5, 10, 20]]],
            left_on="timestamp",
            right_on="ts",
            how="left",
        ).drop(columns=["ts"], errors="ignore")

        features_added.extend([f"market_ret_{lb}" for lb in [1, 5, 10, 20]])
    else:
        # Create placeholder market features from cross-sectional average
        print("  Computing market proxy from cross-sectional average...")
        cross_avg = df.groupby("timestamp")["returns"].mean().reset_index()
        cross_avg.columns = ["timestamp", "market_ret_proxy"]
        df = df.merge(cross_avg, on="timestamp", how="left")

        for lb in [1, 5, 10, 20]:
            df[f"market_ret_{lb}"] = df.groupby("symbol")["market_ret_proxy"].transform(
                lambda x: x.rolling(lb, min_periods=1).sum()
            )
        df = df.drop(columns=["market_ret_proxy"])
        features_added.extend([f"market_ret_{lb}" for lb in [1, 5, 10, 20]])

    # 2. Relative strength vs market
    print("  Adding relative strength features...")
    for lb in [5, 10, 20]:
        stock_ret = df.groupby("symbol")["returns"].transform(
            lambda x: x.rolling(lb, min_periods=1).sum()
        )
        df[f"rel_strength_{lb}"] = stock_ret - df[f"market_ret_{lb}"]
        features_added.append(f"rel_strength_{lb}")

    # 3. Cross-sectional rank features
    print("  Adding cross-sectional rank features...")

    # Rank of return within each timestamp
    df["cross_rank_ret"] = df.groupby("timestamp")["returns"].rank(pct=True)
    features_added.append("cross_rank_ret")

    # Rank of volume within each timestamp
    if "volume_ratio" in df.columns:
        df["cross_rank_vol"] = df.groupby("timestamp")["volume_ratio"].rank(pct=True)
        features_added.append("cross_rank_vol")

    # 4. Sector/peer momentum (average return of other stocks at same time)
    print("  Adding sector momentum features...")

    # For each timestamp, compute mean return excluding current stock
    def sector_momentum(group):
        if len(group) <= 1:
            return pd.Series(0, index=group.index)
        total = group["returns"].sum()
        n = len(group)
        # Exclude self: (total - self) / (n - 1)
        return (total - group["returns"]) / (n - 1)

    df["sector_momentum"] = df.groupby("timestamp", group_keys=False).apply(
        sector_momentum
    )
    features_added.append("sector_momentum")

    # 5. Cross-sectional dispersion (volatility of returns across stocks)
    print("  Adding dispersion features...")
    dispersion = df.groupby("timestamp")["returns"].std().reset_index()
    dispersion.columns = ["timestamp", "cross_dispersion"]
    df = df.merge(dispersion, on="timestamp", how="left")
    features_added.append("cross_dispersion")

    # 6. Number of stocks trading (breadth)
    print("  Adding breadth features...")
    breadth = df.groupby("timestamp")["symbol"].nunique().reset_index()
    breadth.columns = ["timestamp", "market_breadth"]
    df = df.merge(breadth, on="timestamp", how="left")
    features_added.append("market_breadth")

    # 7. Up/down ratio (% of stocks with positive returns)
    up_ratio = (
        df.groupby("timestamp")["returns"].apply(lambda x: (x > 0).mean()).reset_index()
    )
    up_ratio.columns = ["timestamp", "up_down_ratio"]
    df = df.merge(up_ratio, on="timestamp", how="left")
    features_added.append("up_down_ratio")

    # Fill NaN
    for col in features_added:
        df[col] = df[col].fillna(0)

    print(f"  Added {len(features_added)} cross-sectional features")
    return df


def main():
    print("=" * 70)
    print("CROSS-SECTIONAL FEATURE ENGINEERING")
    print("=" * 70)

    # Load existing features
    input_path = Path("run/comprehensive_features/features_fixed.parquet")
    if not input_path.exists():
        input_path = Path("run/news_driven_features/features.parquet")

    print(f"Loading features from {input_path}...")
    df = pd.read_parquet(input_path)
    print(f"  Loaded {len(df):,} rows, {df['symbol'].nunique()} symbols")

    # Try to load market data
    gold_root = "/home/jacobw/gcs-mount/gold"
    market_df = None

    if Path(gold_root).exists():
        dates = df["timestamp"].dt.strftime("%Y-%m-%d").unique().tolist()
        print(f"Loading SPY market data for {len(dates)} dates...")
        try:
            market_df = load_market_data(gold_root, dates[:100])  # Limit for speed
            if market_df is not None:
                print(f"  Loaded {len(market_df):,} market bars")
        except Exception as e:
            print(f"  Could not load market data: {e}")

    # Compute cross-sectional features
    df = compute_cross_sectional_features(df, market_df)

    # Save
    output_dir = Path("run/cross_sectional_features")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "features.parquet"
    df.to_parquet(output_path)
    print(f"\nSaved to {output_path}")

    # Quick validation
    print("\n" + "=" * 70)
    print("FEATURE VALIDATION")
    print("=" * 70)

    new_features = [
        "market_ret_1",
        "market_ret_5",
        "market_ret_10",
        "market_ret_20",
        "rel_strength_5",
        "rel_strength_10",
        "rel_strength_20",
        "cross_rank_ret",
        "cross_rank_vol",
        "sector_momentum",
        "cross_dispersion",
        "market_breadth",
        "up_down_ratio",
    ]

    from scipy.stats import spearmanr

    print(f"{'Feature':<25} {'Corr':>10} {'P-value':>12}")
    print("-" * 50)

    for feat in new_features:
        if feat in df.columns:
            clean = df[[feat, "return_30min"]].dropna()
            if len(clean) > 100:
                corr, pval = spearmanr(clean[feat], clean["return_30min"])
                sig = (
                    "***"
                    if pval < 0.001
                    else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
                )
                print(f"{feat:<25} {corr:>+10.4f} {pval:>12.2e} {sig}")

    return df


if __name__ == "__main__":
    df = main()
