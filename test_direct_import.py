#!/usr/bin/env python3
"""Test direct import of prepare_features function."""

import sys
import os

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-backtest", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-data", "src"))

print("Importing test_regime_pilot...")
import test_regime_pilot

print("Creating test data...")
df = test_regime_pilot.load_test_data()

print("Calling prepare_features from imported module...")
df_features = test_regime_pilot.prepare_features(df)

print("SUCCESS: prepare_features completed!")