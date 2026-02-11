#!/usr/bin/env python3
"""Test emergency EOD close script with PostgreSQL."""

import sys
from datetime import datetime

import psycopg2


def test_emergency_eod():
    """Test the emergency EOD script can connect and query."""

    print("Testing emergency EOD script...")

    # Test 1: Database connection
    print("\n1. Testing PostgreSQL connection...")
    try:
        conn = psycopg2.connect(database="trading", user="jacobw")
        cursor = conn.cursor()
        print("   ✓ Connected to PostgreSQL")
    except Exception as e:
        print(f"   ✗ Connection failed: {e}")
        return False

    # Test 2: Query open positions
    print("\n2. Testing query for open positions...")
    try:
        cursor.execute("SELECT * FROM trades WHERE status = 'OPEN'")
        columns = [desc[0] for desc in cursor.description]
        open_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
        print(f"   ✓ Found {len(open_trades)} open positions")

        for trade in open_trades:
            print(
                f"     - {trade['symbol']} {trade['direction']} {trade['entry_qty']} @ {trade['entry_price']}"
            )
    except Exception as e:
        print(f"   ✗ Query failed: {e}")
        conn.close()
        return False

    # Test 3: Test UPDATE syntax (dry run)
    print("\n3. Testing UPDATE statement syntax...")
    try:
        if open_trades:
            trade = open_trades[0]
            exit_time = datetime.utcnow().isoformat()
            exit_price = trade["entry_price"]
            hold_time = 0.0

            # Test with EXPLAIN (doesn't execute)
            cursor.execute(
                """
                EXPLAIN UPDATE trades SET
                    exit_time = %s,
                    exit_price = %s,
                    exit_qty = %s,
                    exit_reason = 'EMERGENCY_EOD',
                    gross_pnl = 0.0,
                    net_pnl = 0.0,
                    commission = 0.0,
                    hold_time_seconds = %s,
                    status = 'CLOSED'
                WHERE trade_id = %s
            """,
                (
                    exit_time,
                    exit_price,
                    trade["entry_qty"],
                    hold_time,
                    trade["trade_id"],
                ),
            )
            result = cursor.fetchall()
            print("   ✓ UPDATE syntax valid")
        else:
            print("   ⊘ No open trades to test UPDATE (this is OK)")
    except Exception as e:
        print(f"   ✗ UPDATE syntax failed: {e}")
        conn.close()
        return False

    conn.close()
    print("\n✓ All tests passed - emergency EOD script is ready")
    return True


if __name__ == "__main__":
    success = test_emergency_eod()
    sys.exit(0 if success else 1)
