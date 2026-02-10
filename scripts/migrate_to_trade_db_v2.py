#!/usr/bin/env python3
"""Migrate trades from old broken database to Trade DB V2"""
import psycopg2
from datetime import datetime
from decimal import Decimal

def get_db_config():
    return {"database": "trading", "user": "jacobw"}

def migrate():
    conn = psycopg2.connect(**get_db_config())
    cur = conn.cursor()
    
    # Get old trades
    cur.execute("""
        SELECT trade_id, symbol, strategy, direction, signal_id,
               entry_time, entry_price, entry_qty, entry_order_id,
               exit_time, exit_price, exit_qty, exit_order_id,
               exit_reason, gross_pnl, commission, net_pnl,
               entry_slippage, exit_slippage, hold_time_seconds,
               status, system, signal_entry_price, signal_exit_price
        FROM trades
        WHERE trade_id IS NOT NULL
        ORDER BY entry_time
    """)
    
    old_trades = cur.fetchall()
    print(f"Found {len(old_trades)} trades in old database")
    
    migrated = 0
    skipped = 0
    
    for row in old_trades:
        (trade_id, symbol, strategy, direction, signal_id,
         entry_time, entry_price, entry_qty, entry_order_id,
         exit_time, exit_price, exit_qty, exit_order_id,
         exit_reason, gross_pnl, commission, net_pnl,
         entry_slippage, exit_slippage, hold_time_seconds,
         status, system, signal_entry_price, signal_exit_price) = row
        
        if not symbol or not system:
            skipped += 1
            continue
            
        # Parse timestamps
        try:
            signal_time = datetime.fromisoformat(entry_time) if entry_time else None
            entry_ts = datetime.fromisoformat(entry_time) if entry_time else None
            exit_ts = datetime.fromisoformat(exit_time) if exit_time else None
        except:
            signal_time = None
            entry_ts = None
            exit_ts = None
            
        # Map direction
        dir_map = {'LONG': 'long', 'SHORT': 'short', 'long': 'long', 'short': 'short'}
        direction_v2 = dir_map.get(direction, 'long')
        
        # Map status
        status_map = {'open': 'OPEN', 'closed': 'CLOSED', 'OPEN': 'OPEN', 'CLOSED': 'CLOSED'}
        status_v2 = status_map.get(status, 'CLOSED' if exit_time else 'OPEN')
        
        # Insert into trades_v2
        try:
            cur.execute("""
                INSERT INTO trades_v2 (
                    symbol, system, strategy, direction, status,
                    signal_time, signal_price,
                    entry_time, entry_price, entry_qty,
                    exit_time, exit_price, exit_qty,
                    gross_pnl, total_commission, net_pnl,
                    entry_slippage_bps, exit_slippage_bps,
                    hold_seconds, exit_reason
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s
                )
            """, (
                symbol, system or 'legacy', strategy, direction_v2, status_v2,
                signal_time, signal_entry_price,
                entry_ts, entry_price, entry_qty,
                exit_ts, exit_price, exit_qty,
                gross_pnl, commission, net_pnl,
                entry_slippage, exit_slippage,
                hold_time_seconds, exit_reason
            ))
            migrated += 1
        except Exception as e:
            print(f"Error migrating trade {trade_id}: {e}")
            skipped += 1
            
    conn.commit()
    
    # Verify
    cur.execute("SELECT COUNT(*) FROM trades_v2 WHERE system = 'legacy' OR strategy IS NOT NULL")
    new_count = cur.fetchone()[0]
    
    print(f"\nMigration complete:")
    print(f"  Migrated: {migrated}")
    print(f"  Skipped: {skipped}")
    print(f"  Total in trades_v2: {new_count}")
    
    conn.close()

if __name__ == "__main__":
    migrate()
