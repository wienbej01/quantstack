"""Trade database interface."""

import json
import uuid
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.pool import ThreadedConnectionPool


class TradeDatabase:
    """Database interface for all trading systems."""

    def __init__(self, db_config: dict):
        self.pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=db_config.get("host", "localhost"),
            port=db_config.get("port", 5432),
            database=db_config.get("database", "trading"),
            user=db_config.get("user"),
            password=db_config.get("password"),
        )

    def open_trade(
        self,
        symbol: str,
        system: str,
        direction: str,
        signal_price: float,
        signal_time: datetime,
        strategy: str = None,
        substrategy: str = None,
        initial_stop: float = None,
        initial_target: float = None,
        signal_data: dict = None,
    ) -> str:
        """Create new trade record. Returns trade_id."""
        trade_id = str(uuid.uuid4())
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO trades_v2 (
                    trade_id, symbol, system, direction, strategy, substrategy,
                    signal_time, signal_price, signal_data,
                    initial_stop, current_stop, initial_target, current_target, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
            """,
                (
                    trade_id,
                    symbol,
                    system,
                    direction,
                    strategy,
                    substrategy,
                    signal_time,
                    signal_price,
                    json.dumps(signal_data or {}),
                    initial_stop,
                    initial_stop,
                    initial_target,
                    initial_target,
                ),
            )
            conn.commit()
            return trade_id
        finally:
            self.pool.putconn(conn)

    def link_order_to_trade(
        self,
        trade_id: str,
        ibkr_order_id: int,
        is_entry: bool,
        system: str | None = None,
    ):
        """Link IBKR order to trade for fill matching by order_id."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO trade_order_links (trade_id, ibkr_order_id, system, is_entry)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (trade_id, ibkr_order_id) DO NOTHING
            """,
                (trade_id, ibkr_order_id, system, is_entry),
            )
            # Link by ibkr_order_id since that's available at order placement
            if system:
                cur.execute(
                    """
                    UPDATE executions
                    SET trade_id = %s,
                        system = COALESCE(NULLIF(system, 'unknown'), %s)
                    WHERE ibkr_order_id = %s AND trade_id IS NULL
                """,
                    (trade_id, system, ibkr_order_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE executions SET trade_id = %s
                    WHERE ibkr_order_id = %s AND trade_id IS NULL
                """,
                    (trade_id, ibkr_order_id),
                )
            # Backfill any existing executions for this order into trades_v2
            self._backfill_trade_from_executions(cur, trade_id, ibkr_order_id)
            conn.commit()
        finally:
            self.pool.putconn(conn)

    def _backfill_trade_from_executions(
        self,
        cur,
        trade_id: str,
        ibkr_order_id: int,
    ) -> None:
        """Apply existing executions to trades_v2 if fills arrived before linking."""
        cur.execute(
            """
            SELECT exec_id, price, quantity, side, ibkr_time, exchange, commission
            FROM executions
            WHERE trade_id = %s AND ibkr_order_id = %s
            ORDER BY ibkr_time
        """,
            (trade_id, ibkr_order_id),
        )
        rows = cur.fetchall()
        for row in rows:
            exec_id, price, quantity, side, ibkr_time, exchange, commission = row
            self._apply_execution_to_trade(
                cur,
                trade_id=trade_id,
                exec_id=exec_id,
                price=float(price),
                quantity=int(quantity),
                side=side,
                ibkr_time=ibkr_time,
                exchange=exchange,
                commission=float(commission or 0),
            )

    def _apply_execution_to_trade(
        self,
        cur,
        trade_id: str,
        exec_id: str,
        price: float,
        quantity: int,
        side: str,
        ibkr_time,
        exchange: str | None,
        commission: float,
    ) -> None:
        """Apply a single execution to trades_v2 (idempotent)."""
        cur.execute(
            """
            SELECT direction, entry_fills, exit_fills, status
            FROM trades_v2
            WHERE trade_id = %s
        """,
            (trade_id,),
        )
        row = cur.fetchone()
        if not row:
            return
        direction, entry_fills, exit_fills, status = row
        fill_record = {
            "exec_id": exec_id,
            "price": price,
            "qty": quantity,
            "time": ibkr_time,
            "exchange": exchange,
            "commission": commission,
        }

        is_entry_fill = (direction == "long" and side == "BUY") or (
            direction == "short" and side == "SELL"
        )

        if is_entry_fill and status == "PENDING":
            fills = entry_fills or []
            if any(f.get("exec_id") == exec_id for f in fills):
                return
            fills.append(fill_record)
            vwap = sum(f["price"] * f["qty"] for f in fills) / sum(
                f["qty"] for f in fills
            )
            total_qty = sum(f["qty"] for f in fills)
            cur.execute(
                """
                UPDATE trades_v2 SET entry_fills = %s, entry_fill_count = %s,
                    entry_price = %s, entry_qty = %s, entry_time = COALESCE(entry_time, %s),
                    status = 'OPEN', updated_at = NOW()
                WHERE trade_id = %s
            """,
                (json.dumps(fills), len(fills), vwap, total_qty, ibkr_time, trade_id),
            )
            return

        fills = exit_fills or []
        if any(f.get("exec_id") == exec_id for f in fills):
            return
        fills.append(fill_record)
        vwap = sum(f["price"] * f["qty"] for f in fills) / sum(f["qty"] for f in fills)
        total_qty = sum(f["qty"] for f in fills)
        cur.execute(
            """
            UPDATE trades_v2 SET exit_fills = %s, exit_fill_count = %s,
                exit_price = %s, exit_qty = %s, exit_time = %s, updated_at = NOW()
            WHERE trade_id = %s
        """,
            (json.dumps(fills), len(fills), vwap, total_qty, ibkr_time, trade_id),
        )
        self._maybe_close_trade(cur, trade_id)

    def _maybe_close_trade(self, cur, trade_id: str) -> None:
        """Close trade if fully filled and calculate P&L."""
        cur.execute(
            """
            SELECT direction, entry_price, entry_qty, exit_price, exit_qty,
                   entry_fills, exit_fills
            FROM trades_v2 WHERE trade_id = %s
        """,
            (trade_id,),
        )
        row = cur.fetchone()
        if not row or not row[4] or row[4] < row[2]:
            return
        (
            direction,
            entry_price,
            entry_qty,
            exit_price,
            exit_qty,
            entry_fills,
            exit_fills,
        ) = row
        gross_pnl = (
            (exit_price - entry_price) * entry_qty
            if direction == "long"
            else (entry_price - exit_price) * entry_qty
        )
        total_comm = sum(f.get("commission", 0) for f in (entry_fills or [])) + sum(
            f.get("commission", 0) for f in (exit_fills or [])
        )
        net_pnl = gross_pnl - total_comm
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM (exit_time - entry_time)) FROM trades_v2 WHERE trade_id = %s",
            (trade_id,),
        )
        hold_seconds = cur.fetchone()[0] or 0
        cur.execute(
            """
            UPDATE trades_v2 SET gross_pnl = %s, total_commission = %s, net_pnl = %s,
                hold_seconds = %s, status = 'CLOSED', updated_at = NOW()
            WHERE trade_id = %s
        """,
            (gross_pnl, total_comm, net_pnl, hold_seconds, trade_id),
        )

    def get_trade(self, trade_id: str) -> Optional[dict]:
        """Get trade by ID."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trades_v2 WHERE trade_id = %s", (trade_id,))
            row = cur.fetchone()
            if row:
                cols = [desc[0] for desc in cur.description]
                return dict(zip(cols, row))
            return None
        finally:
            self.pool.putconn(conn)

    def get_open_trades(self, system: str = None) -> list[dict]:
        """Get all open trades."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            if system:
                cur.execute(
                    """
                    SELECT * FROM trades_v2 
                    WHERE status IN ('PENDING', 'OPEN') AND system = %s
                """,
                    (system,),
                )
            else:
                cur.execute(
                    "SELECT * FROM trades_v2 WHERE status IN ('PENDING', 'OPEN')"
                )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            self.pool.putconn(conn)

    def get_trades_for_date(self, date_str: str, system: str = None) -> list[dict]:
        """Get all trades for a date."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            if system:
                cur.execute(
                    """
                    SELECT * FROM trades_v2 
                    WHERE entry_time::date = %s AND system = %s
                    ORDER BY entry_time
                """,
                    (date_str, system),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM trades_v2 
                    WHERE entry_time::date = %s
                    ORDER BY entry_time
                """,
                    (date_str,),
                )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            self.pool.putconn(conn)

    def update_stop(self, trade_id: str, new_stop: float, reason: str = None):
        """Update stop price with audit trail."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT current_stop, stop_adjustments FROM trades_v2 WHERE trade_id = %s",
                (trade_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            old_stop, adjustments = row
            adjustments = adjustments or []
            adjustments.append(
                {
                    "time": datetime.utcnow().isoformat(),
                    "old": float(old_stop) if old_stop else None,
                    "new": new_stop,
                    "reason": reason,
                }
            )
            cur.execute(
                """
                UPDATE trades_v2 SET current_stop = %s, stop_adjustments = %s, updated_at = NOW()
                WHERE trade_id = %s
            """,
                (new_stop, json.dumps(adjustments), trade_id),
            )
            conn.commit()
        finally:
            self.pool.putconn(conn)

    def close(self):
        """Close connection pool."""
        self.pool.closeall()
