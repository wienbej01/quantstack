#!/usr/bin/env python3
"""Step by step debugging of prepare_features function."""

import sys
import os
import signal

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-backtest", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-data", "src"))

# Timeout handler
def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

# Set timeout
signal.signal(signal.SIGALRM, timeout_handler)

print("Importing functions...")
from test_regime_pilot import load_test_data
from qx_features.core_basics import compute_all_core_features
from qx_features.regime.features import compute_all_regime_features
from qx_features.regime_enhanced import compute_all_regime_enhanced_features

print("Creating test data...")
df = load_test_data()
print(f"Data created: {len(df)} bars")

print("Testing core features computation...")
signal.alarm(30)  # 30 second timeout
try:
    df_core = compute_all_core_features(df)
    signal.alarm(0)  # Cancel timeout
    print("SUCCESS: Core features computed!")
    print(f"Core features shape: {df_core.shape}")

    print("Testing regime features computation...")
    signal.alarm(30)
    df_regime = compute_all_regime_features(df_core)
    signal.alarm(0)
    print("SUCCESS: Regime features computed!")

    print("Testing enhanced features computation...")
    signal.alarm(30)
    df_enhanced = compute_all_regime_enhanced_features(df_regime)
    signal.alarm(0)
    print("SUCCESS: Enhanced features computed!")

    print("All features computed successfully!")

except TimeoutError:
    print("TIMEOUT: Operation timed out")
    signal.alarm(0)
except Exception as e:
    print(f"ERROR: {e}")
    signal.alarm(0)