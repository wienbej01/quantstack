"""SQLite event store for comprehensive trade journaling."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class EventStore:
    """SQLite event store for paper trading events."""

    def __init__(self, db_path: str = "data/journal/events.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)

        # ML decisions table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT,
                symbol TEXT,
                strategy TEXT,
                direction TEXT,
                confidence REAL,
                prediction REAL,
                regime TEXT,
                decision TEXT,
                rejection_reason TEXT,
                features TEXT
            )
        """
        )

        # Orders table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT,
                order_id INTEGER,
                symbol TEXT,
                action TEXT,
                quantity INTEGER,
                order_type TEXT,
                status TEXT,
                entry_price REAL,
                stop_price REAL,
                target_price REAL,
                system_name TEXT,
                order_ref TEXT
            )
        """
        )

        # Fills table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT,
                order_id INTEGER,
                symbol TEXT,
                side TEXT,
                quantity INTEGER,
                price REAL,
                commission REAL,
                exchange TEXT,
                exec_id TEXT
            )
        """
        )

        # Trades table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT,
                strategy TEXT,
                direction TEXT,
                regime TEXT,
                confidence REAL,
                entry_time TEXT,
                entry_price REAL,
                entry_qty INTEGER,
                exit_time TEXT,
                exit_price REAL,
                exit_qty INTEGER,
                exit_reason TEXT,
                gross_pnl REAL,
                commission REAL,
                net_pnl REAL,
                hold_time_seconds REAL,
                status TEXT
            )
        """
        )

        conn.commit()
        conn.close()

    def _gen_id(self) -> str:
        """Generate unique event ID."""
        return str(uuid.uuid4())[:8]

    def log_ml_decision(
        self,
        symbol: str,
        strategy: str,
        direction: str,
        confidence: float,
        prediction: float,
        regime: str,
        decision: str,
        rejection_reason: str = "",
        features: Dict = None,
    ) -> str:
        """Log ML prediction decision."""
        event_id = self._gen_id()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                event_id,
                datetime.utcnow().isoformat(),
                symbol,
                strategy,
                direction,
                confidence,
                prediction,
                regime,
                decision,
                rejection_reason,
                json.dumps(features or {}),
            ),
        )
        conn.commit()
        conn.close()
        return event_id

    def log_order(
        self,
        order_id: int,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str,
        entry_price: float = 0,
        stop_price: float = 0,
        target_price: float = 0,
        system_name: str = "",
        order_ref: str = "",
    ) -> str:
        """Log order placement."""
        event_id = self._gen_id()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                event_id,
                datetime.utcnow().isoformat(),
                order_id,
                symbol,
                action,
                quantity,
                order_type,
                "SUBMITTED",
                entry_price,
                stop_price,
                target_price,
                system_name,
                order_ref,
            ),
        )
        conn.commit()
        conn.close()
        return event_id

    def log_fill(
        self,
        order_id: int,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        commission: float = 0,
        exchange: str = "",
        exec_id: str = "",
    ) -> str:
        """Log order fill."""
        event_id = self._gen_id()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
            (
                event_id,
                datetime.utcnow().isoformat(),
                order_id,
                symbol,
                side,
                quantity,
                price,
                commission,
                exchange,
                exec_id,
            ),
        )
        conn.commit()
        conn.close()
        return event_id

    def open_trade(
        self,
        symbol: str,
        strategy: str,
        direction: str,
        regime: str,
        confidence: float,
        entry_price: float,
        entry_qty: int,
    ) -> str:
        """Open new trade record."""
        trade_id = self._gen_id()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                trade_id,
                symbol,
                strategy,
                direction,
                regime,
                confidence,
                datetime.utcnow().isoformat(),
                entry_price,
                entry_qty,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                "OPEN",
            ),
        )
        conn.commit()
        conn.close()
        return trade_id

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_qty: int,
        exit_reason: str,
        commission: float = 0,
    ) -> bool:
        """Close trade record."""
        conn = sqlite3.connect(self.db_path)

        # Get entry data
        cur = conn.cursor()
        cur.execute(
            "SELECT entry_time, entry_price, direction FROM trades WHERE trade_id = ?",
            (trade_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return False

        entry_time_str, entry_price, direction = row
        entry_time = datetime.fromisoformat(entry_time_str)
        exit_time = datetime.utcnow()

        # Calculate P&L
        if direction == "long":
            gross_pnl = (exit_price - entry_price) * exit_qty
        else:
            gross_pnl = (entry_price - exit_price) * exit_qty

        net_pnl = gross_pnl - commission
        hold_time = (exit_time - entry_time).total_seconds()

        # Update trade
        conn.execute(
            """
            UPDATE trades SET 
                exit_time = ?, exit_price = ?, exit_qty = ?, exit_reason = ?,
                gross_pnl = ?, commission = ?, net_pnl = ?, 
                hold_time_seconds = ?, status = ?
            WHERE trade_id = ?
        """,
            (
                exit_time.isoformat(),
                exit_price,
                exit_qty,
                exit_reason,
                gross_pnl,
                commission,
                net_pnl,
                hold_time,
                "CLOSED",
                trade_id,
            ),
        )

        conn.commit()
        conn.close()
        return True

    def get_daily_summary(self, date_str: str) -> Dict:
        """Get daily trading summary."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Get decisions
        cur.execute(
            """
            SELECT decision, COUNT(*) as count 
            FROM decisions 
            WHERE timestamp LIKE ? 
            GROUP BY decision
        """,
            (f"{date_str}%",),
        )
        decisions = {row["decision"]: row["count"] for row in cur.fetchall()}

        # Get closed trades
        cur.execute(
            """
            SELECT COUNT(*) as total, SUM(net_pnl) as net_pnl,
                   SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as winners
            FROM trades 
            WHERE exit_time LIKE ? AND status = 'CLOSED'
        """,
            (f"{date_str}%",),
        )
        trades = dict(cur.fetchone())

        conn.close()

        return {
            "date": date_str,
            "signals_generated": decisions.get("TRADE", 0),
            "signals_rejected": decisions.get("NO_TRADE", 0),
            "trades_closed": trades["total"] or 0,
            "winners": trades["winners"] or 0,
            "net_pnl": trades["net_pnl"] or 0,
            "win_rate": (trades["winners"] / trades["total"]) if trades["total"] else 0,
        }

    def get_regime_performance(self) -> Dict:
        """Get performance by regime."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute(
            """
            SELECT regime, COUNT(*) as trades, SUM(net_pnl) as pnl,
                   AVG(confidence) as avg_confidence,
                   SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as winners
            FROM trades 
            WHERE status = 'CLOSED' AND regime IS NOT NULL
            GROUP BY regime
        """
        )

        results = {}
        for row in cur.fetchall():
            results[row["regime"]] = {
                "trades": row["trades"],
                "pnl": row["pnl"],
                "avg_confidence": row["avg_confidence"],
                "win_rate": row["winners"] / row["trades"] if row["trades"] else 0,
            }

        conn.close()
        return results
