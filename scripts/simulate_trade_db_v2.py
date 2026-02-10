#!/usr/bin/env python3
"""Simulate fills and test Trade Database V2 using historical data."""

import json
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from cpapi.trade_database import TradeDatabase
from cpapi.position_tracker import PositionTracker

# Mock DB config
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'trading',
    'user': 'jacobw',
    'password': ''
}

WAL_DIR = "/home/jacobw/quantstack/logs/wal"


class FillSimulator:
    """Simulate fills from historical data."""
    
    def __init__(self):
        self.db = TradeDatabase(DB_CONFIG)
        self.positions = PositionTracker(DB_CONFIG)
        self.wal_path = Path(WAL_DIR)
        self.wal_path.mkdir(parents=True, exist_ok=True)
        
    def simulate_trade(self, symbol: str, direction: str, qty: int, price: float):
        """Simulate a complete trade with entry and exit."""
        print(f"\n{'='*60}")
        print(f"Simulating {direction} trade: {symbol} {qty}@${price:.2f}")
        print(f"{'='*60}")
        
        # Open trade
        stop_loss = price * 0.99 if direction == "LONG" else price * 1.01
        take_profit = price * 1.01 if direction == "LONG" else price * 0.99
        
        trade_id = self.db.open_trade(
            symbol=symbol,
            direction=direction,
            entry_reason="simulation",
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata={"test": "simulation"}
        )
        print(f"✅ Opened trade_id={trade_id}")
        
        # Simulate entry order
        entry_order_id = random.randint(1000, 9999)
        self.db.link_order_to_trade(trade_id, entry_order_id, is_entry=True)
        print(f"✅ Linked entry order {entry_order_id}")
        
        # Simulate entry fills (possibly partial)
        num_fills = random.randint(1, 3)
        remaining_qty = qty
        
        for i in range(num_fills):
            fill_qty = remaining_qty if i == num_fills - 1 else random.randint(1, remaining_qty - 1)
            remaining_qty -= fill_qty
            fill_price = price + random.uniform(-0.02, 0.02)
            
            exec_id = f"SIM{uuid4().hex[:8]}"
            self._write_fill_to_wal(
                exec_id=exec_id,
                trade_id=trade_id,
                symbol=symbol,
                side="BUY" if direction == "LONG" else "SELL",
                qty=fill_qty,
                price=fill_price,
                commission=fill_qty * 0.005
            )
            print(f"  Fill {i+1}/{num_fills}: {fill_qty}@${fill_price:.2f}")
        
        # Simulate exit fills
        time.sleep(0.1)  # Simulate time passing
        exit_order_id = random.randint(1000, 9999)
        self.db.link_order_to_trade(trade_id, exit_order_id, is_entry=False)
        
        exit_price = take_profit if random.random() > 0.3 else stop_loss
        exit_side = "SELL" if direction == "LONG" else "BUY"
        
        exec_id = f"SIM{uuid4().hex[:8]}"
        self._write_fill_to_wal(
            exec_id=exec_id,
            trade_id=trade_id,
            symbol=symbol,
            side=exit_side,
            qty=qty,
            price=exit_price,
            commission=qty * 0.005
        )
        print(f"  Exit: {qty}@${exit_price:.2f}")
        
        # Get final trade
        trade = self.db.get_trade(trade_id)
        if trade:
            print(f"\n✅ Trade complete:")
            print(f"   Entry: {trade['entry_qty']}@${trade['entry_price']:.2f}")
            print(f"   Exit:  {trade['exit_qty']}@${trade['exit_price']:.2f}")
            print(f"   P&L:   ${trade['net_pnl']:.2f}")
        
        return trade_id
    
    def _write_fill_to_wal(self, exec_id: str, trade_id: int, symbol: str, 
                           side: str, qty: int, price: float, commission: float):
        """Write fill to WAL file (simulating UnifiedFillProcessor)."""
        wal_file = self.wal_path / f"fills_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        fill_data = {
            "exec_id": exec_id,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "commission": commission,
            "exec_time": datetime.utcnow().isoformat(),
            "received_at": datetime.utcnow().isoformat(),
            "source": "simulation"
        }
        
        with open(wal_file, 'a') as f:
            f.write(json.dumps(fill_data) + '\n')
        
        # Also write to database (simulating WAL processing)
        self._process_fill_to_db(fill_data)
    
    def _process_fill_to_db(self, fill_data: dict):
        """Process fill from WAL to database."""
        import psycopg2
        
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO executions (
                    exec_id, trade_id, symbol, side, qty, price, 
                    commission, exec_time, received_at, source
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (exec_id) DO NOTHING
            """, (
                fill_data['exec_id'],
                fill_data['trade_id'],
                fill_data['symbol'],
                fill_data['side'],
                fill_data['qty'],
                fill_data['price'],
                fill_data['commission'],
                fill_data['exec_time'],
                fill_data['received_at'],
                fill_data['source']
            ))
            conn.commit()
        except Exception as e:
            print(f"⚠️  Error writing to DB: {e}")
            conn.rollback()
        finally:
            cur.close()
            conn.close()


def run_simulation_tests():
    """Run comprehensive simulation tests."""
    print("\n" + "="*60)
    print("Trade Database V2 - Simulation Tests")
    print("="*60)
    
    sim = FillSimulator()
    
    # Test 1: Single trade
    print("\n[Test 1] Single complete trade")
    sim.simulate_trade("AAPL", "LONG", 100, 150.00)
    
    # Test 2: Multiple partial fills
    print("\n[Test 2] Trade with multiple partial fills")
    sim.simulate_trade("MSFT", "SHORT", 200, 380.00)
    
    # Test 3: Multiple trades same symbol
    print("\n[Test 3] Multiple trades same symbol")
    sim.simulate_trade("GOOGL", "LONG", 50, 140.00)
    time.sleep(0.2)
    sim.simulate_trade("GOOGL", "LONG", 75, 141.00)
    
    # Test 4: Rapid trades (stress test)
    print("\n[Test 4] Rapid trades (deduplication test)")
    symbols = ["TSLA", "NVDA", "META"]
    for symbol in symbols:
        sim.simulate_trade(symbol, "LONG", 100, 200.00)
        time.sleep(0.1)
    
    # Verification
    print("\n" + "="*60)
    print("Verification")
    print("="*60)
    
    import psycopg2
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Count trades
    cur.execute("SELECT COUNT(*) FROM trades_v2 WHERE metadata->>'test' = 'simulation'")
    trade_count = cur.fetchone()[0]
    print(f"✅ Trades created: {trade_count}")
    
    # Count fills
    cur.execute("SELECT COUNT(*) FROM executions WHERE source = 'simulation'")
    fill_count = cur.fetchone()[0]
    print(f"✅ Fills captured: {fill_count}")
    
    # Check unlinked fills
    cur.execute("SELECT COUNT(*) FROM executions WHERE trade_id IS NULL AND source = 'simulation'")
    unlinked = cur.fetchone()[0]
    if unlinked == 0:
        print(f"✅ Unlinked fills: 0")
    else:
        print(f"❌ Unlinked fills: {unlinked}")
    
    # Check P&L
    cur.execute("""
        SELECT 
            symbol,
            direction,
            entry_price,
            exit_price,
            net_pnl
        FROM trades_v2
        WHERE metadata->>'test' = 'simulation'
        ORDER BY signal_time DESC
        LIMIT 5
    """)
    
    print("\n📊 Recent simulated trades:")
    for row in cur.fetchall():
        symbol, direction, entry, exit, pnl = row
        print(f"  {symbol:6s} {direction:5s} ${entry:.2f} -> ${exit:.2f} = ${pnl:.2f}")
    
    cur.close()
    conn.close()
    
    print("\n" + "="*60)
    print("Simulation Complete")
    print("="*60)


if __name__ == '__main__':
    run_simulation_tests()
