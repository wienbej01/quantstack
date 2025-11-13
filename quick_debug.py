#!/usr/bin/env python3
"""
Quick test to debug why baseline generates no trades.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from qx_data.gold_loader import load_bars
from qx_features.core_basics import CoreBasicsFeaturePack


def quick_debug():
    """Quick debug of VWAP values in actual data."""

    print("🔍 Quick VWAP Debug")
    print("=" * 50)

    try:
        data = load_bars(
            root="/home/jacobw/gcs-mount",
            family="bars_1m",
            symbols=["AAPL"],
            dates=["2024-01-02"],
        )

        print(f"Loaded {len(data)} bars for AAPL on 2024-01-02")

        # Compute VWAP
        feature_pack = CoreBasicsFeaturePack()
        features = feature_pack.compute(data)

        # Check VWAP values and deviations
        features["vwap_deviation_pct"] = (
            (features["close"] - features["f__ta__vwap_30"]) / features["f__ta__vwap_30"]
        ) * 100

        print("\nVWAP Deviation Analysis:")
        print(f"  Min deviation: {features['vwap_deviation_pct'].min():.2f}%")
        print(f"  Max deviation: {features['vwap_deviation_pct'].max():.2f}%")
        print(f"  Mean deviation: {features['vwap_deviation_pct'].mean():.2f}%")
        print(f"  Std deviation: {features['vwap_deviation_pct'].std():.2f}%")

        # Check how many times price crosses 2% threshold
        below_2pct = (features["vwap_deviation_pct"] < -2.0).sum()
        above_2pct = (features["vwap_deviation_pct"] > 2.0).sum()

        print("\nThreshold Analysis (2%):")
        print(f"  Times price >2% below VWAP: {below_2pct}")
        print(f"  Times price >2% above VWAP: {above_2pct}")
        print(f"  Total trading opportunities: {below_2pct + above_2pct}")

        if below_2pct + above_2pct == 0:
            print("\n❌ NO TRADING OPPORTUNITIES: 2% threshold is too strict!")
            print("   Consider loosening to 1% or 0.5%")

            # Check 1% threshold
            below_1pct = (features["vwap_deviation_pct"] < -1.0).sum()
            above_1pct = (features["vwap_deviation_pct"] > 1.0).sum()
            print("\nThreshold Analysis (1%):")
            print(f"  Times price >1% below VWAP: {below_1pct}")
            print(f"  Times price >1% above VWAP: {above_1pct}")
            print(f"  Total trading opportunities: {below_1pct + above_1pct}")

            # Check 0.5% threshold
            below_05pct = (features["vwap_deviation_pct"] < -0.5).sum()
            above_05pct = (features["vwap_deviation_pct"] > 0.5).sum()
            print("\nThreshold Analysis (0.5%):")
            print(f"  Times price >0.5% below VWAP: {below_05pct}")
            print(f"  Times price >0.5% above VWAP: {above_05pct}")
            print(f"  Total trading opportunities: {below_05pct + above_05pct}")

        # Show some examples
        print("\nSample VWAP deviations:")
        sample = features[["ts", "close", "f__ta__vwap_30", "vwap_deviation_pct"]].head(10)
        for _, row in sample.iterrows():
            print(
                f"  {row['ts']}: Close=${row['close']:.2f}, VWAP=${row['f__ta__vwap_30']:.2f}, Dev={row['vwap_deviation_pct']:.2f}%"
            )

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    quick_debug()
