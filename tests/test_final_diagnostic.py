#!/usr/bin/env python3
"""Final corrected diagnostic function."""

import os
import sys

import pandas as pd

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-data", "src"))

from qx_data.gold_loader import load_bars
from qx_features.core_basics import compute_all_core_features
from qx_features.regime.features import compute_all_regime_features


def run_corrected_diagnostic(df, verbose=False):
    """Corrected diagnostic function that properly counts regimes."""
    if not verbose:
        return {"BULL": 0, "BEAR": 0, "SIDEWAYS": 0, "STRESS": 0, "OFF": 0, "NONE": 0}

    print("\nCORRECTED DIAGNOSTIC: Regime Signal Distribution")

    # Regime classification thresholds
    STRESS_VOL_THRESHOLD = 2.0
    BULL_VAR_RATIO_MIN = 1.2
    BEAR_VAR_RATIO_MAX = 0.8
    SIDEWAYS_VAR_RANGE = 0.1
    TRENDING_ADX_MIN = 25
    SIDEWAYS_ADX_MAX = 22

    # Count regime occurrences by session (excluding warmup)
    warmup_mask = df.get("f__regime__warmup_ok", pd.Series(True, index=df.index))
    ready_bars = df[warmup_mask].copy()

    if len(ready_bars) == 0:
        print("No bars past warmup period")
        return

    # Add date and session info for session-based counting
    ready_bars["dt_et"] = pd.to_datetime(ready_bars["ts"], unit="ns", utc=True).dt.tz_convert(
        "America/New_York"
    )
    ready_bars["date"] = ready_bars["dt_et"].dt.date
    ready_bars["session"] = ready_bars["dt_et"].apply(
        lambda x: "AM" if x.time() < pd.Timestamp("12:30").time() else "PM"
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
        f"Valid regime bars: {len(valid_bars)} out of {len(ready_bars)} ({len(valid_bars) / len(ready_bars) * 100:.1f}%)"
    )

    if len(valid_bars) == 0:
        print("No valid regime features found - skipping diagnostic")
        return {"BULL": 0, "BEAR": 0, "SIDEWAYS": 0, "STRESS": 0, "OFF": 0, "NONE": 0}

    # FIXED: Count regimes by bars (not sessions) for accuracy
    regime_counts = {"BULL": 0, "BEAR": 0, "SIDEWAYS": 0, "STRESS": 0, "NONE": 0}

    print(f"Classifying {len(valid_bars)} valid bars by regime...")

    for _, bar in valid_bars.iterrows():
        # Use actual feature values (no defaults)
        features = {
            "var_ratio": bar["f__regime__var_ratio_10_60"],
            "adx": bar["f__regime__adx_proxy_14"],
            "band_pos": bar["f__regime__band_pos_20_2.0"],
            "mod_vol": bar["f__regime__mod_vol_30"],
            "stress": bar["f__regime__stress_10_10"],
        }

        # Simple regime classification using defined constants
        if features["stress"] > 0 or features["mod_vol"] >= STRESS_VOL_THRESHOLD:
            regime = "STRESS"
        elif features["var_ratio"] > BULL_VAR_RATIO_MIN and features["adx"] >= TRENDING_ADX_MIN:
            regime = "BULL"
        elif features["var_ratio"] < BEAR_VAR_RATIO_MAX and features["adx"] >= TRENDING_ADX_MIN:
            regime = "BEAR"
        elif (
            abs(features["var_ratio"] - 1.0) <= SIDEWAYS_VAR_RANGE
            or features["adx"] < SIDEWAYS_ADX_MAX
        ):
            regime = "SIDEWAYS"
        else:
            regime = "NONE"

        regime_counts[regime] += 1

    total_bars = sum(regime_counts.values())
    print(f"Regime distribution over {total_bars} valid bars:")
    for regime, count in regime_counts.items():
        pct = (count / total_bars * 100) if total_bars > 0 else 0
        print(f"  {regime}: {count} bars ({pct:.1f}%)")

    if regime_counts["BULL"] + regime_counts["BEAR"] == 0:
        print("No trending regimes detected - policies may not generate trades")
    else:
        trending_pct = (regime_counts["BULL"] + regime_counts["BEAR"]) / total_bars * 100
        print(f"Trending regimes (BULL/BEAR): {trending_pct:.1f}% - Tradeable conditions")

    return regime_counts


def main():
    print("Testing Corrected Diagnostic Function")
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
    print("\nComputing features...")
    df = compute_all_core_features(df)
    df = compute_all_regime_features(df)

    # Test the corrected diagnostic
    run_corrected_diagnostic(df, verbose=True)

    print("\n✅ Corrected diagnostic test completed!")
    print("Now using bar-based counting (no session double-counting)")


if __name__ == "__main__":
    main()
