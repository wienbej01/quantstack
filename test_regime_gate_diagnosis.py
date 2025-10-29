#!/usr/bin/env python3
"""Diagnostic script to identify why policies aren't generating trades."""

import os
import sys

import pandas as pd

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-backtest", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-data", "src"))

from qx_backtest.policies.regime_aligned import AVWAPMomentumPolicy
from qx_core.schemas import RegimeType
from qx_data.gold_loader import load_bars
from qx_features.core_basics import compute_all_core_features
from qx_features.regime.features import compute_all_regime_features
from qx_features.regime_enhanced import (
    compute_avwap_features,
    compute_ict_structures,
    compute_intraday_volume_profile,
    compute_order_flow_vpa,
    compute_stress_contraction,
)


def load_small_dataset():
    """Load minimal test data."""
    gold_root = "/home/jacobw/gcs-mount"

    if os.path.exists(gold_root):
        try:
            df = load_bars(
                root=gold_root,
                family="stocks",
                symbols=["AAPL"],
                dates=["2024-04-01"],
                validate=False,
            )
            if df is not None and len(df) > 0:
                return df.sort_values(["symbol", "ts"]).reset_index(drop=True)
        except Exception as e:
            print(f"Could not load gold data: {e}")

    return None


def prepare_features_minimal(df):
    """Compute minimal features."""
    print(f"\n[1] Computing features for {len(df)} bars...")
    df = compute_all_core_features(df)
    df = compute_all_regime_features(df)
    df = compute_avwap_features(df)
    df = compute_intraday_volume_profile(df, window=100)
    df = compute_ict_structures(df)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        df = compute_order_flow_vpa(df)

    df = compute_stress_contraction(df)

    # Set warmup
    df["f__warmup_ok"] = df.groupby("symbol").cumcount() >= 100

    return df


def diagnose_trade_gates(df):
    """Check all gates that could prevent trading."""
    print("\n" + "=" * 70)
    print("TRADE GATE DIAGNOSTICS")
    print("=" * 70)

    # Filter to warmed-up bars only
    warmed = df[df["f__warmup_ok"]].copy()
    print(
        f"\n[2] Warmed-up bars: {len(warmed)}/{len(df)} ({len(warmed)/len(df)*100:.1f}%)"
    )

    if len(warmed) == 0:
        print("❌ NO WARMED-UP BARS - Cannot proceed")
        return

    # Check for regime field
    print(f"\n[3] Checking for regime classification field...")
    has_regime_current = "f__regime__current" in warmed.columns
    print(
        f"   {'✓' if has_regime_current else '❌'} 'f__regime__current' field exists: {has_regime_current}"
    )

    if has_regime_current:
        regime_dist = warmed["f__regime__current"].value_counts()
        print(f"   Regime distribution:")
        for regime, count in regime_dist.items():
            print(f"      {regime}: {count} bars ({count/len(warmed)*100:.1f}%)")
    else:
        print(
            "   ⚠️  CRITICAL: Regime field missing - policies will see RegimeType.OFF!"
        )

    # Check regime feature values
    print(f"\n[4] Checking regime feature values (sample of 5 bars after warmup)...")
    regime_cols = [
        "f__regime__var_ratio_10_60",
        "f__regime__adx_proxy_14",
        "f__regime__band_pos_20_2.0",
        "f__regime__mod_vol_30",
        "f__regime__stress_10_10",
    ]

    sample = warmed[regime_cols].head(5)
    print(sample.to_string())

    # Manually classify what regime these should be
    print(f"\n[5] Manual regime classification (using detector thresholds)...")
    BULL_VR_MIN = 1.2
    BEAR_VR_MAX = 0.8
    TRENDING_ADX_MIN = 25
    STRESS_VOL = 2.0

    for idx, row in warmed.head(10).iterrows():
        vr = row["f__regime__var_ratio_10_60"]
        adx = row["f__regime__adx_proxy_14"]
        vol = row["f__regime__mod_vol_30"]
        stress = row["f__regime__stress_10_10"]

        if stress > 0 or vol >= STRESS_VOL:
            expected = "STRESS"
        elif vr > BULL_VR_MIN and adx >= TRENDING_ADX_MIN:
            expected = "BULL"
        elif vr < BEAR_VR_MAX and adx >= TRENDING_ADX_MIN:
            expected = "BEAR"
        else:
            expected = "SIDEWAYS"

        actual = row.get("f__regime__current", "MISSING")
        match = "✓" if actual == expected else "❌"
        print(
            f"   Bar {idx}: VR={vr:.2f} ADX={adx:.1f} Vol={vol:.2f} => Expected={expected}, Actual={actual} {match}"
        )

    # Check AVWAP features
    print(f"\n[6] Checking AVWAP features (needed for momentum entry)...")
    avwap_cols = ["f__anchor__session_avwap", "f__anchor__first_hour_avwap", "close"]
    if all(col in warmed.columns for col in avwap_cols):
        sample = warmed[avwap_cols].head(5)
        print(sample.to_string())

        # Check if price is above/below AVWAP
        above_both = (warmed["close"] > warmed["f__anchor__session_avwap"]) & (
            warmed["close"] > warmed["f__anchor__first_hour_avwap"]
        )
        print(
            f"   Bars above both AVWAPs: {above_both.sum()}/{len(warmed)} ({above_both.sum()/len(warmed)*100:.1f}%)"
        )
    else:
        print("   ❌ AVWAP features missing!")

    # Check ICT features
    print(f"\n[7] Checking ICT features (FVG, discount/premium)...")
    ict_cols = [
        "f__ict__in_discount",
        "f__ict__in_premium",
        "f__ict__fvg_bull_active",
        "f__ict__fvg_bear_active",
    ]
    if all(col in warmed.columns for col in ict_cols):
        in_discount = warmed["f__ict__in_discount"].sum()
        in_premium = warmed["f__ict__in_premium"].sum()
        fvg_bull = warmed["f__ict__fvg_bull_active"].sum()
        fvg_bear = warmed["f__ict__fvg_bear_active"].sum()

        print(
            f"   In discount zone: {in_discount} bars ({in_discount/len(warmed)*100:.1f}%)"
        )
        print(
            f"   In premium zone: {in_premium} bars ({in_premium/len(warmed)*100:.1f}%)"
        )
        print(
            f"   Bullish FVG active: {fvg_bull} bars ({fvg_bull/len(warmed)*100:.1f}%)"
        )
        print(
            f"   Bearish FVG active: {fvg_bear} bars ({fvg_bear/len(warmed)*100:.1f}%)"
        )
    else:
        print("   ❌ ICT features missing!")

    # Check ATR
    print(f"\n[8] Checking ATR (minimum 0.5 required for trade)...")
    if "f__vol__atr_14" in warmed.columns:
        atr_ok = (warmed["f__vol__atr_14"] >= 0.5).sum()
        print(
            f"   ATR >= 0.5: {atr_ok}/{len(warmed)} bars ({atr_ok/len(warmed)*100:.1f}%)"
        )
        print(
            f"   ATR range: {warmed['f__vol__atr_14'].min():.3f} - {warmed['f__vol__atr_14'].max():.3f}"
        )
    else:
        print("   ❌ ATR feature missing!")

    # Test a specific bar against entry logic
    print(f"\n[9] Testing entry logic on a sample bar...")
    test_bar = (
        warmed.iloc[100].to_dict() if len(warmed) > 100 else warmed.iloc[0].to_dict()
    )

    # Add regime if missing
    if "f__regime__current" not in test_bar:
        # Manually classify
        vr = test_bar["f__regime__var_ratio_10_60"]
        adx = test_bar["f__regime__adx_proxy_14"]
        if vr > BULL_VR_MIN and adx >= TRENDING_ADX_MIN:
            test_bar["f__regime__current"] = RegimeType.BULL
        else:
            test_bar["f__regime__current"] = RegimeType.SIDEWAYS

    policy = AVWAPMomentumPolicy()

    print(f"   Bar regime: {test_bar.get('f__regime__current', 'MISSING')}")
    print(f"   Close: {test_bar.get('close', 0):.2f}")
    print(f"   Session AVWAP: {test_bar.get('f__anchor__session_avwap', 0):.2f}")
    print(f"   First hour AVWAP: {test_bar.get('f__anchor__first_hour_avwap', 0):.2f}")
    print(f"   In discount: {test_bar.get('f__ict__in_discount', False)}")
    print(f"   VR: {test_bar.get('f__regime__var_ratio_10_60', 0):.2f}")
    print(f"   ADX: {test_bar.get('f__regime__adx_proxy_14', 0):.1f}")
    print(f"   ATR: {test_bar.get('f__vol__atr_14', 0):.3f}")

    # Check each gate manually
    gates_passed = []
    gates_failed = []

    if policy._check_regime_gating(test_bar):
        gates_passed.append("Regime gating")
    else:
        gates_failed.append("Regime gating (strategy not allowed or wrong regime)")

    if policy._check_warmup(test_bar):
        gates_passed.append("Warmup check")
    else:
        gates_failed.append("Warmup check")

    print(f"\n   Gates passed: {gates_passed}")
    print(f"   Gates FAILED: {gates_failed}")

    print(f"\n" + "=" * 70)
    print("DIAGNOSIS SUMMARY")
    print("=" * 70)
    print(f"✓ Features computed successfully")
    print(
        f"{'❌' if not has_regime_current else '✓'} Regime classification {'MISSING' if not has_regime_current else 'present'}"
    )

    if not has_regime_current:
        print(
            f"\n🔴 ROOT CAUSE: 'f__regime__current' field is NOT being added to bars!"
        )
        print(f"   The backtest engine or test script needs to:")
        print(f"   1. Create a regime detector")
        print(
            f"   2. Run detector.evaluate() or detector.evaluate_symbol() on each bar"
        )
        print(f"   3. Add the result as bar['f__regime__current'] = signal.regime")
        print(f"   Without this, all policies see RegimeType.OFF and cannot trade!")


def main():
    print("Trade Gate Diagnostic Tool")
    print("=" * 70)

    df = load_small_dataset()
    if df is None or len(df) == 0:
        print("❌ Could not load test data")
        return

    print(f"Loaded {len(df)} bars")

    df = prepare_features_minimal(df)
    diagnose_trade_gates(df)


if __name__ == "__main__":
    main()
