"""Event journaling for L2 collection (from PAPER_TRADING_GUIDE)."""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class L2Journal:
    """SQLite event journal for L2 collection."""

    def __init__(self, config: dict):
        journal_cfg = config.get("journal", {})
        self.enabled = journal_cfg.get("enabled", True)
        self.db_path = Path(journal_cfg.get("db_path", "./data/l2/journal.db"))

        if self.enabled:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                start_time TEXT,
                end_time TEXT,
                symbols TEXT,
                window TEXT,
                records_collected INTEGER DEFAULT 0,
                depth_rate REAL,
                avg_spread REAL,
                status TEXT DEFAULT 'running'
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS errors (
                error_id TEXT PRIMARY KEY,
                timestamp TEXT,
                session_id TEXT,
                error_type TEXT,
                message TEXT,
                symbol TEXT
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_records INTEGER,
                total_sessions INTEGER,
                symbols_collected TEXT,
                avg_depth_rate REAL,
                avg_spread REAL,
                storage_mb REAL
            )
        """
        )

        conn.commit()
        conn.close()

    def _gen_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def start_session(self, symbols: list[str], window: str = None) -> str:
        """Log collection session start."""
        if not self.enabled:
            return ""

        session_id = self._gen_id()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO sessions (session_id, start_time, symbols, window, status)
            VALUES (?, ?, ?, ?, 'running')
        """,
            (session_id, datetime.utcnow().isoformat(), json.dumps(symbols), window),
        )
        conn.commit()
        conn.close()

        logger.info(f"Session started: {session_id} with {len(symbols)} symbols")
        return session_id

    def end_session(self, session_id: str, stats: dict):
        """Log collection session end."""
        if not self.enabled or not session_id:
            return

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            UPDATE sessions SET 
                end_time = ?, records_collected = ?, depth_rate = ?,
                avg_spread = ?, status = 'completed'
            WHERE session_id = ?
        """,
            (
                datetime.utcnow().isoformat(),
                stats.get("records", 0),
                stats.get("depth_rate", 0),
                stats.get("avg_spread", 0),
                session_id,
            ),
        )
        conn.commit()
        conn.close()

        logger.info(
            f"Session ended: {session_id} with {stats.get('records', 0)} records"
        )

    def log_error(
        self, error_type: str, message: str, session_id: str = None, symbol: str = None
    ):
        """Log error event."""
        if not self.enabled:
            return

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO errors (error_id, timestamp, session_id, error_type, message, symbol)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                self._gen_id(),
                datetime.utcnow().isoformat(),
                session_id,
                error_type,
                message,
                symbol,
            ),
        )
        conn.commit()
        conn.close()

        logger.error(f"[{error_type}] {message}")

    def update_daily_stats(self, date_str: str, stats: dict):
        """Update daily statistics."""
        if not self.enabled:
            return

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_stats 
            (date, total_records, total_sessions, symbols_collected, 
             avg_depth_rate, avg_spread, storage_mb)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                date_str,
                stats.get("total_records", 0),
                stats.get("total_sessions", 0),
                json.dumps(stats.get("symbols", [])),
                stats.get("avg_depth_rate", 0),
                stats.get("avg_spread", 0),
                stats.get("storage_mb", 0),
            ),
        )
        conn.commit()
        conn.close()

    def get_session_stats(self, session_id: str) -> Optional[dict]:
        """Get stats for a session."""
        if not self.enabled:
            return None

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
        conn.close()

        return dict(row) if row else None

    def get_daily_summary(self, date_str: str) -> dict:
        """Get collection summary for a date."""
        if not self.enabled:
            return {}

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Get sessions for date
        cur.execute(
            """
            SELECT COUNT(*) as sessions, SUM(records_collected) as records,
                   AVG(depth_rate) as depth_rate, AVG(avg_spread) as spread
            FROM sessions WHERE start_time LIKE ?
        """,
            (f"{date_str}%",),
        )
        row = cur.fetchone()

        # Get errors for date
        cur.execute(
            """
            SELECT COUNT(*) as errors FROM errors WHERE timestamp LIKE ?
        """,
            (f"{date_str}%",),
        )
        errors = cur.fetchone()

        conn.close()

        return {
            "date": date_str,
            "sessions": row["sessions"] or 0,
            "records": row["records"] or 0,
            "depth_rate": row["depth_rate"] or 0,
            "avg_spread": row["spread"] or 0,
            "errors": errors["errors"] or 0,
        }
