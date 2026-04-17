"""Cross-service shared position ledger and global margin budget.

Each trading service writes its positions here on entry/exit.
Pre-trade checks query total exposure to prevent margin stacking.
"""

import logging
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

def _default_dsn() -> str:
    return " ".join(
        [
            f"dbname={os.getenv('POSTGRES_DB', 'trading')}",
            f"user={os.getenv('POSTGRES_USER', os.getenv('USER', 'jacobw'))}",
            f"host={os.getenv('POSTGRES_HOST', '/var/run/postgresql')}",
            f"port={os.getenv('POSTGRES_PORT', '5432')}",
        ]
    )


GLOBAL_MARGIN_CAP_PCT = 0.80  # Max 80% of account equity in margin


class SharedPositionLedger:
    """Shared position ledger backed by PostgreSQL."""

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _default_dsn()

    @contextmanager
    def _conn(self):
        conn = psycopg2.connect(self._dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert(self, service: str, symbol: str, quantity: int,
               avg_price: float, margin_used: float = 0.0) -> None:
        """Insert or update a position."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                if quantity == 0:
                    cur.execute(
                        "DELETE FROM shared_positions WHERE service=%s AND symbol=%s",
                        (service, symbol),
                    )
                else:
                    cur.execute(
                        """INSERT INTO shared_positions
                           (service, symbol, quantity, avg_price, margin_used, updated_at)
                           VALUES (%s, %s, %s, %s, %s, NOW())
                           ON CONFLICT (service, symbol) DO UPDATE SET
                             quantity=EXCLUDED.quantity,
                             avg_price=EXCLUDED.avg_price,
                             margin_used=EXCLUDED.margin_used,
                             updated_at=NOW()""",
                        (service, symbol, quantity, avg_price, margin_used),
                    )

    def remove(self, service: str, symbol: str) -> None:
        """Remove a closed position."""
        self.upsert(service, symbol, 0, 0.0)

    def get_all(self, service: str | None = None) -> list[dict]:
        """Get positions, optionally filtered by service."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if service:
                    cur.execute(
                        "SELECT * FROM shared_positions WHERE service=%s",
                        (service,),
                    )
                else:
                    cur.execute("SELECT * FROM shared_positions")
                return [dict(r) for r in cur.fetchall()]

    def get_symbol_positions(self, symbol: str) -> list[dict]:
        """Return all non-zero service positions for a symbol."""
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT service, symbol, quantity, avg_price, margin_used, updated_at
                    FROM shared_positions
                    WHERE symbol = %s AND quantity <> 0
                    ORDER BY service
                    """,
                    (symbol,),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_total_margin(self) -> float:
        """Get total margin used across all services."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(SUM(margin_used), 0) FROM shared_positions")
                return float(cur.fetchone()[0])

    def check_global_margin(self, new_margin: float, account_equity: float,
                            cap_pct: float = GLOBAL_MARGIN_CAP_PCT) -> tuple[bool, str]:
        """Check if adding new_margin would exceed the global cap.

        Uses advisory lock for atomicity across concurrent services.
        Returns (allowed, reason).
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                # Advisory lock to prevent race between services
                cur.execute("SELECT pg_advisory_xact_lock(8675309)")
                cur.execute("SELECT COALESCE(SUM(margin_used), 0) FROM shared_positions")
                total = float(cur.fetchone()[0])

                cap = account_equity * cap_pct
                if total + new_margin > cap:
                    reason = (
                        f"Global margin cap: used=${total:,.0f} + new=${new_margin:,.0f}"
                        f" > cap=${cap:,.0f} ({cap_pct:.0%} of ${account_equity:,.0f})"
                    )
                    logger.warning(reason)
                    return False, reason
                return True, "OK"

    def clear_service(self, service: str) -> None:
        """Remove all positions for a service."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM shared_positions WHERE service=%s", (service,))
