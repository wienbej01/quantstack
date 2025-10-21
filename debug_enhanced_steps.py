#!/usr/bin/env python3
"""Debug each step of enhanced features individually."""

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
from qx_features.regime_enhanced import (
    compute_avwap_features,
    compute_intraday_volume_profile,
    compute_ict_structures,
    compute_order_flow_vpa,
    compute_stress_contraction
)

print("Creating test data...")
df = load_test_data()
print(f"Data created: {len(df)} bars")

print("Computing core features...")
df_core = compute_all_core_features(df)
print("Core features computed")

print("Computing regime features...")
df_regime = compute_all_regime_features(df_core)
print("Regime features computed")

print("\n=== Testing Enhanced Features Step by Step ===")

# Test Step 1: AVWAP features
print("Step 1: Testing AVWAP features...")
signal.alarm(10)  # 10 second timeout
try:
    df_step1 = compute_avwap_features(df_regime)
    signal.alarm(0)
    print("✓ AVWAP features computed successfully")
except TimeoutError:
    print("✗ AVWAP features timed out")
    signal.alarm(0)
    exit(1)
except Exception as e:
    print(f"✗ AVWAP features error: {e}")
    signal.alarm(0)
    exit(1)

# Test Step 2: Volume profile
print("Step 2: Testing volume profile...")
signal.alarm(10)
try:
    df_step2 = compute_intraday_volume_profile(df_step1, verbose=False)
    signal.alarm(0)
    print("✓ Volume profile computed successfully")
except TimeoutError:
    print("✗ Volume profile timed out")
    signal.alarm(0)
    exit(1)
except Exception as e:
    print(f"✗ Volume profile error: {e}")
    signal.alarm(0)
    exit(1)

# Test Step 3: ICT structures
print("Step 3: Testing ICT structures...")
signal.alarm(10)
try:
    df_step3 = compute_ict_structures(df_step2, verbose=False)
    signal.alarm(0)
    print("✓ ICT structures computed successfully")
except TimeoutError:
    print("✗ ICT structures timed out")
    signal.alarm(0)
    exit(1)
except Exception as e:
    print(f"✗ ICT structures error: {e}")
    signal.alarm(0)
    exit(1)

# Test Step 4: Order flow VPA
print("Step 4: Testing order flow VPA...")
signal.alarm(10)
try:
    df_step4 = compute_order_flow_vpa(df_step3, verbose=False)
    signal.alarm(0)
    print("✓ Order flow VPA computed successfully")
except TimeoutError:
    print("✗ Order flow VPA timed out")
    signal.alarm(0)
    exit(1)
except Exception as e:
    print(f"✗ Order flow VPA error: {e}")
    signal.alarm(0)
    exit(1)

# Test Step 5: Stress contraction
print("Step 5: Testing stress contraction...")
signal.alarm(10)
try:
    df_step5 = compute_stress_contraction(df_step4, verbose=False)
    signal.alarm(0)
    print("✓ Stress contraction computed successfully")
except TimeoutError:
    print("✗ Stress contraction timed out")
    signal.alarm(0)
    exit(1)
except Exception as e:
    print(f"✗ Stress contraction error: {e}")
    signal.alarm(0)
    exit(1)

print("\n✓ All enhanced features steps completed successfully!")