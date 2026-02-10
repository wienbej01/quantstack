#!/usr/bin/env python3
"""Verify Trade Database V2 integration and health."""

import psycopg2
import sys
import subprocess
from datetime import datetime, timedelta

def get_db_config():
    """Get database config, using peer auth for local connections"""
    try:
        # Test if we can connect via psql (uses peer auth)
        result = subprocess.run(
            ['psql', '-U', 'jacobw', '-d', 'trading', '-c', 'SELECT 1'],
            capture_output=True, timeout=2
        )
        if result.returncode == 0:
            # Use Unix socket connection (peer auth)
            return {"database": "trading", "user": "jacobw"}
    except:
        pass
    
    # Fall back to TCP
    return {
        'host': 'localhost',
        'port': 5432,
        'database': 'trading',
        'user': 'jacobw',
    }

def check_schema():
    """Verify schema exists."""
    print("=" * 60)
    print("CHECKING SCHEMA")
    print("=" * 60)
    
    conn = psycopg2.connect(**get_db_config())
    cur = conn.cursor()
    
    tables = ['executions', 'trades_v2', 'positions', 'trade_order_links']
    for table in tables:
        cur.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{table}'")
        exists = cur.fetchone()[0]
        status = "✅" if exists else "❌"
        print(f"{status} Table '{table}': {'EXISTS' if exists else 'MISSING'}")
    
    cur.close()
    conn.close()
    print()

def check_fill_capture():
    """Check fill capture rate."""
    print("=" * 60)
    print("FILL CAPTURE RATE (Last 24 Hours)")
    print("=" * 60)
    
    conn = psycopg2.connect(**get_db_config())
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            source,
            COUNT(*) as fills,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as pct
        FROM executions
        WHERE received_at > NOW() - INTERVAL '24 hours'
        GROUP BY source
        ORDER BY fills DESC
    """)
    
    rows = cur.fetchall()
    if rows:
        for source, fills, pct in rows:
            print(f"  {source:15s}: {fills:5d} fills ({pct:5.1f}%)")
    else:
        print("  No fills in last 24 hours")
    
    cur.close()
    conn.close()
    print()

def check_unlinked_fills():
    """Check for unlinked fills."""
    print("=" * 60)
    print("UNLINKED FILLS")
    print("=" * 60)
    
    conn = psycopg2.connect(**get_db_config())
    cur = conn.cursor()
    
    cur.execute("""
        SELECT COUNT(*) 
        FROM executions 
        WHERE trade_id IS NULL 
            AND received_at > NOW() - INTERVAL '24 hours'
    """)
    
    unlinked = cur.fetchone()[0]
    status = "✅" if unlinked == 0 else "⚠️"
    print(f"{status} Unlinked fills (last 24h): {unlinked}")
    
    if unlinked > 0:
        cur.execute("""
            SELECT symbol, side, quantity, price, received_at
            FROM executions
            WHERE trade_id IS NULL
                AND received_at > NOW() - INTERVAL '24 hours'
            ORDER BY received_at DESC
            LIMIT 5
        """)
        print("\n  Recent unlinked fills:")
        for row in cur.fetchall():
            print(f"    {row[0]} {row[1]} {row[2]}@{row[3]:.2f} at {row[4]}")
    
    cur.close()
    conn.close()
    print()

def check_position_reconciliation():
    """Check position reconciliation."""
    print("=" * 60)
    print("POSITION RECONCILIATION")
    print("=" * 60)
    
    conn = psycopg2.connect(**get_db_config())
    cur = conn.cursor()
    
    cur.execute("""
        SELECT COUNT(*) 
        FROM positions 
        WHERE NOT is_reconciled
    """)
    
    discrepancies = cur.fetchone()[0]
    status = "✅" if discrepancies == 0 else "❌"
    print(f"{status} Position discrepancies: {discrepancies}")
    
    if discrepancies > 0:
        cur.execute("""
            SELECT symbol, quantity, avg_price, last_reconcile
            FROM positions
            WHERE NOT is_reconciled
            ORDER BY last_reconcile DESC
            LIMIT 5
        """)
        print("\n  Positions with discrepancies:")
        for row in cur.fetchall():
            print(f"    {row[0]}: {row[1]} @ {row[2]:.2f} (last check: {row[3]})")
    
    cur.close()
    conn.close()
    print()

def check_recent_trades():
    """Show recent trades."""
    print("=" * 60)
    print("RECENT TRADES (Last 24 Hours)")
    print("=" * 60)
    
    conn = psycopg2.connect(**get_db_config())
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            trade_id,
            symbol,
            direction,
            status,
            entry_price,
            exit_price,
            net_pnl
        FROM trades_v2
        WHERE signal_time > NOW() - INTERVAL '24 hours'
        ORDER BY signal_time DESC
        LIMIT 10
    """)
    
    rows = cur.fetchall()
    if rows:
        for row in rows:
            trade_id, symbol, direction, status, entry, exit, pnl = row
            entry_str = f"{entry:.2f}" if entry else "N/A"
            exit_str = f"{exit:.2f}" if exit else "N/A"
            pnl_str = f"${pnl:.2f}" if pnl else "N/A"
            print(f"  {symbol:6s} {direction:5s} {status:8s} {entry_str:8s} -> {exit_str:8s} PnL: {pnl_str}")
    else:
        print("  No trades in last 24 hours")
    
    cur.close()
    conn.close()
    print()

def check_wal_files():
    """Check WAL files."""
    print("=" * 60)
    print("WRITE-AHEAD LOG (WAL)")
    print("=" * 60)
    
    import os
    from pathlib import Path
    
    wal_dir = Path("/home/jacobw/quantstack/logs/wal")
    if wal_dir.exists():
        wal_files = list(wal_dir.glob("fills_*.jsonl"))
        print(f"  WAL files: {len(wal_files)}")
        
        if wal_files:
            latest = max(wal_files, key=lambda p: p.stat().st_mtime)
            size = latest.stat().st_size
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            print(f"  Latest: {latest.name}")
            print(f"  Size: {size:,} bytes")
            print(f"  Modified: {mtime}")
    else:
        print("  ⚠️  WAL directory not found")
    
    print()

def main():
    """Run all checks."""
    print("\n" + "=" * 60)
    print("TRADE DATABASE V2 HEALTH CHECK")
    print("=" * 60)
    print(f"Time: {datetime.now()}")
    print("=" * 60)
    print()
    
    try:
        check_schema()
        check_fill_capture()
        check_unlinked_fills()
        check_position_reconciliation()
        check_recent_trades()
        check_wal_files()
        
        print("=" * 60)
        print("HEALTH CHECK COMPLETE")
        print("=" * 60)
        
    except psycopg2.Error as e:
        print(f"\n❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
