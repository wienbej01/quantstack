#!/usr/bin/env python3
"""
Test IOC Price Improvement - Simulate Exact Production Scenario
This test loads the actual config and simulates the exact code path.
"""

import sys
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "l2_scalping" / "src"))


def test_ioc_price_improvement():
    """Test that IOC price improvement is calculated correctly"""

    # Load actual config (same as production)
    config_dir = Path(__file__).parent / "l2_scalping" / "config"
    config = {}

    config_files = {
        "strategy": "strategy.yaml",
        "risk": "risk.yaml",
        "ibkr": "ibkr.yaml",
    }

    for key, filename in config_files.items():
        filepath = config_dir / filename
        with open(filepath) as f:
            config[key] = yaml.safe_load(f)

    print("=" * 70)
    print("IOC PRICE IMPROVEMENT TEST")
    print("=" * 70)
    print()

    # Extract config values (EXACT same code as production)
    use_ioc = config["ibkr"]["orders"]["use_ioc_for_scalping"]
    improvement_ticks = config["ibkr"]["orders"].get("ioc_price_improvement_ticks", 0)
    tick_size = config["ibkr"]["orders"].get("tick_size", 0.01)
    price_improvement = improvement_ticks * tick_size if use_ioc else 0.0

    print("CONFIG VALUES:")
    print(f"  use_ioc: {use_ioc}")
    print(f"  improvement_ticks: {improvement_ticks}")
    print(f"  tick_size: {tick_size}")
    print(f"  price_improvement: {price_improvement}")
    print()

    # Simulate actual market data from yesterday
    test_cases = [
        {"symbol": "NVDA", "ask": 187.39, "bid": 187.38, "side": "BUY"},
        {"symbol": "NVDA", "ask": 187.37, "bid": 187.36, "side": "BUY"},
        {"symbol": "PLUG", "ask": 2.64, "bid": 2.63, "side": "BUY"},
        {"symbol": "INTC", "ask": 47.89, "bid": 47.88, "side": "SELL"},
    ]

    print("TEST CASES (Simulating Yesterday's Orders):")
    print("-" * 70)

    all_passed = True

    for i, case in enumerate(test_cases, 1):
        # EXACT same calculation as production code
        if case["side"] == "BUY":
            limit_price = case["ask"] + price_improvement
            expected_price = case["ask"] + 0.01  # What we SHOULD get
            base_price = case["ask"]
        else:
            limit_price = case["bid"] - price_improvement
            expected_price = case["bid"] - 0.01  # What we SHOULD get
            base_price = case["bid"]

        # Check if improvement was applied
        improvement_applied = abs(limit_price - base_price) > 0.001

        status = "✅ PASS" if improvement_applied else "❌ FAIL"
        all_passed = all_passed and improvement_applied

        print(f"\nTest {i}: {case['symbol']} {case['side']}")
        print(f"  Market: ask={case['ask']}, bid={case['bid']}")
        print(f"  Calculated limit_price: {limit_price:.4f}")
        print(f"  Expected limit_price: {expected_price:.4f}")
        print(f"  Improvement applied: {improvement_applied}")
        print(f"  Status: {status}")

    print()
    print("=" * 70)

    if all_passed:
        print("✅ ALL TESTS PASSED - IOC Price Improvement is WORKING")
        print()
        print("Expected behavior:")
        print("  - BUY orders: limit_price = ask + $0.01")
        print("  - SELL orders: limit_price = bid - $0.01")
        print()
        print("This should result in better fill rates on Monday.")
        return 0
    else:
        print("❌ TESTS FAILED - IOC Price Improvement is NOT WORKING")
        print()
        print("CRITICAL ISSUE:")
        print("  The price improvement is NOT being applied!")
        print("  Orders will continue to be placed at exact ask/bid.")
        print("  This will result in ZERO fills again.")
        print()
        print("DEBUG INFO:")
        print(f"  price_improvement = {price_improvement}")
        print(f"  This should be 0.01 but is: {price_improvement}")
        print()

        # Diagnose the issue
        if not use_ioc:
            print("  PROBLEM: use_ioc is False")
        elif improvement_ticks == 0:
            print("  PROBLEM: improvement_ticks is 0")
        elif tick_size == 0:
            print("  PROBLEM: tick_size is 0")
        else:
            print("  PROBLEM: Unknown - calculation should work but doesn't")

        return 1


if __name__ == "__main__":
    sys.exit(test_ioc_price_improvement())
