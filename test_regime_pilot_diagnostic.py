#!/usr/bin/env python3
"""Diagnostic script to isolate the source of 'Mean of empty slice' warning."""

import argparse
import os
import sys
import traceback
import warnings

import pandas as pd

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-backtest", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "qx-data", "src"))

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


def load_test_data():
    """Load test data for April 1-7, 2024 using existing gold loader."""
    print("Loading test data for April 1-7, 2024...")

    symbols = ["AAPL"]
    dates = ["2024-04-01", "2024-04-02", "2024-04-03", "2024-04-04", "2024-04-05"]

    gold_root = "/home/jacobw/gcs-mount"

    if not os.path.exists(gold_root):
        raise RuntimeError(f"Gold data mount not accessible at {gold_root}.")

    print(f"Loading real market data from {gold_root}...")
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
                else:
                    print(f"No data found for {symbol} {date}")
            except Exception as e:
                print(f"Could not load {symbol} {date}: {e}")
                continue

    if not all_data:
        raise RuntimeError("No gold data could be loaded.")

    df = pd.concat(all_data, ignore_index=True)
    df = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    print(f"Successfully loaded {len(df)} bars")
    return df


def test_function_isolation(df, func_name, func, *args, **kwargs):
    """Test a single function and capture warnings."""
    print(f"\n{'='*60}")
    print(f"Testing: {func_name}")
    print(f"{'='*60}")

    # Capture warnings and stack traces
    captured_warnings = []

    def warning_handler(message, category, filename, lineno, file=None, line=None):
        if "Mean of empty slice" in str(message):
            captured_warnings.append(
                {
                    "message": str(message),
                    "category": category.__name__,
                    "filename": filename,
                    "lineno": lineno,
                    "traceback": traceback.format_stack(),
                }
            )

    old_showwarning = warnings.showwarning
    warnings.showwarning = warning_handler
    warnings.simplefilter("always", RuntimeWarning)

    try:
        result = func(df, *args, **kwargs)
        print(f"✓ {func_name} completed successfully")
        if captured_warnings:
            print(f"⚠️  WARNING DETECTED during {func_name}:")
            for w in captured_warnings:
                print(f"   Message: {w['message']}")
                print(f"   File: {w['filename']}:{w['lineno']}")
        return result, captured_warnings
    except Exception as e:
        print(f"✗ {func_name} failed with error: {e}")
        return None, []
    finally:
        warnings.showwarning = old_showwarning


def main():
    """Main diagnostic function."""
    argparse.ArgumentParser().parse_args()

    print("DIAGNOSTIC: Isolating RuntimeWarning Sources")
    print("=" * 60)

    # Load test data
    try:
        df = load_test_data()
    except Exception as e:
        print(f"Failed to load data: {e}")
        return

    print(f"\nInitial data shape: {df.shape}")
    print(f"Symbols: {df['symbol'].unique()}")
    print(f"Date range: {df['ts'].min()} to {df['ts'].max()}")

    # Test each function sequentially
    functions_to_test = [
        ("compute_all_core_features", compute_all_core_features),
        ("compute_all_regime_features", compute_all_regime_features),
        ("compute_avwap_features", compute_avwap_features),
        ("compute_intraday_volume_profile", compute_intraday_volume_profile, 100),
        ("compute_ict_structures", compute_ict_structures),
        ("compute_order_flow_vpa", compute_order_flow_vpa),
        ("compute_stress_contraction", compute_stress_contraction),
    ]

    warnings_found = {}
    current_df = df.copy()

    for test_case in functions_to_test:
        func_name = test_case[0]
        func = test_case[1]
        extra_args = test_case[2:] if len(test_case) > 2 else ()

        result_df, warnings_list = test_function_isolation(
            current_df, func_name, func, *extra_args
        )

        if result_df is not None:
            current_df = result_df
            if warnings_list:
                warnings_found[func_name] = warnings_list

    # Summary
    print(f"\n\n{'='*60}")
    print("DIAGNOSTIC SUMMARY")
    print(f"{'='*60}")

    if warnings_found:
        print(f"⚠️  WARNINGS FOUND IN {len(warnings_found)} FUNCTION(S):\n")
        for func_name, warnings_list in warnings_found.items():
            print(f"\n{func_name}:")
            for w in warnings_list:
                print(f"  - {w['message']}")
                print(f"    Location: {w['filename']}:{w['lineno']}")
    else:
        print("✓ No 'Mean of empty slice' warnings detected!")


if __name__ == "__main__":
    main()
