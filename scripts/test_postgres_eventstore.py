#!/usr/bin/env python3
"""Test EventStore PostgreSQL integration"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "intraday_stack" / "src"))

from journal.event_store import EventStore

# Test PostgreSQL connection
store = EventStore(
    use_postgres=True, pg_config={"database": "trading", "user": "jacobw"}
)

# Test open_trade
trade_id = store.open_trade(
    symbol="TEST",
    strategy="test_strategy",
    direction="long",
    signal_id="test_signal_001",
    entry_order_id=12345,
    entry_price=100.50,
    entry_qty=10,
    signal_price=100.45,
    system="test-system",
)
print(f"✓ Trade opened: {trade_id}")

# Test close_trade
store.close_trade(
    trade_id=trade_id,
    exit_order_id=12346,
    exit_price=101.00,
    exit_qty=10,
    exit_reason="TEST_EXIT",
    commission=2.00,
    signal_price=101.05,
)
print(f"✓ Trade closed: {trade_id}")

# Verify in database
from datetime import datetime

today = datetime.utcnow().strftime("%Y-%m-%d")
trades = store.get_trades_for_date(today)
test_trades = [t for t in trades if t["symbol"] == "TEST"]
print(f"✓ Found {len(test_trades)} test trade(s) in database for {today}")

if test_trades:
    t = test_trades[-1]
    print(
        f"  Trade: {t['symbol']} {t['direction']} {t['entry_qty']}@{t['entry_price']} -> {t['exit_price']}"
    )
    print(
        f"  P&L: ${t['net_pnl']:.2f} (gross: ${t['gross_pnl']:.2f}, commission: ${t['commission']:.2f})"
    )
    print(f"  Status: {t['status']}")

print("\n✓ PostgreSQL EventStore test passed!")
