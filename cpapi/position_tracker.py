"""Position tracker with IBKR reconciliation."""
import logging

logger = logging.getLogger(__name__)


class PositionTracker:
    """Tracks positions and reconciles with IBKR."""
    
    def __init__(self, db, ib):
        self.db = db
        self.ib = ib
    
    def update_from_fill(self, symbol: str, system: str, side: str, qty: int, price: float):
        """Update position from fill."""
        conn = self.db.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT quantity, avg_price, realized_pnl
                FROM positions WHERE symbol = %s AND system = %s
            """, (symbol, system))
            row = cur.fetchone()
            old_qty, old_avg, realized = (row[0], row[1], row[2]) if row else (0, 0, 0)
            
            if side == 'BUY':
                if old_qty >= 0:
                    new_qty = old_qty + qty
                    new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty else 0
                else:
                    new_qty = old_qty + qty
                    pnl = (old_avg - price) * min(qty, abs(old_qty))
                    realized += pnl
                    new_avg = old_avg if new_qty < 0 else price
            else:
                if old_qty <= 0:
                    new_qty = old_qty - qty
                    new_avg = ((abs(old_qty) * old_avg) + (qty * price)) / abs(new_qty) if new_qty else 0
                else:
                    new_qty = old_qty - qty
                    pnl = (price - old_avg) * min(qty, old_qty)
                    realized += pnl
                    new_avg = old_avg if new_qty > 0 else 0
            
            cur.execute("""
                INSERT INTO positions (symbol, system, quantity, avg_price, realized_pnl, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (symbol, system) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    avg_price = EXCLUDED.avg_price,
                    realized_pnl = EXCLUDED.realized_pnl,
                    updated_at = NOW()
            """, (symbol, system, new_qty, new_avg, realized))
            conn.commit()
        finally:
            self.db.pool.putconn(conn)
    
    def reconcile_with_ibkr(self) -> list[dict]:
        """Reconcile positions with IBKR. Returns discrepancies."""
        discrepancies = []
        ibkr_positions = {}
        for pos in self.ib.positions():
            ibkr_positions[pos.contract.symbol] = {
                'quantity': int(pos.position),
                'avg_price': float(pos.avgCost)
            }
        
        conn = self.db.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT symbol, system, quantity FROM positions WHERE quantity != 0")
            db_positions = {}
            for row in cur.fetchall():
                symbol, system, qty = row
                if symbol not in db_positions:
                    db_positions[symbol] = 0
                db_positions[symbol] += qty
            
            all_symbols = set(ibkr_positions.keys()) | set(db_positions.keys())
            for symbol in all_symbols:
                ibkr_qty = ibkr_positions.get(symbol, {}).get('quantity', 0)
                db_qty = db_positions.get(symbol, 0)
                if ibkr_qty != db_qty:
                    discrepancies.append({
                        'symbol': symbol, 'ibkr_qty': ibkr_qty,
                        'db_qty': db_qty, 'diff': ibkr_qty - db_qty
                    })
                    logger.warning(f"Position mismatch {symbol}: IBKR={ibkr_qty} DB={db_qty}")
            
            for symbol, data in ibkr_positions.items():
                cur.execute("""
                    UPDATE positions SET ibkr_quantity = %s, ibkr_avg_price = %s,
                        last_reconcile = NOW(), is_reconciled = (quantity = %s)
                    WHERE symbol = %s
                """, (data['quantity'], data['avg_price'], data['quantity'], symbol))
            conn.commit()
        finally:
            self.db.pool.putconn(conn)
        return discrepancies
