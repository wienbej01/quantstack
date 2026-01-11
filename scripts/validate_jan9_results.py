#!/usr/bin/env python3
"""
Validate January 9th trading results for data corruption and overnight positions.
"""

import json
import sqlite3
from datetime import datetime, timedelta

import pandas as pd


def check_jan9_trading_results():
    """Check Jan 9 results for corruption and overnight positions."""

    # Connect to trade database
    db_path = "/home/jacobw/intraday_stack/data/journal/events.db"
    conn = sqlite3.connect(db_path)


def check_jan9_trading_results():
    """Check Jan 9 results for corruption and overnight positions."""

    # Connect to trade database
    db_path = "/home/jacobw/intraday_stack/data/journal/events.db"
    conn = sqlite3.connect(db_path)

    print("=== JANUARY 9TH TRADING RESULTS VALIDATION ===\n")

    # Check schema of trades table
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(trades);")
    trades_columns = cursor.fetchall()
    print(f"Trades table columns: {[c[1] for c in trades_columns]}")

    # Check schema of fills table
    cursor.execute("PRAGMA table_info(fills);")
    fills_columns = cursor.fetchall()
    print(f"Fills table columns: {[c[1] for c in fills_columns]}")

    # Get sample data to understand structure
    cursor.execute("SELECT * FROM trades LIMIT 5;")
    sample_trades = cursor.fetchall()
    print(f"\nSample trades:")
    for row in sample_trades:
        print(row)

    cursor.execute("SELECT * FROM fills LIMIT 5;")
    sample_fills = cursor.fetchall()
    print(f"\nSample fills:")
    for row in sample_fills:
        print(row)

    # Try to find Jan 9 data with different date column names
    possible_date_cols = [
        "timestamp",
        "created_at",
        "trade_time",
        "fill_time",
        "event_time",
    ]

    jan9_trades = None
    for col in possible_date_cols:
        try:
            query = f"SELECT * FROM trades WHERE date({col}) = '2026-01-09'"
            jan9_trades = pd.read_sql_query(query, conn)
            print(
                f"\nFound Jan 9 trades using column '{col}': {len(jan9_trades)} records"
            )
            break
        except Exception as e:
            continue

    if jan9_trades is None or len(jan9_trades) == 0:
        # Try without date filter to see all data
        all_trades = pd.read_sql_query("SELECT * FROM trades", conn)
        print(f"\nTotal trades in database: {len(all_trades)}")
        if len(all_trades) > 0:
            print("Sample of all trades:")
            print(all_trades.head())

            # Check date range
            for col in all_trades.columns:
                if "time" in col.lower() or "date" in col.lower():
                    print(f"Date column '{col}' range:")
                    print(f"  Min: {all_trades[col].min()}")
                    print(f"  Max: {all_trades[col].max()}")

    conn.close()
    return {}


if __name__ == "__main__":
    results = check_jan9_trading_results()

    print(f"\n=== RELIABILITY ASSESSMENT ===")

    corruption_score = 0
    if results["suspicious_prices"] > 0:
        corruption_score += 2
    if results["zero_pnl_trades"] > 0:
        corruption_score += 3
    if results["after_hours_trades"] > 0:
        corruption_score += 1
    if results["sync_trades"] > results["total_trades"] * 0.5:
        corruption_score += 2

    if corruption_score == 0:
        print("✅ L2 scalping results appear RELIABLE")
    elif corruption_score <= 2:
        print("⚠️  L2 scalping results have MINOR issues")
    else:
        print("❌ L2 scalping results are CORRUPTED")

    print(f"Corruption score: {corruption_score}/8")
