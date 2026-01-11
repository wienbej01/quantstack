#!/usr/bin/env python3
"""Test manual patterns implementation."""

import sys
from pathlib import Path

# Setup paths
root = Path("/home/jacobw/quantstack")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "sip_pattern_discovery"))
sys.path.insert(0, str(root / "pattern_backtest"))

from pattern_backtest.src.manual_patterns import (
    MANUAL_PATTERNS,
    evaluate_all_manual_patterns,
)

print("=" * 80)
print("MANUAL PATTERNS TEST")
print("=" * 80)

# Display loaded patterns
print(f"\nLoaded {len(MANUAL_PATTERNS)} manual patterns:\n")
for pattern_id, data in MANUAL_PATTERNS.items():
    print(f"{pattern_id}:")
    print(f"  Description: {data['description']}")
    print(f"  Rule: {data['rule']}")
    print(f"  Lift: {data['lift']:.2f}x")
    print(f"  Support: {data['support']:.2%}")
    print()

# Test pattern evaluation
print("=" * 80)
print("PATTERN EVALUATION TEST")
print("=" * 80)

# Test bar 1: Matches pattern 1 (high ATR + power hour)
test_bar_1 = {
    "symbol": "TEST",
    "atr_14_bin": 4,
    "is_power_hour_bin": True,
    "ret_60m_bin": 2.0,
    "rvol_bin": 2,
}

matches_1 = evaluate_all_manual_patterns(test_bar_1)
print(f"\nTest Bar 1: {test_bar_1}")
print(f"Matches: {matches_1}")

# Test bar 2: Matches pattern 2 (momentum + power hour)
test_bar_2 = {
    "symbol": "TEST",
    "atr_14_bin": 2,
    "is_power_hour_bin": True,
    "ret_60m_bin": 4.0,
    "rvol_bin": 2,
}

matches_2 = evaluate_all_manual_patterns(test_bar_2)
print(f"\nTest Bar 2: {test_bar_2}")
print(f"Matches: {matches_2}")

# Test bar 3: Matches pattern 15 (volume + power hour)
test_bar_3 = {
    "symbol": "TEST",
    "atr_14_bin": 2,
    "is_power_hour_bin": True,
    "ret_60m_bin": 2.0,
    "rvol_bin": 3,
}

matches_3 = evaluate_all_manual_patterns(test_bar_3)
print(f"\nTest Bar 3: {test_bar_3}")
print(f"Matches: {matches_3}")

# Test bar 4: No power hour (no matches)
test_bar_4 = {
    "symbol": "TEST",
    "atr_14_bin": 4,
    "is_power_hour_bin": False,
    "ret_60m_bin": 4.0,
    "rvol_bin": 3,
}

matches_4 = evaluate_all_manual_patterns(test_bar_4)
print(f"\nTest Bar 4: {test_bar_4}")
print(f"Matches: {matches_4}")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
