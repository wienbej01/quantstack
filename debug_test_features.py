#!/usr/bin/env python3
"""Debug test for prepare_features function."""

import os
import sys

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-backtest", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-data", "src"))

from test_regime_pilot import load_test_data
from qx_features.core_basics import compute_all_core_features
from qx_features.regime.features import compute_all_regime_features
from qx_features.regime_enhanced import compute_all_regime_enhanced_features

def prepare_features_debug(df):
    """Prepare all required features for regime-aligned strategies."""
    print("Computing features...")

    # Compute core features
    df = compute_all_core_features(df)
    print("✅ Core features computed")

    # Compute regime features (NEW)
    df = compute_all_regime_features(df)
    print("✅ Regime features computed")

    # Compute regime-enhanced features
    df = compute_all_regime_enhanced_features(df)
    print("✅ Enhanced features computed")

    # Verify regime features are present (verbose)
    verbose = True  # TODO: Make this parameterizable
    if verbose:
        regime_features = [col for col in df.columns if col.startswith("f__regime__")]
        print(f"✅ Regime features present: {len(regime_features)} columns")
        if len(df) > 0:
            print("First few regime feature values:")
            print(df[regime_features].head(2).to_string())

    return df

def main():
    print("🚀 Debug Test for prepare_features")
    print("=" * 50)

    # Load data
    df = load_test_data()
    if df is None or len(df) == 0:
        print("❌ No data available for testing")
        return

    print(f"✅ Loaded {len(df)} bars")

    # Prepare features
    print("Starting feature computation...")
    df_features = prepare_features_debug(df)
    print("✅ Feature computation completed successfully!")

if __name__ == "__main__":
    main()