#!/usr/bin/env python3

# Fix for the formatting error: "Cannot specify ',' with 's'"
# The issue is using both comma separator and 's' format specifier

# WRONG: f"{value:,s}"
# RIGHT: f"{value:,}" or f"{value:s}"

# Example fixes:
print("=== POSITION SIZING ANALYSIS ===")
shares_range = (100, 9999889755)
print(f"Shares range: {shares_range[0]:,} to {shares_range[1]:,}")

entry_price = 100.0
print(f"Entry price: [{entry_price}]")

exit_price_range = (88.41, 133.06)
print(f"Exit price range: {exit_price_range[0]} to {exit_price_range[1]}")

print("\n=== EXTREME TRADE EXAMPLES ===")
symbol = "EXPE"
side = "LONG"
print(f"Symbol: {symbol}, Side: {side}")

# If you need to format numbers with commas, use:
extreme_trades = 22476
total_trades = 37694
percentage = 59.6

print(f"Extreme trades: {extreme_trades:,} ({percentage}%)")
print(f"Total trades: {total_trades:,}")

# For large numbers:
large_shares = 9999889755
print(f"Large position: {large_shares:,} shares")
