#!/usr/bin/env python3
"""Debug script to understand NaN values in regime features."""

import os
import sys

import numpy as np
import pandas as pd

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))

from qx_features.regime.features import (
    adx_proxy,
    band_position,
    compute_all_regime_features,
    mod_normalized_volatility,
    stress_metrics,
    variance_ratio,
)


def create_simple_test_data():
    """Create simple test data with sufficient history."""
    print("Creating simple test data...")

    # Create 2 days of data for one symbol to ensure enough warmup
    dates = pd.date_range(
        "2024-04-01 09:30:00", "2024-04-02 16:00:00", freq="1min", tz="America/New_York"
    )

    np.random.seed(42)  # For reproducibility
    base_price = 100.0
    data = []

    for _i, date in enumerate(dates):
        # Simple random walk
        price_change = np.random.randn() * 0.1
        base_price = max(base_price + price_change, 10.0)  # Ensure positive prices

        high = base_price + abs(np.random.randn() * 0.3)
        low = base_price - abs(np.random.randn() * 0.3)
        close = base_price
        open_price = close + np.random.randn() * 0.2
        volume = np.random.randint(1000, 5000)

        data.append(
            {
                "ts": int(
                    date.tz_convert("UTC").timestamp() * 1_000_000_000
                ),  # Convert to nanoseconds
                "symbol": "AAPL",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    df = pd.DataFrame(data)
    print(f"Created {len(df)} bars")
    return df


def debug_individual_features(df):
    """Test each feature individually to see where NaNs originate."""
    print("\n=== Testing Individual Features ===")

    print("\n1. Testing mod_normalized_volatility...")
    try:
        mod_vol = mod_normalized_volatility(df, lookback_m=30, min_periods=5)
        print(f"   mod_vol NaN count: {mod_vol.isna().sum()}/{len(mod_vol)}")
        print(f"   First 5 values: {mod_vol.head().tolist()}")
        print(f"   Last 5 values: {mod_vol.tail().tolist()}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n2. Testing variance_ratio...")
    try:
        var_ratio = variance_ratio(df, short_window=10, long_window=60, min_periods=3)
        print(f"   var_ratio NaN count: {var_ratio.isna().sum()}/{len(var_ratio)}")
        print(f"   First 5 values: {var_ratio.head().tolist()}")
        print(f"   Last 5 values: {var_ratio.tail().tolist()}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n3. Testing adx_proxy...")
    try:
        adx = adx_proxy(df, lookback_m=14, min_periods=3)
        print(f"   adx NaN count: {adx.isna().sum()}/{len(adx)}")
        print(f"   First 5 values: {adx.head().tolist()}")
        print(f"   Last 5 values: {adx.tail().tolist()}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n4. Testing band_position...")
    try:
        band_pos = band_position(df, window_m=20, std_dev=2.0, min_periods=5)
        print(f"   band_pos NaN count: {band_pos.isna().sum()}/{len(band_pos)}")
        print(f"   First 5 values: {band_pos.head().tolist()}")
        print(f"   Last 5 values: {band_pos.tail().tolist()}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n5. Testing stress_metrics...")
    try:
        stress = stress_metrics(
            df, volatility_window=10, volume_window=10, min_periods=3
        )
        print(f"   stress NaN count: {stress.isna().sum()}/{len(stress)}")
        print(f"   First 5 values: {stress.head().tolist()}")
        print(f"   Last 5 values: {stress.tail().tolist()}")
    except Exception as e:
        print(f"   Error: {e}")


def main():
    print("Debugging Regime Features NaN Values")
    print("=" * 50)

    # Create test data
    df = create_simple_test_data()

    # Test individual features
    debug_individual_features(df)

    # Test the combined function
    print("\n=== Testing Combined Function ===")
    try:
        df_with_features = compute_all_regime_features(df)
        print("Combined function completed successfully")

        # Check NaN counts for each regime feature
        regime_features = [
            col for col in df_with_features.columns if col.startswith("f__regime__")
        ]
        print(f"\nRegime features computed: {len(regime_features)}")

        for feature in regime_features:
            nan_count = df_with_features[feature].isna().sum()
            total_count = len(df_with_features)
            print(
                f"  {feature}: {nan_count}/{total_count} NaN values ({nan_count/total_count*100:.1f}%)"
            )

            if nan_count < total_count:
                # Show first non-NaN value
                first_valid = df_with_features[feature].first_valid_index()
                if first_valid is not None:
                    print(
                        f"    First valid value at index {first_valid}: {df_with_features[feature].loc[first_valid]}"
                    )
    except Exception as e:
        print(f"Combined function error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
