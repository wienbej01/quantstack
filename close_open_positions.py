#!/usr/bin/env python3
"""
Close Open Positions - Manual cleanup script

Closes the 2 open INSM positions from Jan 9
"""

import sqlite3
import sys
from pathlib import Path

# Add intraday_stack to path
sys.path.insert(0, str(Path(__file__).parent.parent / "intraday_stack" / "src"))

from journal.event_store import EventStore


def close_open_positions():
    """Close all open positions in database."""

    db_path = "/home/jacobw/intraday_stack/data/journal/events.db"
    event_store = EventStore(db_path)

    # Get open trades
    open_trades = event_store.get_open_trades()

    if not open_trades:
        print("No open positions to close")
        return

    print(f"Found {len(open_trades)} open positions:")
    for trade in open_trades:
        print(
            f"  {trade['trade_id']} | {trade['symbol']} | {trade['system']} | entry@{trade['entry_price']}"
        )

    # Close each position
    for trade in open_trades:
        # Use entry price as exit (we don't have current market price)
        exit_price = trade["entry_price"]

        print(f"\nClosing {trade['symbol']} (trade_id={trade['trade_id']})")

        event_store.close_trade(
            trade_id=trade["trade_id"],
            exit_order_id=0,
            exit_price=exit_price,
            exit_qty=trade["entry_qty"],
            exit_reason="MANUAL_CLOSE",
            commission=0.0,
        )

        print(f"  ✓ Closed at {exit_price:.4f}")

    print(f"\n✓ Closed {len(open_trades)} positions")


if __name__ == "__main__":
    close_open_positions()
