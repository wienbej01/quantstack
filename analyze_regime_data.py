#!/usr/bin/env python3
"""Analyze the actual regime data quality and distribution."""

import os
import sys

import numpy as np
import pandas as pd

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-data", "src"))

from qx_data.gold_loader import load_bars
from qx_features.core_basics import compute_all_core_features
from qx_features.regime.features import compute_all_regime_features


def analyze_real_data():
    """Load and analyze real AAPL data."""
    print("Analyzing Real AAPL Market Data")
    print("=" * 50)

    # Load real data
    symbols = ["AAPL"]
    dates = ["2024-04-01", "2024-04-02"]
    gold_root = "/home/jacobw/gcs-mount"

    if not os.path.exists(gold_root):
        print(f"Gold mount not accessible: {gold_root}")
        return

    print(f"Loading data from {gold_root}...")
    all_data = []
    for symbol in symbols:
        for date in dates:
            try:
                symbol_data = load_bars(
                    root=gold_root,
                    family="stocks",
                    symbols=[symbol],
                    dates=[date],
                    validate=False,
                )
                if symbol_data is not None and len(symbol_data) > 0:
                    print(f"Loaded {len(symbol_data)} bars for {symbol} {date}")
                    all_data.append(symbol_data)
            except Exception as e:
                print(f"Error loading {symbol} {date}: {e}")

    if not all_data:
        print("No data loaded")
        return

    df = pd.concat(all_data, ignore_index=True)
    df = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    print(f"Total data: {len(df)} bars")

    # Analyze raw data first
    print(f"\nRaw Data Analysis:")
    print(
        f"  Time range: {pd.to_datetime(df['ts'], unit='ns', utc=True).min()} to {pd.to_datetime(df['ts'], unit='ns', utc=True).max()}"
    )
    print(f"  Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    print(f"  Volume range: {df['volume'].min()} - {df['volume'].max()}")

    # Compute features
    print(f"\nComputing features...")
    df = compute_all_core_features(df)
    df = compute_all_regime_features(df)

    # Analyze regime feature quality
    regime_features = [col for col in df.columns if col.startswith("f__regime__")]
    print(f"\nRegime Features Analysis:")

    for feature in regime_features:
        total_count = len(df)
        nan_count = df[feature].isna().sum()
        valid_count = total_count - nan_count
        pct_valid = (valid_count / total_count) * 100

        print(f"  {feature}:")
        print(
            f"    Total: {total_count}, Valid: {valid_count}, NaN: {nan_count} ({pct_valid:.1f}% valid)"
        )

        if valid_count > 0:
            valid_values = df[feature].dropna()
            print(f"    Range: {valid_values.min():.3f} to {valid_values.max():.3f}")
            print(f"    Mean: {valid_values.mean():.3f}, Std: {valid_values.std():.3f}")

    # Analyze actual regime distribution (without defaults)
    print(f"\nActual Regime Distribution (No Defaults):")

    # Only analyze rows with valid regime features
    valid_mask = (
        df["f__regime__var_ratio_10_60"].notna()
        & df["f__regime__adx_proxy_14"].notna()
        & df["f__regime__band_pos_20_2.0"].notna()
        & df["f__regime__mod_vol_30"].notna()
        & df["f__regime__stress_10_10"].notna()
    )

    valid_bars = df[valid_mask]
    print(
        f"Valid regime bars: {len(valid_bars)} out of {len(df)} ({len(valid_bars)/len(df)*100:.1f}%)"
    )

    if len(valid_bars) > 0:
        # Real regime classification
        STRESS_VOL_THRESHOLD = 2.0
        BULL_VAR_RATIO_MIN = 1.2
        BEAR_VAR_RATIO_MAX = 0.8
        SIDEWAYS_VAR_RANGE = 0.1
        TRENDING_ADX_MIN = 25
        SIDEWAYS_ADX_MAX = 22

        regimes = []
        for _, bar in valid_bars.iterrows():
            var_ratio = bar["f__regime__var_ratio_10_60"]
            adx = bar["f__regime__adx_proxy_14"]
            mod_vol = bar["f__regime__mod_vol_30"]
            stress = bar["f__regime__stress_10_10"]

            if stress > 0 or mod_vol >= STRESS_VOL_THRESHOLD:
                regime = "STRESS"
            elif var_ratio > BULL_VAR_RATIO_MIN and adx >= TRENDING_ADX_MIN:
                regime = "BULL"
            elif var_ratio < BEAR_VAR_RATIO_MAX and adx >= TRENDING_ADX_MIN:
                regime = "BEAR"
            elif abs(var_ratio - 1.0) <= SIDEWAYS_VAR_RANGE or adx < SIDEWAYS_ADX_MAX:
                regime = "SIDEWAYS"
            else:
                regime = "NONE"

            regimes.append(regime)

        regime_counts = pd.Series(regimes).value_counts()
        total_valid = len(regimes)

        print(f"Regime distribution over {total_valid} valid bars:")
        for regime, count in regime_counts.items():
            pct = (count / total_valid) * 100
            print(f"  {regime}: {count} bars ({pct:.1f}%)")
    else:
        print("No valid regime features found!")

    # Sample some actual values
    print(f"\nSample Regime Feature Values (First 5 valid rows):")
    if len(valid_bars) > 0:
        sample_cols = [
            "f__regime__var_ratio_10_60",
            "f__regime__adx_proxy_14",
            "f__regime__mod_vol_30",
        ]
        sample_data = valid_bars[sample_cols].head()
        print(sample_data.to_string(float_format="%.3f"))
    else:
        print("No valid regime data to sample")

    print(f"\n✅ Analysis complete!")


if __name__ == "__main__":
    analyze_real_data()
