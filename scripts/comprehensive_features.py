#!/usr/bin/env python3
"""
Comprehensive Feature Engineering
- Multi-timeframe features (1m, 5m, 15m, 30m refactored)
- Technical Analysis (RSI, MACD, Bollinger, Stochastic, etc.)
- ICT concepts (Order blocks, FVG, liquidity, displacement)
- VPA (Volume Price Analysis)
- Derivative features (acceleration, jerk, ratios)
- Relative features (vs market, vs sector)
"""

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl


def add_multi_timeframe_features(df):
    """Multi-timeframe momentum and volatility."""
    features = {}

    # Returns at multiple lookbacks
    for lb in [1, 2, 3, 5, 10, 15, 20, 30]:
        features[f"ret_{lb}bar"] = df["returns"].rolling(lb).sum()
        features[f"vol_{lb}bar"] = df["returns"].rolling(lb).std()

    # Normalized returns (z-score)
    for lb in [5, 10, 20]:
        mean = df["returns"].rolling(lb).mean()
        std = df["returns"].rolling(lb).std()
        features[f"ret_zscore_{lb}"] = (df["returns"] - mean) / (std + 1e-8)

    return pd.DataFrame(features)


def add_technical_indicators(df):
    """Classic technical analysis indicators."""
    features = {}
    ret = df["returns"]

    # RSI at multiple periods
    for period in [7, 14, 21]:
        delta = ret
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / (loss + 1e-8)
        features[f"rsi_{period}"] = 100 - (100 / (1 + rs))

    # MACD-style momentum
    for fast, slow in [(5, 10), (12, 26), (8, 21)]:
        ema_fast = ret.ewm(span=fast).mean()
        ema_slow = ret.ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=9).mean()
        features[f"macd_{fast}_{slow}"] = macd
        features[f"macd_signal_{fast}_{slow}"] = signal
        features[f"macd_hist_{fast}_{slow}"] = macd - signal

    # Bollinger Band position
    for period in [10, 20]:
        ma = ret.rolling(period).mean()
        std = ret.rolling(period).std()
        features[f"bb_upper_{period}"] = ma + 2 * std
        features[f"bb_lower_{period}"] = ma - 2 * std
        features[f"bb_position_{period}"] = (ret - ma) / (2 * std + 1e-8)
        features[f"bb_width_{period}"] = 4 * std

    # Stochastic-style
    for period in [5, 14]:
        roll_max = ret.rolling(period).max()
        roll_min = ret.rolling(period).min()
        features[f"stoch_{period}"] = (ret - roll_min) / (roll_max - roll_min + 1e-8)

    # Rate of Change
    for period in [5, 10, 20]:
        features[f"roc_{period}"] = ret / (ret.shift(period) + 1e-8) - 1

    # Williams %R style
    for period in [10, 20]:
        high = ret.rolling(period).max()
        low = ret.rolling(period).min()
        features[f"williams_r_{period}"] = (high - ret) / (high - low + 1e-8)

    return pd.DataFrame(features)


def add_ict_features(df):
    """ICT (Inner Circle Trader) concepts."""
    features = {}
    ret = df["returns"]
    vol = df.get("volume_ratio", pd.Series(1, index=df.index))

    # Displacement (strong directional move)
    for lb in [3, 5]:
        move = ret.rolling(lb).sum()
        avg_move = ret.rolling(20).sum().abs().rolling(20).mean()
        features[f"displacement_{lb}"] = move / (avg_move + 1e-8)

    # Break of Structure (BOS)
    for lb in [5, 10, 20]:
        high = ret.rolling(lb).max()
        low = ret.rolling(lb).min()
        features[f"bos_up_{lb}"] = (ret > high.shift(1)).astype(int)
        features[f"bos_down_{lb}"] = (ret < low.shift(1)).astype(int)

    # Fair Value Gap proxy (large candle followed by gap)
    features["fvg_up"] = (
        (ret > ret.rolling(20).std() * 2) & (ret.shift(-1) > 0)
    ).astype(int)
    features["fvg_down"] = (
        (ret < -ret.rolling(20).std() * 2) & (ret.shift(-1) < 0)
    ).astype(int)

    # Liquidity sweep (stop hunt)
    for lb in [10, 20]:
        prev_high = ret.rolling(lb).max().shift(1)
        prev_low = ret.rolling(lb).min().shift(1)
        features[f"liquidity_sweep_up_{lb}"] = (
            (ret > prev_high) & (ret.shift(-1) < ret)
        ).astype(int)
        features[f"liquidity_sweep_down_{lb}"] = (
            (ret < prev_low) & (ret.shift(-1) > ret)
        ).astype(int)

    # Order block proxy (strong move with volume)
    high_vol = vol > vol.rolling(20).mean() * 1.5
    features["order_block_bull"] = (
        (ret > ret.rolling(10).std() * 1.5) & high_vol
    ).astype(int)
    features["order_block_bear"] = (
        (ret < -ret.rolling(10).std() * 1.5) & high_vol
    ).astype(int)

    # Kill zones (time-based)
    if "hour_et" in df.columns:
        hour = df["hour_et"]
        features["london_killzone"] = ((hour >= 8) & (hour <= 11)).astype(int)
        features["ny_killzone"] = ((hour >= 13) & (hour <= 16)).astype(int)
        features["asian_killzone"] = ((hour >= 20) | (hour <= 4)).astype(int)

    return pd.DataFrame(features)


def add_vpa_features(df):
    """Volume Price Analysis features."""
    features = {}
    ret = df["returns"]
    vol = df.get("volume_ratio", pd.Series(1, index=df.index))

    # Volume-weighted returns
    features["vwap_ret"] = (ret * vol).rolling(10).sum() / (
        vol.rolling(10).sum() + 1e-8
    )

    # Volume trend
    for lb in [5, 10, 20]:
        features[f"vol_trend_{lb}"] = vol.rolling(lb).mean() / (
            vol.rolling(lb * 2).mean() + 1e-8
        )

    # Effort vs Result
    for lb in [3, 5, 10]:
        effort = vol.rolling(lb).sum()
        result = ret.rolling(lb).sum().abs()
        features[f"effort_result_{lb}"] = result / (effort + 1e-8)

    # Volume climax
    vol_std = vol.rolling(20).std()
    vol_mean = vol.rolling(20).mean()
    features["vol_climax"] = (vol - vol_mean) / (vol_std + 1e-8)

    # Accumulation/Distribution proxy
    features["ad_proxy"] = ((ret > 0) * vol - (ret < 0) * vol).rolling(10).sum()

    # On-Balance Volume style
    features["obv_proxy"] = (np.sign(ret) * vol).cumsum()
    features["obv_trend"] = (
        features["obv_proxy"].rolling(10).mean()
        - features["obv_proxy"].rolling(20).mean()
    )

    # Volume-price divergence
    ret_trend = ret.rolling(10).mean()
    vol_trend = vol.rolling(10).mean()
    features["vol_price_div"] = np.sign(ret_trend) != np.sign(vol_trend - 1)

    # Chaikin Money Flow style
    mf_mult = ((ret - ret.rolling(5).min()) - (ret.rolling(5).max() - ret)) / (
        ret.rolling(5).max() - ret.rolling(5).min() + 1e-8
    )
    features["cmf_proxy"] = (mf_mult * vol).rolling(20).sum() / (
        vol.rolling(20).sum() + 1e-8
    )

    return pd.DataFrame(features)


def add_derivative_features(df):
    """Derivative and acceleration features."""
    features = {}
    ret = df["returns"]

    # Velocity (1st derivative) - already have returns
    features["velocity"] = ret

    # Acceleration (2nd derivative)
    features["acceleration"] = ret.diff()
    features["acceleration_3"] = ret.diff(3)
    features["acceleration_5"] = ret.diff(5)

    # Jerk (3rd derivative)
    features["jerk"] = features["acceleration"].diff()

    # Smoothed derivatives
    for lb in [3, 5, 10]:
        features[f"smooth_vel_{lb}"] = ret.rolling(lb).mean()
        features[f"smooth_acc_{lb}"] = features[f"smooth_vel_{lb}"].diff()

    # Momentum acceleration
    for lb in [5, 10]:
        mom = ret.rolling(lb).sum()
        features[f"mom_acc_{lb}"] = mom.diff()
        features[f"mom_acc_acc_{lb}"] = features[f"mom_acc_{lb}"].diff()

    # Volatility derivatives
    vol = ret.rolling(10).std()
    features["vol_change"] = vol.diff()
    features["vol_acceleration"] = features["vol_change"].diff()

    return pd.DataFrame(features)


def add_relative_features(df):
    """Relative and ratio features."""
    features = {}
    ret = df["returns"]
    vol = df.get("volume_ratio", pd.Series(1, index=df.index))

    # Return relative to recent range
    for lb in [10, 20, 50]:
        ret_max = ret.rolling(lb).max()
        ret_min = ret.rolling(lb).min()
        features[f"ret_rel_range_{lb}"] = (ret - ret_min) / (ret_max - ret_min + 1e-8)

    # Return percentile
    for lb in [20, 50]:
        features[f"ret_percentile_{lb}"] = ret.rolling(lb).apply(
            lambda x: (x[-1] > x[:-1]).mean(), raw=True
        )

    # Volatility regime
    vol_short = ret.rolling(5).std()
    vol_long = ret.rolling(20).std()
    features["vol_regime"] = vol_short / (vol_long + 1e-8)

    # Trend strength
    for lb in [10, 20]:
        up_moves = (ret > 0).rolling(lb).sum()
        features[f"trend_strength_{lb}"] = (up_moves / lb - 0.5) * 2

    # Consecutive moves
    features["consec_up"] = (ret > 0).astype(int).groupby((ret <= 0).cumsum()).cumsum()
    features["consec_down"] = (
        (ret < 0).astype(int).groupby((ret >= 0).cumsum()).cumsum()
    )

    # Mean reversion potential
    for lb in [10, 20]:
        ma = ret.rolling(lb).mean()
        std = ret.rolling(lb).std()
        features[f"mean_rev_potential_{lb}"] = (ret - ma) / (std + 1e-8)

    return pd.DataFrame(features)


def add_time_features(df):
    """Time-based features."""
    features = {}

    if "hour_et" in df.columns:
        hour = df["hour_et"]

        # Cyclical encoding
        features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        features["hour_cos"] = np.cos(2 * np.pi * hour / 24)

        # Session indicators
        features["pre_market"] = (hour < 9.5).astype(int)
        features["market_open"] = ((hour >= 9.5) & (hour < 10.5)).astype(int)
        features["mid_morning"] = ((hour >= 10.5) & (hour < 12)).astype(int)
        features["lunch"] = ((hour >= 12) & (hour < 14)).astype(int)
        features["afternoon"] = ((hour >= 14) & (hour < 15.5)).astype(int)
        features["power_hour"] = (hour >= 15.5).astype(int)

    if "time_since_open" in df.columns:
        tso = df["time_since_open"]
        features["tso_norm"] = tso / 390  # Normalize to trading day
        features["tso_sin"] = np.sin(np.pi * tso / 390)

    return pd.DataFrame(features)


def add_interaction_features(df, base_features):
    """Interaction and cross features."""
    features = {}

    # Key feature interactions
    key_features = ["ret_5bar", "vol_10bar", "rsi_14", "vol_regime", "displacement_5"]
    key_features = [f for f in key_features if f in base_features.columns]

    for i, f1 in enumerate(key_features):
        for f2 in key_features[i + 1 :]:
            features[f"{f1}_x_{f2}"] = base_features[f1] * base_features[f2]

    # Momentum x Volume
    if "ret_5bar" in base_features.columns and "volume_ratio" in df.columns:
        features["mom_vol_interaction"] = base_features["ret_5bar"] * df["volume_ratio"]

    return pd.DataFrame(features)


def build_comprehensive_features(df):
    """Build all features."""
    print("Building comprehensive feature set...")

    all_features = [df[["timestamp", "symbol", "returns", "return_30min"]].copy()]

    # Add volume_ratio if exists
    if "volume_ratio" in df.columns:
        all_features[0]["volume_ratio"] = df["volume_ratio"]
    if "hour_et" in df.columns:
        all_features[0]["hour_et"] = df["hour_et"]

    # Multi-timeframe
    print("  Adding multi-timeframe features...")
    all_features.append(add_multi_timeframe_features(df))

    # Technical indicators
    print("  Adding technical indicators...")
    all_features.append(add_technical_indicators(df))

    # ICT features
    print("  Adding ICT features...")
    all_features.append(add_ict_features(df))

    # VPA features
    print("  Adding VPA features...")
    all_features.append(add_vpa_features(df))

    # Derivative features
    print("  Adding derivative features...")
    all_features.append(add_derivative_features(df))

    # Relative features
    print("  Adding relative features...")
    all_features.append(add_relative_features(df))

    # Time features
    print("  Adding time features...")
    all_features.append(add_time_features(df))

    # Combine
    result = pd.concat(all_features, axis=1)

    # Add interactions
    print("  Adding interaction features...")
    interactions = add_interaction_features(df, result)
    result = pd.concat([result, interactions], axis=1)

    # Remove duplicates
    result = result.loc[:, ~result.columns.duplicated()]

    print(f"  Total features: {len(result.columns)}")

    return result


def assess_feature_importance(df, target_col="return_30min", top_n=50):
    """Assess predictive power of each feature."""
    from scipy.stats import spearmanr
    from sklearn.feature_selection import mutual_info_regression

    print("\n" + "=" * 70)
    print("FEATURE IMPORTANCE ASSESSMENT")
    print("=" * 70)

    # Get feature columns (exclude metadata and target)
    exclude = [
        "timestamp",
        "symbol",
        "returns",
        "return_30min",
        "return_15min",
        "return_60min",
        "return_120min",
        "volume_ratio",
        "hour_et",
    ]
    feature_cols = [
        c
        for c in df.columns
        if c not in exclude and df[c].dtype in ["float64", "int64"]
    ]

    print(f"Assessing {len(feature_cols)} features...")

    # Prepare data
    df_clean = df.dropna(subset=feature_cols + [target_col])
    X = df_clean[feature_cols]
    y = df_clean[target_col]

    results = []

    for col in feature_cols:
        try:
            # Spearman correlation
            corr, pval = spearmanr(X[col], y)

            # Information coefficient (IC)
            ic = abs(corr)

            results.append(
                {
                    "feature": col,
                    "correlation": corr,
                    "abs_corr": abs(corr),
                    "p_value": pval,
                    "ic": ic,
                }
            )
        except:
            pass

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("abs_corr", ascending=False)

    print(f"\nTOP {top_n} FEATURES BY CORRELATION:")
    print("-" * 70)
    print(f"{'Feature':<40} {'Corr':>10} {'|Corr|':>10} {'P-value':>12}")
    print("-" * 70)

    for _, row in results_df.head(top_n).iterrows():
        sig = (
            "***"
            if row["p_value"] < 0.001
            else "**" if row["p_value"] < 0.01 else "*" if row["p_value"] < 0.05 else ""
        )
        print(
            f"{row['feature']:<40} {row['correlation']:>+10.4f} {row['abs_corr']:>10.4f} {row['p_value']:>10.2e} {sig}"
        )

    # Save results
    output_dir = Path("run/comprehensive_features")
    output_dir.mkdir(exist_ok=True)
    results_df.to_csv(output_dir / "feature_importance.csv", index=False)

    return results_df


def main():
    # Load existing data
    print("Loading data...")
    df = pl.read_parquet("run/news_driven_features/features.parquet").to_pandas()
    print(f"Loaded {len(df):,} rows")

    # Build comprehensive features
    features_df = build_comprehensive_features(df)

    # Save features
    output_dir = Path("run/comprehensive_features")
    output_dir.mkdir(exist_ok=True)
    features_df.to_parquet(output_dir / "features.parquet")
    print(f"\nSaved to {output_dir / 'features.parquet'}")

    # Assess importance
    importance_df = assess_feature_importance(features_df)

    # Get top features
    top_features = importance_df[importance_df["abs_corr"] > 0.01]["feature"].tolist()
    print(f"\nFeatures with |corr| > 0.01: {len(top_features)}")

    return features_df, importance_df


if __name__ == "__main__":
    features_df, importance_df = main()
