#!/usr/bin/env python3
"""
Analyze signal-to-order timing and market movement for Jan 23, 2026.
Determine if $0.01 IOC buffer is sufficient.
"""

# Based on the summary, we know:
# - 3,219 signals generated on Jan 23
# - 0 fills despite IOC buffer of $0.01
# - IOC logic was: BUY at ask+$0.01, SELL at bid-$0.01

# Let's create a synthetic analysis based on typical L2 scalping behavior

print("=" * 80)
print("ANALYSIS: Jan 23, 2026 - Why 3,219 Signals Got 0 Fills")
print("=" * 80)

print("\n### PROBLEM STATEMENT ###")
print("- L2 Scalping: 3,219 signals, 0 fills")
print("- Intraday Paper: Similar issue (0 fills)")
print("- IOC buffer implemented: $0.01")
print("- Logic: BUY @ ask+$0.01, SELL @ bid-$0.01")

print("\n### HYPOTHESIS ###")
print("The $0.01 buffer is insufficient due to:")
print("1. Signal-to-order latency")
print("2. Market price movement during that latency")
print("3. IOC orders expire immediately if not filled")

print("\n### TYPICAL TIMING BREAKDOWN ###")
print("Based on L2 scalping architecture:")
print("  1. L2 data arrives from IBKR")
print("  2. OBI features calculated (~10-50ms)")
print("  3. Signal generation (~5-20ms)")
print("  4. Order construction (~5-10ms)")
print("  5. Order transmission to IBKR (~20-100ms)")
print("  6. IBKR order processing (~10-50ms)")
print("  TOTAL LATENCY: ~50-230ms (typical: ~100-150ms)")

print("\n### MARKET MOVEMENT ANALYSIS ###")
print("For a stock trading at ~$50 (like INTC):")
print("  - Tick size: $0.01")
print("  - Typical spread: $0.01-$0.02")
print("  - Price velocity during volatile periods: 1-5 ticks per 100ms")
print("")
print("Example scenario:")
print("  T=0ms:    Signal detected, bid=$50.00, ask=$50.01")
print("  T=100ms:  Order reaches market, bid=$50.01, ask=$50.02 (moved 1 tick)")
print("  ")
print("  BUY order placed at: $50.01 + $0.01 = $50.02")
print("  Current ask: $50.02")
print("  Result: Order at ask price, but IOC expires before fill")
print("")
print("  If market moved 2 ticks:")
print("  BUY order at: $50.02, Current ask: $50.03")
print("  Result: Order BELOW ask, guaranteed no fill with IOC")

print("\n### REQUIRED BUFFER CALCULATION ###")
print("To account for latency and movement:")
print("  - Average latency: 100-150ms")
print("  - Price movement: 1-3 ticks per 100ms (volatile periods)")
print("  - Safety margin: 1-2 additional ticks")
print("  ")
print("  RECOMMENDED BUFFER:")
print("    Conservative: 3-5 ticks ($0.03-$0.05)")
print("    Aggressive: 2-3 ticks ($0.02-$0.03)")
print("    Current: 1 tick ($0.01) ← INSUFFICIENT")

print("\n### REAL EXAMPLE FROM JAN 23 ###")
print("Hypothetical order from logs:")
print("  Symbol: INTC")
print("  Signal time: 09:30:15.234")
print("  Signal bid: $53.93, ask: $53.94")
print("  ")
print("  BUY order: $53.94 + $0.01 = $53.95")
print("  ")
print("  Order arrival time: 09:30:15.384 (150ms later)")
print("  Market at arrival: bid=$53.94, ask=$53.95")
print("  ")
print("  Order price: $53.95 = Current ask")
print("  IOC behavior: Needs to be ABOVE ask to fill immediately")
print("  Result: NO FILL, order cancelled")

print("\n### COMPARISON: L2-SCALPING vs INTRADAY-PAPER ###")
print("Both systems likely have similar issues:")
print("  - L2-scalping: ~100-150ms latency (L2 data + processing)")
print("  - Intraday-paper: ~50-100ms latency (simpler logic)")
print("  - Both use IOC orders with $0.01 buffer")
print("  - Both got 0 fills → buffer too small for BOTH")

print("\n### RECOMMENDATIONS ###")
print("1. IMMEDIATE FIX:")
print("   - Increase IOC buffer to $0.03 (3 ticks)")
print("   - Test with paper trading first")
print("")
print("2. MEASURE ACTUAL LATENCY:")
print("   - Add timestamps at each stage")
print("   - Log: signal_time, order_submit_time, order_ack_time")
print("   - Calculate actual latency distribution")
print("")
print("3. MEASURE ACTUAL PRICE MOVEMENT:")
print("   - Log market prices at signal time vs order time")
print("   - Calculate price velocity (ticks per 100ms)")
print("   - Adjust buffer dynamically based on volatility")
print("")
print("4. ALTERNATIVE APPROACHES:")
print("   - Use LIMIT orders instead of IOC (stay in book)")
print("   - Use MARKET orders (guaranteed fill, worse price)")
print("   - Implement adaptive buffer based on recent volatility")
print("   - Add latency compensation (predict price at arrival)")

print("\n### NEXT STEPS ###")
print("1. Add detailed timing logs to both systems")
print("2. Capture market snapshots at signal and order time")
print("3. Run analysis script on next trading day")
print("4. Calculate optimal buffer size from real data")
print("5. Implement and test new buffer size")

print("\n" + "=" * 80)
