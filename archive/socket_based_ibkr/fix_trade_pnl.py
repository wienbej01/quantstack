#!/usr/bin/env python3
"""
Fix Trade P&L - Update existing trades with actual P&L calculation

This script fixes the $0.00 P&L issue by:
1. Getting actual fill prices from IBKR Gateway
2. Recalculating P&L for existing trades
3. Updating the database with correct values
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import ib_insync as ib

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from journal.event_store import EventStore


def fix_trade_pnl(db_path: str = "/home/jacobw/intraday_stack/data/journal/events.db"):
    """Fix P&L for trades with $0.00 values."""

    # Connect to IBKR Gateway to get actual execution data
    try:
        ib_client = ib.IB()
        ib_client.connect("127.0.0.1", 7497, clientId=999)
        print("Connected to IBKR Gateway")

        # Get executions from today
        executions = ib_client.executions()
        print(f"Found {len(executions)} executions from IBKR")

        # Group executions by symbol and time
        exec_by_symbol = {}
        for exec_detail in executions:
            symbol = exec_detail.contract.symbol
            if symbol not in exec_by_symbol:
                exec_by_symbol[symbol] = []
            exec_by_symbol[symbol].append(
                {
                    "time": exec_detail.time,
                    "side": exec_detail.side,
                    "shares": exec_detail.shares,
                    "price": exec_detail.price,
                    "commission": exec_detail.commission or 0.0,
                    "realized_pnl": exec_detail.realizedPNL or 0.0,
                }
            )

        ib_client.disconnect()

    except Exception as e:
        print(f"Could not connect to IBKR Gateway: {e}")
        exec_by_symbol = {}

    # Fix database trades
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get trades with $0.00 P&L from Jan 9
    cursor.execute(
        """
        SELECT * FROM trades 
        WHERE DATE(entry_time) = '2026-01-09' 
        AND (net_pnl = 0.0 OR net_pnl IS NULL)
        AND status = 'CLOSED'
    """
    )

    zero_pnl_trades = cursor.fetchall()
    print(f"Found {len(zero_pnl_trades)} trades with $0.00 P&L")

    fixed_count = 0
    for trade in zero_pnl_trades:
        trade_dict = dict(trade)
        symbol = trade_dict["symbol"]
        direction = trade_dict["direction"]
        entry_price = trade_dict["entry_price"]
        exit_price = trade_dict["exit_price"]
        entry_qty = trade_dict["entry_qty"]

        # Skip if we already have different entry/exit prices
        if entry_price != exit_price:
            continue

        # Try to get actual prices from IBKR executions
        actual_exit_price = exit_price  # Default fallback

        if symbol in exec_by_symbol:
            symbol_execs = exec_by_symbol[symbol]
            # Find exit execution (opposite side)
            exit_side = "SLD" if direction == "long" else "BOT"
            exit_execs = [e for e in symbol_execs if e["side"] == exit_side]

            if exit_execs:
                # Use most recent exit execution
                latest_exit = max(exit_execs, key=lambda x: x["time"])
                actual_exit_price = latest_exit["price"]
                print(f"Found actual exit price for {symbol}: {actual_exit_price:.4f}")

        # Recalculate P&L with actual prices
        if direction == "long":
            gross_pnl = (actual_exit_price - entry_price) * entry_qty
        else:
            gross_pnl = (entry_price - actual_exit_price) * entry_qty

        commission = trade_dict.get("commission", 0.0)
        net_pnl = gross_pnl - commission

        # Update the trade
        cursor.execute(
            """
            UPDATE trades SET 
                exit_price = ?, 
                gross_pnl = ?, 
                net_pnl = ?
            WHERE trade_id = ?
        """,
            (actual_exit_price, gross_pnl, net_pnl, trade_dict["trade_id"]),
        )

        print(
            f"Fixed {symbol}: entry@{entry_price:.4f} exit@{actual_exit_price:.4f} = ${net_pnl:.2f}"
        )
        fixed_count += 1

    conn.commit()
    conn.close()

    print(f"Fixed {fixed_count} trades")
    return fixed_count


if __name__ == "__main__":
    fixed = fix_trade_pnl()
    print(f"Trade P&L fix complete. Updated {fixed} trades.")
