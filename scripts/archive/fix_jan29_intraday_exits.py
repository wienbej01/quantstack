#!/usr/bin/env python3
"""Fix Jan 29 intraday trades with correct exit prices from fills table."""

import psycopg2

def fix_jan29_trades():
    """Update Jan 29 intraday trades with actual exit prices."""
    conn = psycopg2.connect(database='trading', user='jacobw')
    cursor = conn.cursor()
    
    # Get trades that need fixing (entry_price == exit_price on Jan 29)
    cursor.execute("""
        SELECT trade_id, symbol, entry_price, exit_price, entry_qty, direction
        FROM trades
        WHERE entry_time::date = '2026-01-29'
        AND system = 'intraday-paper'
        AND entry_price = exit_price
        ORDER BY entry_time
    """)
    
    trades = cursor.fetchall()
    print(f"Found {len(trades)} trades to fix")
    
    for trade_id, symbol, entry_price, exit_price, qty, direction in trades:
        # Find actual exit fill
        exit_side = 'SLD' if direction == 'long' else 'BOT'
        cursor.execute("""
            SELECT price, timestamp 
            FROM fills 
            WHERE symbol = %s 
            AND side = %s
            AND timestamp::date = '2026-01-29'
            ORDER BY timestamp DESC
            LIMIT 1
        """, (symbol, exit_side))
        
        fill = cursor.fetchone()
        if fill:
            actual_exit_price = float(fill[0])
            fill_time = fill[1]
            
            # Calculate correct P&L
            if direction == 'long':
                gross_pnl = (actual_exit_price - entry_price) * qty
            else:
                gross_pnl = (entry_price - actual_exit_price) * qty
            
            # Assume $1 commission per trade
            commission = 1.0
            net_pnl = gross_pnl - commission
            
            print(f"\n{symbol}:")
            print(f"  Entry: ${entry_price:.2f}")
            print(f"  Exit (wrong): ${exit_price:.2f}")
            print(f"  Exit (actual): ${actual_exit_price:.2f}")
            print(f"  P&L: ${net_pnl:.2f}")
            
            # Update trade
            cursor.execute("""
                UPDATE trades
                SET exit_price = %s,
                    gross_pnl = %s,
                    net_pnl = %s
                WHERE trade_id = %s
            """, (actual_exit_price, gross_pnl, net_pnl, trade_id))
            
            print(f"  ✅ Updated")
        else:
            print(f"\n{symbol}: ❌ No exit fill found")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"\n✅ Fixed {len(trades)} trades")

if __name__ == "__main__":
    fix_jan29_trades()
