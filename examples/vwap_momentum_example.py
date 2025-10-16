#!/usr/bin/env python3
"""
Quick example demonstrating VWAP momentum policy usage.

This example shows how to create and use the VWAP momentum breakout strategy.
"""

from qx_backtest.policies import VwapMomentumPolicy, VwapMomentumPolicyEnhanced


def main() -> None:
    """Demonstrate VWAP momentum policy usage."""

    print("VWAP Momentum Breakout Strategy Example")
    print("=" * 50)

    # Basic momentum policy
    print("\n1. Basic Momentum Policy:")
    basic_policy = VwapMomentumPolicy(
        vwap_window=30,
        min_rvol=1.2,
        min_breakout_strength=0.8,
        position_size_pct=0.15,
        max_positions=3,
    )
    print(f"   Policy name: {basic_policy.name}")
    print(f"   VWAP window: {basic_policy.vwap_window}")
    print(f"   Breakout threshold: {basic_policy.min_breakout_strength}%")

    # Enhanced momentum policy
    print("\n2. Enhanced Momentum Policy:")
    enhanced_policy = VwapMomentumPolicyEnhanced(
        vwap_window=30,
        min_rvol=1.2,
        min_breakout_strength=0.8,
        atr_window=14,
        atr_multiplier=2.0,
        min_profit_atr=1.0,
        position_size_pct=0.15,
        max_positions=3,
    )
    print(f"   Policy name: {enhanced_policy.name}")
    print(f"   ATR window: {enhanced_policy.atr_window}")
    print(f"   ATR multiplier: {enhanced_policy.atr_multiplier}")
    print(f"   Profit target: {enhanced_policy.min_profit_atr} ATR")

    # Configuration example
    print("\n3. Configuration Example:")
    config = {
        "policy": {
            "type": "VwapMomentum",
            "params": {
                "vwap_window": 25,
                "min_rvol": 1.5,
                "min_breakout_strength": 0.7,
                "max_position_bars": 40,
                "position_size_pct": 0.2,
                "max_positions": 4,
            },
        }
    }
    print(f"   Policy type: {config['policy']['type']}")
    print(f"   Parameters: {len(config['policy']['params'])} settings")

    print("\n✅ Example completed successfully!")
    print("\nFor detailed documentation, see: docs/vwap_momentum_guide.md")
    print("For experiment configurations, see: experiments/vwap_momentum_test/")


if __name__ == "__main__":
    main()
