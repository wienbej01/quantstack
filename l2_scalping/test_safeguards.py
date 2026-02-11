#!/usr/bin/env python3
"""Test script to verify overnight position safeguards."""

import sys
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path

import pytz

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from scheduler import MarketScheduler


def test_entry_curfew():
    """Test entry curfew logic."""
    print("=" * 60)
    print("TESTING ENTRY CURFEW")
    print("=" * 60)

    config = {"schedule": {"auto_start": False}}
    scheduler = MarketScheduler(config)

    # Test scenarios
    max_hold_seconds = 600  # 10 minutes

    # Get current ET time
    et_now = scheduler.get_et_time()
    print(f"\nCurrent ET time: {et_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Market close: {scheduler.market_close}")
    print(f"Max hold time: {max_hold_seconds}s ({max_hold_seconds/60:.1f} min)")

    # Test can_open_new_position
    can_open, reason = scheduler.can_open_new_position(max_hold_seconds)
    print(f"\nCan open new position: {can_open}")
    print(f"Reason: {reason}")

    # Calculate curfew time
    market_close_dt = et_now.replace(
        hour=scheduler.market_close.hour,
        minute=scheduler.market_close.minute,
        second=0,
        microsecond=0,
    )
    seconds_until_close = (market_close_dt - et_now).total_seconds()
    buffer_seconds = 60
    required_seconds = max_hold_seconds + buffer_seconds
    curfew_time = market_close_dt.replace(
        hour=15, minute=49, second=0
    )  # 16:00 - 11 min

    print(f"\nSeconds until close: {seconds_until_close:.0f}s")
    print(f"Required seconds: {required_seconds}s")
    print(f"Entry curfew time: {curfew_time.strftime('%H:%M:%S')} ET")

    if seconds_until_close < required_seconds:
        print("\n⚠️  ENTRY BLOCKED - Too close to market close")
    else:
        print("\n✅ ENTRY ALLOWED - Sufficient time remaining")

    print("\n" + "=" * 60)


def test_bracket_order_prices():
    """Test bracket order price calculations."""
    print("\nTESTING BRACKET ORDER PRICES")
    print("=" * 60)

    # Risk config
    max_loss_bps = 10
    profit_target_bps = 15

    # Test LONG entry
    entry_price = 100.00
    print(f"\nLONG Entry @ ${entry_price:.2f}")
    stop_loss = entry_price * (1 - max_loss_bps / 10000)
    profit_target = entry_price * (1 + profit_target_bps / 10000)
    print(f"  Stop Loss: ${stop_loss:.4f} ({max_loss_bps} bps)")
    print(f"  Profit Target: ${profit_target:.4f} ({profit_target_bps} bps)")

    # Test SHORT entry
    print(f"\nSHORT Entry @ ${entry_price:.2f}")
    stop_loss = entry_price * (1 + max_loss_bps / 10000)
    profit_target = entry_price * (1 - profit_target_bps / 10000)
    print(f"  Stop Loss: ${stop_loss:.4f} ({max_loss_bps} bps)")
    print(f"  Profit Target: ${profit_target:.4f} ({profit_target_bps} bps)")

    print("\n" + "=" * 60)


def test_exit_priority():
    """Test exit priority logic."""
    print("\nTESTING EXIT PRIORITY LOGIC")
    print("=" * 60)

    import time

    # Simulate position
    entry_time = time.time()
    default_hold = 300  # 5 min
    max_hold = 600  # 10 min

    print(f"\nDefault hold time: {default_hold}s ({default_hold/60:.1f} min)")
    print(f"Max hold time: {max_hold}s ({max_hold/60:.1f} min)")

    # Test scenarios
    scenarios = [
        (650, 5, "Max hold exceeded"),  # 650s hold, 5 bps profit
        (350, 20, "Profit target hit"),  # 350s hold, 20 bps profit
        (200, -15, "Stop loss hit"),  # 200s hold, -15 bps loss
        (310, 5, "Scheduled exit"),  # 310s hold, 5 bps profit
    ]

    for hold_time, pnl_bps, expected in scenarios:
        current_time = entry_time + hold_time
        scheduled_exit = entry_time + default_hold

        # Check conditions
        if hold_time >= max_hold:
            result = "FORCE EXIT (market order)"
            priority = 1
        elif current_time >= scheduled_exit:
            result = "Scheduled exit"
            priority = 2
        elif pnl_bps >= 15:
            result = "Profit target"
            priority = 3
        elif pnl_bps <= -10:
            result = "Stop loss"
            priority = 4
        else:
            result = "Hold"
            priority = 5

        print(f"\nScenario: {expected}")
        print(f"  Hold time: {hold_time}s, P&L: {pnl_bps:+.1f} bps")
        print(f"  Result: {result} (priority {priority})")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    test_entry_curfew()
    test_bracket_order_prices()
    test_exit_priority()
    print("\n✅ All tests completed")
