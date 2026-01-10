#!/usr/bin/env python3
"""
Complete Trade Journal with P&L Calculation

Ensures full trade database with fills, closing prices, and P&L calculation.
Can either get P&L from IBKR Gateway or calculate locally.
"""

import sqlite3
from datetime import datetime
from typing import Dict, Optional
import ib_insync as ib


class CompleteTradeJournal:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()
        
    def _init_database(self):
        """Initialize complete database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Trades table with complete P&L tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                system TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                entry_price REAL NOT NULL,
                exit_price REAL,
                entry_qty INTEGER NOT NULL,
                exit_qty INTEGER,
                gross_pnl REAL DEFAULT 0.0,
                net_pnl REAL DEFAULT 0.0,
                commission REAL DEFAULT 0.0,
                realized_pnl REAL DEFAULT 0.0,
                status TEXT DEFAULT 'OPEN',
                exit_reason TEXT,
                hold_time_seconds REAL
            )
        """)
        
        # Fills table with complete execution data
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                trade_id TEXT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                commission REAL DEFAULT 0.0,
                realized_pnl REAL DEFAULT 0.0,
                exec_id TEXT,
                exchange TEXT,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
            )
        """)
        
        conn.commit()
        conn.close()
        
    def log_fill(self, trade_id: str, symbol: str, side: str, quantity: int, 
                 price: float, commission: float = 0.0, realized_pnl: float = 0.0,
                 exec_id: str = "", exchange: str = "") -> str:
        """Log complete fill with P&L data."""
        fill_id = f"fill_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO fills (fill_id, trade_id, timestamp, symbol, side, 
                             quantity, price, commission, realized_pnl, exec_id, exchange)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (fill_id, trade_id, datetime.utcnow().isoformat(), symbol, side,
              quantity, price, commission, realized_pnl, exec_id, exchange))
        
        conn.commit()
        conn.close()
        
        # Update trade P&L
        self._update_trade_pnl(trade_id)
        return fill_id
        
    def _update_trade_pnl(self, trade_id: str):
        """Calculate and update trade P&L from fills."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all fills for this trade
        cursor.execute("""
            SELECT side, quantity, price, commission, realized_pnl 
            FROM fills WHERE trade_id = ? ORDER BY timestamp
        """, (trade_id,))
        fills = cursor.fetchall()
        
        if not fills:
            conn.close()
            return
            
        # Calculate P&L
        total_commission = sum(f[3] for f in fills)
        total_realized_pnl = sum(f[4] for f in fills)
        
        # Simple P&L calculation for complete fills
        entry_fills = [f for f in fills if f[0] in ['BUY', 'LONG']]
        exit_fills = [f for f in fills if f[0] in ['SELL', 'SHORT']]
        
        if entry_fills and exit_fills:
            entry_value = sum(f[1] * f[2] for f in entry_fills)  # qty * price
            exit_value = sum(f[1] * f[2] for f in exit_fills)
            gross_pnl = exit_value - entry_value
            net_pnl = gross_pnl - total_commission
            
            # Update trade record
            cursor.execute("""
                UPDATE trades SET 
                    gross_pnl = ?, net_pnl = ?, commission = ?, 
                    realized_pnl = ?, status = 'CLOSED'
                WHERE trade_id = ?
            """, (gross_pnl, net_pnl, total_commission, total_realized_pnl, trade_id))
            
        conn.commit()
        conn.close()
        
    def get_pnl_from_gateway(self, ib_client: ib.IB, account: str = "") -> Dict:
        """Get P&L directly from IBKR Gateway."""
        try:
            # Get account summary with P&L
            account_values = ib_client.accountSummary(account)
            pnl_data = {}
            
            for item in account_values:
                if item.tag in ['UnrealizedPnL', 'RealizedPnL', 'NetLiquidation']:
                    pnl_data[item.tag] = float(item.value)
                    
            # Get position P&L
            positions = ib_client.positions(account)
            position_pnl = {}
            
            for pos in positions:
                if pos.position != 0:
                    position_pnl[pos.contract.symbol] = {
                        'position': pos.position,
                        'market_price': pos.marketPrice,
                        'market_value': pos.marketValue,
                        'avg_cost': pos.avgCost,
                        'unrealized_pnl': pos.unrealizedPNL,
                        'realized_pnl': pos.realizedPNL
                    }
                    
            return {
                'account_pnl': pnl_data,
                'position_pnl': position_pnl,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            print(f"Error getting P&L from gateway: {e}")
            return {}
            
    def calculate_local_pnl(self, trade_id: str, current_price: float = None) -> Dict:
        """Calculate P&L locally from fills and current price."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get trade and fills
        cursor.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
        trade = cursor.fetchone()
        
        cursor.execute("""
            SELECT side, quantity, price, commission 
            FROM fills WHERE trade_id = ? ORDER BY timestamp
        """, (trade_id,))
        fills = cursor.fetchall()
        
        conn.close()
        
        if not trade or not fills:
            return {}
            
        # Calculate realized P&L from completed fills
        entry_value = 0
        exit_value = 0
        total_commission = 0
        
        for side, qty, price, commission in fills:
            total_commission += commission
            if side in ['BUY', 'LONG']:
                entry_value += qty * price
            else:
                exit_value += qty * price
                
        realized_pnl = exit_value - entry_value - total_commission
        
        # Calculate unrealized P&L if position still open
        unrealized_pnl = 0
        if trade[15] == 'OPEN' and current_price:  # status column
            remaining_qty = trade[5] - (trade[6] or 0)  # entry_qty - exit_qty
            if remaining_qty > 0:
                direction = 1 if trade[4] == 'long' else -1  # direction
                unrealized_pnl = direction * remaining_qty * (current_price - trade[7])  # entry_price
                
        return {
            'trade_id': trade_id,
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': realized_pnl + unrealized_pnl,
            'commission': total_commission,
            'fill_count': len(fills)
        }


if __name__ == "__main__":
    # Example usage
    journal = CompleteTradeJournal("/home/jacobw/intraday_stack/data/journal/events.db")
    
    # Test fill logging
    trade_id = "test_trade_001"
    fill_id = journal.log_fill(
        trade_id=trade_id,
        symbol="AAPL",
        side="BUY", 
        quantity=100,
        price=150.25,
        commission=1.00,
        realized_pnl=0.0
    )
    
    print(f"Logged fill: {fill_id}")
    
    # Calculate local P&L
    pnl = journal.calculate_local_pnl(trade_id, current_price=151.00)
    print(f"P&L calculation: {pnl}")
