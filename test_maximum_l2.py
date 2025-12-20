#!/usr/bin/env python3
"""Test maximum L2 collection configuration."""

import sys
from pathlib import Path

# Add paths
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root / "qx-data" / "src"))
sys.path.insert(0, str(repo_root / "scripts"))

from datetime import datetime

from scripts.daily_sip_scheduler import load_daily_sip_results, run_daily_sip_selection
from scripts.l2_symbol_selector import get_l2_symbols, log_symbol_selection


def test_maximum_l2_setup():
    """Test the maximum L2 collection setup."""

    print("=== TESTING MAXIMUM L2 COLLECTION SETUP ===\n")

    # 1. Test daily SIP generation with 50 L2 symbols
    print("1. Testing daily SIP generation...")
    try:
        sip_universe, l2_symbols = run_daily_sip_selection()
        print(f"   ✓ Generated {len(sip_universe)} SIP symbols")
        print(f"   ✓ Generated {len(l2_symbols)} L2 symbols")
        print(
            f"   ✓ L2 symbols: {l2_symbols[:10]}..."
            if len(l2_symbols) > 10
            else f"   ✓ L2 symbols: {l2_symbols}"
        )
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

    # 2. Test L2 symbol selector with maximum configuration
    print("\n2. Testing L2 symbol selector...")
    try:
        selected_symbols = get_l2_symbols(sip_universe)
        print(f"   ✓ Selected {len(selected_symbols)} symbols for L2 collection")
        print(f"   ✓ Core symbols: {selected_symbols[:10]}")
        print(f"   ✓ Rotating symbols: {len(selected_symbols[10:])} symbols")

        # Log the selection
        selection = log_symbol_selection(selected_symbols, sip_universe)
        print(
            f"   ✓ Logged selection to: data/l2_selection_log/{selection['date']}.json"
        )
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

    # 3. Test configuration loading
    print("\n3. Testing configuration files...")

    # Check dual_system config
    dual_config = Path("qx-l2/configs/dual_system.yaml")
    if dual_config.exists():
        print(f"   ✓ Found dual_system config: {dual_config}")
    else:
        print(f"   ✗ Missing dual_system config: {dual_config}")

    # Check maximum config
    max_config = Path("qx-l2/configs/maximum_l2.yaml")
    if max_config.exists():
        print(f"   ✓ Found maximum L2 config: {max_config}")
    else:
        print(f"   ✗ Missing maximum L2 config: {max_config}")

    # 4. Calculate expected data collection improvement
    print("\n4. Data collection improvement calculation...")

    # Previous: 12 symbols, 2 hours/day, 1/second
    previous_rate = 12 * 2 * 3600  # symbols * hours * seconds

    # Maximum: 50 symbols, 6 hours/day, 2/second
    maximum_rate = 50 * 6 * 3600 * 2  # symbols * hours * seconds * frequency

    improvement = maximum_rate / previous_rate

    print(f"   Previous collection rate: {previous_rate:,} records/day")
    print(f"   Maximum collection rate: {maximum_rate:,} records/day")
    print(f"   Improvement factor: {improvement:.1f}x")

    # Timeline calculation
    target_records = 200_000
    current_records = 3_128
    needed_records = target_records - current_records

    days_at_previous_rate = needed_records / previous_rate
    days_at_maximum_rate = needed_records / maximum_rate

    print(f"\n   Time to reach 200k records:")
    print(
        f"   - Previous rate: {days_at_previous_rate:.0f} days ({days_at_previous_rate/30:.1f} months)"
    )
    print(
        f"   - Maximum rate: {days_at_maximum_rate:.0f} days ({days_at_maximum_rate/30:.1f} months)"
    )

    # 5. API usage check
    print("\n5. API usage validation...")
    trading_symbols = 40
    l2_symbols_count = len(selected_symbols)
    total_usage = trading_symbols + l2_symbols_count
    api_limit = 100

    print(f"   Trading symbols: {trading_symbols}")
    print(f"   L2 symbols: {l2_symbols_count}")
    print(f"   Total API usage: {total_usage}/100 lines")
    print(f"   Remaining capacity: {api_limit - total_usage} lines")

    if total_usage <= api_limit:
        print(f"   ✓ Within API limits")
    else:
        print(f"   ✗ Exceeds API limits by {total_usage - api_limit} lines")
        return False

    print("\n=== MAXIMUM L2 SETUP TEST COMPLETE ===")
    print("✓ All tests passed - ready for maximum L2 data collection")

    return True


if __name__ == "__main__":
    success = test_maximum_l2_setup()
    sys.exit(0 if success else 1)
