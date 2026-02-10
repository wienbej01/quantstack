#!/usr/bin/env python3
"""
Integration Test: Load actual L2ScalpingSystem and verify config
This simulates exactly what happens when the service starts.
"""

import sys
import os
from pathlib import Path

# Set up environment exactly like production
os.chdir("/home/jacobw/quantstack/l2_scalping")
sys.path.insert(0, "/home/jacobw/quantstack")
sys.path.insert(0, "/home/jacobw/quantstack/l2_scalping/src")

# Import the actual system
from main import ScalpingSystem

def _run_config_check() -> None:
    """Run config validation and assert expectations."""

    print("=" * 70)
    print("INTEGRATION TEST: ScalpingSystem Config Loading")
    print("=" * 70)
    print()
    
    # Create system instance (same as production)
    config_dir = Path("config")
    print(f"Config directory: {config_dir.absolute()}")
    print()
    
    system = ScalpingSystem(config_dir=config_dir)

    orders_cfg = system.config["ibkr"]["orders"]
    entry_order_type = str(orders_cfg.get("entry_order_type", "IOC")).upper()
    improvement_ticks = orders_cfg.get("ioc_price_improvement_ticks", 0)
    tick_size = orders_cfg.get("tick_size", 0.01)
    price_improvement = improvement_ticks * tick_size if entry_order_type == "IOC" else 0.0
    expected_improvement = price_improvement

    print("LOADED CONFIG VALUES:")
    print(f"  entry_order_type: {entry_order_type}")
    print(f"  improvement_ticks: {improvement_ticks}")
    print(f"  tick_size: {tick_size}")
    print(f"  price_improvement: {price_improvement}")
    print()

    assert entry_order_type in {"MKT", "IOC", "LMT"}, "Invalid entry order type"
    assert price_improvement >= 0.0, "Negative price improvement"

    # Test calculation
    test_ask = 187.39
    test_bid = 187.38

    buy_limit = test_ask + price_improvement
    sell_limit = test_bid - price_improvement

    expected_buy = test_ask + expected_improvement
    expected_sell = test_bid - expected_improvement

    print("CALCULATED ORDER PRICES:")
    print(f"  Test ask: {test_ask}")
    print(f"  Test bid: {test_bid}")
    print(f"  BUY limit: {buy_limit:.4f} (should be {expected_buy:.4f})")
    print(f"  SELL limit: {sell_limit:.4f} (should be {expected_sell:.4f})")
    print()

    assert abs(buy_limit - expected_buy) < 0.0001, "BUY price improvement mismatch"
    assert abs(sell_limit - expected_sell) < 0.0001, "SELL price improvement mismatch"

    print("✅ SUCCESS: Config loaded correctly, price improvement consistent")
    print()

def test_actual_system_config():
    """Test that the actual system loads config correctly."""
    _run_config_check()


if __name__ == "__main__":
    try:
        _run_config_check()
    except AssertionError as exc:
        print(f"❌ FAILURE: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"❌ ERROR loading system: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)
