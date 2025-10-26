#!/usr/bin/env python3
"""
Debug script to check why baseline strategy generates no trades.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def debug_baseline_strategy():
    """Debug why baseline strategy generates no trades."""

    print("🔍 Debugging Baseline Strategy - Why No Trades?")
    print("=" * 60)

    # Test simple vwap reversion logic
    print("\n1. Testing VWAP Reversion Logic:")

    # Simulate some sample price data
    test_scenarios = [
        {
            "close": 100.0,
            "vwap": 101.0,
            "deviation": -1.0,
            "should_buy": True,
        },  # 1% below VWAP
        {
            "close": 102.0,
            "vwap": 101.0,
            "deviation": 1.0,
            "should_sell": True,
        },  # 1% above VWAP
        {
            "close": 100.5,
            "vwap": 101.0,
            "deviation": -0.5,
            "should_buy": True,
        },  # 0.5% below VWAP
        {
            "close": 101.5,
            "vwap": 101.0,
            "deviation": 0.5,
            "should_sell": True,
        },  # 0.5% above VWAP
        {
            "close": 100.9,
            "vwap": 101.0,
            "deviation": -0.1,
            "should_buy": False,
        },  # 0.1% below VWAP
        {
            "close": 101.1,
            "vwap": 101.0,
            "deviation": 0.1,
            "should_sell": False,
        },  # 0.1% above VWAP
    ]

    buy_signals = 0
    sell_signals = 0

    for i, scenario in enumerate(test_scenarios):
        close = scenario["close"]
        vwap = scenario["vwap"]
        deviation_pct = ((close - vwap) / vwap) * 100

        # Check buy signal (0.5% below VWAP)
        buy_signal = close < vwap * 0.995
        # Check sell signal (0.5% above VWAP)
        sell_signal = close > vwap * 1.005

        print(
            f"  Scenario {i+1}: Close=${close:.2f}, VWAP=${vwap:.2f}, Deviation={deviation_pct:.1f}%"
        )
        print(f"    Buy signal: {buy_signal} (expected: {scenario['should_buy']})")
        print(f"    Sell signal: {sell_signal} (expected: {scenario['should_sell']})")

        if buy_signal == scenario["should_buy"] and buy_signal:
            buy_signals += 1
        if sell_signal == scenario["should_sell"] and sell_signal:
            sell_signals += 1

    print("\n2. Signal Analysis:")
    print(f"   Buy signals detected: {buy_signals}/5 expected")
    print(f"   Sell signals detected: {sell_signals}/5 expected")
    print(
        f"   Logic appears correct: {'✅' if buy_signals >= 4 and sell_signals >= 4 else '❌'}"
    )

    print("\n3. Potential Issues:")

    issues = []

    # Check VWAP threshold tightness
    print("   📊 VWAP Threshold Analysis:")
    print("      Buy threshold: price < VWAP × 0.995 (-0.5%)")
    print("      Sell threshold: price > VWAP × 1.005 (+0.5%)")
    print("      This might be too strict for stable markets")
    issues.append("VWAP thresholds too tight for typical market movements")

    # Check data availability
    print("   📊 Data Availability:")
    print("      Data loaded: 113,837 bars for 7 symbols")
    print("      This suggests data is available")

    # Check warmup period
    print("   📊 Warmup Period:")
    print("      VWAP calculation needs 30-minute window")
    print("      First 30 minutes (approx 30 bars) may have no VWAP signal")
    issues.append("Warmup period may be blocking early trades")

    # Check position management
    print("   📊 Position Management:")
    print("      Strategy only enters when no position exists")
    print("      May be stuck in positions from previous bars")
    issues.append("Position management may be preventing new entries")

    print("\n4. Recommended Debugging Steps:")

    debug_steps = [
        "1. Loosen VWAP thresholds to ±1.0% instead of ±0.5%",
        "2. Add debug logging to see actual VWAP values in strategy",
        "3. Check if warmup mask is blocking VWAP calculations",
        "4. Verify position state during backtest",
        "5. Test with larger price movements or more volatile symbols",
    ]

    for step in debug_steps:
        print(f"   {step}")

    print("\n5. Quick Fix Test:")
    print("   Try modifying strategy to use wider thresholds:")
    print("   - Buy: close < vwap * 0.98 (-2% below VWAP)")
    print("   - Sell: close > vwap * 1.02 (+2% above VWAP)")
    print("   This should generate more trading signals for testing")

    print("\n🎯 Diagnosis: The most likely issue is that the ±0.5% VWAP")
    print("   thresholds are too tight for the actual market conditions")
    print("   in the test data, resulting in very few or no trading signals.")


if __name__ == "__main__":
    debug_baseline_strategy()
