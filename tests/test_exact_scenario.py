#!/usr/bin/env python3
"""
CRITICAL TEST: Reproduce yesterday's exact scenario
Based on actual log: TRADE [high_obi_depth]: NVDA BUY 5@187.3900
"""


# Simulate the EXACT code path from main.py line 688-710
def test_exact_code_path():
    print("=" * 70)
    print("REPRODUCING YESTERDAY'S EXACT SCENARIO")
    print("=" * 70)
    print()

    # Config values (from ibkr.yaml)
    config = {
        "ibkr": {
            "orders": {
                "use_ioc_for_scalping": True,
                "ioc_price_improvement_ticks": 1,
                "tick_size": 0.01,
            }
        },
        "risk": {"per_trade": {"max_loss_bps": 10, "profit_target_bps": 15}},
    }

    # Market data from yesterday's log
    class MockSnapshot:
        symbol = "NVDA"
        ask = 187.39
        bid = 187.38

    snapshot = MockSnapshot()

    # EXACT code from main.py lines 688-710
    use_ioc = config["ibkr"]["orders"]["use_ioc_for_scalping"]
    improvement_ticks = config["ibkr"]["orders"].get("ioc_price_improvement_ticks", 0)
    tick_size = config["ibkr"]["orders"].get("tick_size", 0.01)
    price_improvement = improvement_ticks * tick_size if use_ioc else 0.0

    print("CONFIG:")
    print(f"  use_ioc: {use_ioc}")
    print(f"  improvement_ticks: {improvement_ticks}")
    print(f"  tick_size: {tick_size}")
    print(f"  price_improvement: {price_improvement}")
    print()

    # BUY order (direction > 0) - CORRECTED LOGIC
    side = "BUY"
    limit_price = snapshot.ask - price_improvement  # Buy BELOW ask to cross spread
    max_loss_bps = config["risk"]["per_trade"]["max_loss_bps"]
    profit_target_bps = config["risk"]["per_trade"]["profit_target_bps"]
    stop_loss_price = limit_price * (1 - max_loss_bps / 10000)
    profit_target_price = limit_price * (1 + profit_target_bps / 10000)

    print("CALCULATED PRICES:")
    print(f"  snapshot.ask: {snapshot.ask}")
    print(f"  price_improvement: {price_improvement}")
    print(f"  limit_price: {limit_price:.4f}")
    print(f"  stop_loss_price: {stop_loss_price:.4f}")
    print(f"  profit_target_price: {profit_target_price:.4f}")
    print()

    # What the TRADE log would show
    trade_log = f"TRADE [high_obi_depth]: {snapshot.symbol} {side} 5@{limit_price:.4f} [stop={stop_loss_price:.4f}, target={profit_target_price:.4f}]"
    print("TRADE LOG:")
    print(f"  {trade_log}")
    print()

    # Compare with yesterday's actual log
    yesterday_log = (
        "TRADE [high_obi_depth]: NVDA BUY 5@187.3900 [stop=187.2026, target=187.6711]"
    )
    print("YESTERDAY'S ACTUAL LOG:")
    print(f"  {yesterday_log}")
    print()

    # Check if they match
    if abs(limit_price - 187.39) < 0.0001:
        print("❌ PROBLEM: limit_price = 187.39 (NO IMPROVEMENT)")
        print("   This means price_improvement = 0")
        print()
        print("   Possible causes:")
        print("   1. use_ioc was False")
        print("   2. improvement_ticks was 0")
        print("   3. tick_size was 0")
        print("   4. Config wasn't loaded correctly")
        return 1
    elif abs(limit_price - 187.40) < 0.0001:
        print("✅ SUCCESS: limit_price = 187.40 (IMPROVEMENT APPLIED)")
        print("   But yesterday's log shows 187.39!")
        print()
        print("   This means:")
        print("   1. The code is correct NOW")
        print("   2. But something was different YESTERDAY")
        print("   3. Either config wasn't loaded, or code was different")
        return 0
    else:
        print(f"⚠️  UNEXPECTED: limit_price = {limit_price:.4f}")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(test_exact_code_path())
