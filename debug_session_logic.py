#!/usr/bin/env python3
"""Debug the session counting logic that's causing perfect 20% distribution."""

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


def debug_session_logic(df):
    """Debug the session counting to find the perfect distribution issue."""
    print("DEBUG: Session Counting Logic")
    print("=" * 40)

    # Count regime occurrences by session (excluding warmup)
    warmup_mask = df.get("f__regime__warmup_ok", pd.Series(True, index=df.index))
    ready_bars = df[warmup_mask].copy()

    print(f"Ready bars after warmup: {len(ready_bars)}")

    # Add date and session info for session-based counting
    ready_bars["dt_et"] = pd.to_datetime(
        ready_bars["ts"], unit="ns", utc=True
    ).dt.tz_convert("America/New_York")
    ready_bars["date"] = ready_bars["dt_et"].dt.date
    ready_bars["session"] = ready_bars["dt_et"].apply(
        lambda x: "AM" if x.time() < pd.Timestamp("12:30").time() else "PM"
    )

    print(f"Date range: {ready_bars['date'].min()} to {ready_bars['date'].max()}")
    print(
        f"Sessions per day: {ready_bars.groupby('date')['session'].nunique().to_dict()}"
    )

    # Only process bars with valid regime features (no defaults)
    valid_mask = (
        ready_bars["f__regime__var_ratio_10_60"].notna()
        & ready_bars["f__regime__adx_proxy_14"].notna()
        & ready_bars["f__regime__band_pos_20_2.0"].notna()
        & ready_bars["f__regime__mod_vol_30"].notna()
        & ready_bars["f__regime__stress_10_10"].notna()
    )

    valid_bars = ready_bars[valid_mask]
    print(
        f"Valid regime bars: {len(valid_bars)} out of {len(ready_bars)} ({len(valid_bars)/len(ready_bars)*100:.1f}%)"
    )

    # Debug: Show first few actual regime values
    print(f"\nFirst 10 actual regime values:")
    sample = valid_bars[
        [
            "f__regime__var_ratio_10_60",
            "f__regime__adx_proxy_14",
            "f__regime__mod_vol_30",
            "f__regime__stress_10_10",
        ]
    ].head(10)
    print(sample.to_string(float_format="%.3f"))

    # Check unique sessions
    unique_sessions = valid_bars[["date", "session"]].drop_duplicates()
    print(f"\nUnique sessions: {len(unique_sessions)}")
    print(unique_sessions.head(10).to_string())

    # Check regime assignment for first few bars
    STRESS_VOL_THRESHOLD = 2.0
    BULL_VAR_RATIO_MIN = 1.2
    BEAR_VAR_RATIO_MAX = 0.8
    SIDEWAYS_VAR_RANGE = 0.1
    TRENDING_ADX_MIN = 25
    SIDEWAYS_ADX_MAX = 22

    print(f"\nRegime assignment for first 10 bars:")
    for i, (_, bar) in enumerate(valid_bars.head(10).iterrows()):
        features = {
            "var_ratio": bar["f__regime__var_ratio_10_60"],
            "adx": bar["f__regime__adx_proxy_14"],
            "mod_vol": bar["f__regime__mod_vol_30"],
            "stress": bar["f__regime__stress_10_10"],
        }

        # Simple regime classification using defined constants
        if features["stress"] > 0 or features["mod_vol"] >= STRESS_VOL_THRESHOLD:
            regime = "STRESS"
        elif (
            features["var_ratio"] > BULL_VAR_RATIO_MIN
            and features["adx"] >= TRENDING_ADX_MIN
        ):
            regime = "BULL"
        elif (
            features["var_ratio"] < BEAR_VAR_RATIO_MAX
            and features["adx"] >= TRENDING_ADX_MIN
        ):
            regime = "BEAR"
        elif (
            abs(features["var_ratio"] - 1.0) <= SIDEWAYS_VAR_RANGE
            or features["adx"] < SIDEWAYS_ADX_MAX
        ):
            regime = "SIDEWAYS"
        else:
            regime = "NONE"

        print(
            f"  Bar {i+1}: var_ratio={features['var_ratio']:.3f}, adx={features['adx']:.1f}, mod_vol={features['mod_vol']:.3f}, stress={features['stress']:.3f} -> {regime}"
        )

    # Now check the full counting logic
    regime_counts = {
        "BULL": set(),
        "BEAR": set(),
        "SIDEWAYS": set(),
        "STRESS": set(),
        "NONE": set(),
    }

    for _, bar in valid_bars.iterrows():
        features = {
            "var_ratio": bar["f__regime__var_ratio_10_60"],
            "adx": bar["f__regime__adx_proxy_14"],
            "mod_vol": bar["f__regime__mod_vol_30"],
            "stress": bar["f__regime__stress_10_10"],
        }

        # Simple regime classification using defined constants
        if features["stress"] > 0 or features["mod_vol"] >= STRESS_VOL_THRESHOLD:
            regime = "STRESS"
        elif (
            features["var_ratio"] > BULL_VAR_RATIO_MIN
            and features["adx"] >= TRENDING_ADX_MIN
        ):
            regime = "BULL"
        elif (
            features["var_ratio"] < BEAR_VAR_RATIO_MAX
            and features["adx"] >= TRENDING_ADX_MIN
        ):
            regime = "BEAR"
        elif (
            abs(features["var_ratio"] - 1.0) <= SIDEWAYS_VAR_RANGE
            or features["adx"] < SIDEWAYS_ADX_MAX
        ):
            regime = "SIDEWAYS"
        else:
            regime = "NONE"

        # Count unique sessions for each regime (twice per day)
        session_key = f"{bar['date']}_{bar['session']}"
        regime_counts[regime].add(session_key)

    # Show what's in each regime set
    print(f"\nSession sets content:")
    for regime, sessions in regime_counts.items():
        print(f"  {regime}: {len(sessions)} sessions")
        if len(sessions) > 0:
            sample_sessions = list(sessions)[:5]
            print(f"    Sample: {sample_sessions}")

    # Check if there's overlap
    all_sessions = set()
    for regime, sessions in regime_counts.items():
        overlap = all_sessions.intersection(sessions)
        if overlap:
            print(
                f"  WARNING: {regime} has {len(overlap)} overlapping sessions with previous regimes"
            )
        all_sessions.update(sessions)

    print(f"\nTotal unique sessions across all regimes: {len(all_sessions)}")

    return regime_counts


def main():
    print("Debug Session Counting Logic")
    print("=" * 50)

    # Load real data
    symbols = ["AAPL"]
    dates = ["2024-04-01"]
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

    # Compute features
    print(f"\nComputing features...")
    df = compute_all_core_features(df)
    df = compute_all_regime_features(df)

    # Debug the session logic
    regime_counts = debug_session_logic(df)

    print(f"\n✅ Debug completed!")


if __name__ == "__main__":
    main()
