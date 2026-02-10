#!/usr/bin/env python3
"""Fix L2 Trade Recording Issue

The L2 scalping system is calling record_fill() but NOT calling open_trade()
or record_trade_entry(), so trades never get written to the PostgreSQL database.

This script analyzes the issue and provides a fix.
"""

import re
from pathlib import Path

# Issue: L2 main.py calls record_fill() but never calls open_trade() or record_trade_entry()
# The fills are recorded but trades are never opened in the database

print("=" * 80)
print("L2 TRADE RECORDING ISSUE ANALYSIS")
print("=" * 80)

print("\n## PROBLEM:")
print("- L2 system records fills via record_fill()")
print("- But NEVER calls open_trade() or record_trade_entry()")
print("- Result: Fills exist but no trade records in PostgreSQL")
print("- 3,591 fills on Jan 29 but 0 trades in database")

print("\n## ROOT CAUSE:")
print("- L2 main.py uses legacy fill handler")
print("- Legacy handler only calls record_fill()")
print("- Never calls trade_journal.record_trade_entry()")

print("\n## FIX:")
print("- Modify _legacy_fill_handler() to call record_trade_entry() on entry fills")
print("- Modify _legacy_fill_handler() to call record_trade_exit() on exit fills")

# Check current implementation
main_py = Path("/home/jacobw/quantstack/l2_scalping/src/main.py")
content = main_py.read_text()

# Find _legacy_fill_handler
match = re.search(r'def _legacy_fill_handler\(self.*?\n(?=    def |\Z)', content, re.DOTALL)
if match:
    print("\n## CURRENT _legacy_fill_handler():")
    lines = match.group(0).split('\n')[:30]
    for line in lines:
        print(f"  {line}")

print("\n## REQUIRED CHANGES:")
print("""
1. In _legacy_fill_handler(), after recording fill:
   - Check if this is an ENTRY fill (opening position)
   - If yes, call: trade_journal.record_trade_entry(
       symbol=symbol,
       side=side,
       quantity=filled_qty,
       entry_price=fill_price,
       order_id=order_id,
       rule_name=<extract from order_ref>,
       signal_id=<generate>,
       signal_price=fill_price
   )
   
2. When position is closed:
   - Call: trade_journal.record_trade_exit(
       trade_id=<from entry>,
       exit_price=exit_price,
       exit_qty=exit_qty,
       exit_reason=<reason>,
       order_id=exit_order_id
   )
""")

print("\n" + "=" * 80)
print("Run this to apply the fix:")
print("  python ~/quantstack/scripts/apply_l2_trade_fix.py")
print("=" * 80)
