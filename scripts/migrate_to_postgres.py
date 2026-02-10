#!/usr/bin/env python3
"""Migrate SQLite events.db to PostgreSQL."""
import sqlite3
import psycopg2
from psycopg2.extras import execute_batch

SQLITE_PATH = '/home/jacobw/intraday_stack/data/journal/events.db'
PG_CONFIG = {
    'database': 'trading',
    'user': 'jacobw'
}

def migrate():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(**PG_CONFIG)
    pg_cursor = pg_conn.cursor()
    
    # Migrate trades
    print("Migrating trades...")
    rows = sqlite_conn.execute("SELECT * FROM trades").fetchall()
    if rows:
        execute_batch(pg_cursor, """
            INSERT INTO trades (trade_id, symbol, strategy, direction, signal_id, 
                              entry_time, entry_price, entry_qty, entry_order_id,
                              exit_time, exit_price, exit_qty, exit_order_id, exit_reason,
                              gross_pnl, commission, net_pnl, entry_slippage, exit_slippage,
                              hold_time_seconds, entry_exchanges, exit_exchanges,
                              entry_fill_count, exit_fill_count, status, system)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trade_id) DO NOTHING
        """, [tuple(row) for row in rows])
    print(f"  {len(rows)} trades")
    
    # Migrate decisions
    print("Migrating decisions...")
    rows = sqlite_conn.execute("SELECT * FROM decisions").fetchall()
    if rows:
        execute_batch(pg_cursor, """
            INSERT INTO decisions (event_id, timestamp, symbol, strategy, direction,
                                 signal_strength, net_edge_bps, decision, rejection_reason,
                                 ranked_position, features)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
        """, [tuple(row) for row in rows], page_size=1000)
    print(f"  {len(rows)} decisions")
    
    # Migrate orders
    print("Migrating orders...")
    rows = sqlite_conn.execute("SELECT * FROM orders").fetchall()
    if rows:
        execute_batch(pg_cursor, """
            INSERT INTO orders (event_id, timestamp, order_id, symbol, action, quantity,
                              order_type, status, entry_price, stop_price, target_price,
                              signal_id, system_name, order_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
        """, [tuple(row) for row in rows])
    print(f"  {len(rows)} orders")
    
    # Migrate fills
    print("Migrating fills...")
    rows = sqlite_conn.execute("SELECT * FROM fills").fetchall()
    if rows:
        execute_batch(pg_cursor, """
            INSERT INTO fills (event_id, timestamp, order_id, symbol, side, quantity,
                             price, commission, latency_ms, exchange, exec_id, realized_pnl)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
        """, [tuple(row) for row in rows])
    print(f"  {len(rows)} fills")
    
    pg_conn.commit()
    pg_cursor.close()
    pg_conn.close()
    sqlite_conn.close()
    print("Migration complete!")

if __name__ == '__main__':
    migrate()
