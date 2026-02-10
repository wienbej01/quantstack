"""Unified fill processor with triple-layer capture and WAL durability."""
from collections import deque
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
import psycopg2
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid %s=%s; using default %.2f", name, value, default)
        return default


class UnifiedFillProcessor:
    """Captures fills from IBKR with 100% reliability."""
    
    def __init__(
        self,
        ib,
        db_config: dict,
        wal_dir: str = "data/wal",
        ib_call: Callable[..., Any] | None = None,
        poll_interval_sec: float | None = None,
        poll_idle_interval_sec: float | None = None,
        poll_idle_after_sec: float | None = None,
        reconcile_interval_sec: float | None = None,
        wal_flush_interval_sec: float | None = None,
    ):
        self.ib = ib
        self.ib_call = ib_call
        self.wal_dir = Path(wal_dir)
        self.wal_dir.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadedConnectionPool(
            minconn=2, maxconn=10,
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 5432),
            database=db_config.get('database', 'trading'),
            user=db_config.get('user'),
            password=db_config.get('password')
        )
        self._running = False
        self._lock = threading.Lock()
        self._ib_call_warned = False
        self._last_fill_ts: float | None = None
        # In-memory dedup to avoid re-WAL'ing the same execution on every poll loop.
        self._seen_exec_ids: set[str] = set()
        self._seen_exec_ids_fifo: deque[str] = deque()
        self._seen_exec_ids_max = int(os.getenv("IBKR_FILL_DEDUP_CACHE_SIZE", "50000"))
        if self._seen_exec_ids_max <= 0:
            self._seen_exec_ids_max = 50000
        self._poll_interval_sec = (
            float(poll_interval_sec)
            if poll_interval_sec is not None
            else _env_float("IBKR_FILL_POLL_INTERVAL_SEC", 2.0)
        )
        self._poll_idle_interval_sec = (
            float(poll_idle_interval_sec)
            if poll_idle_interval_sec is not None
            else _env_float("IBKR_FILL_POLL_IDLE_INTERVAL_SEC", 5.0)
        )
        self._poll_idle_after_sec = (
            float(poll_idle_after_sec)
            if poll_idle_after_sec is not None
            else _env_float("IBKR_FILL_POLL_IDLE_AFTER_SEC", 30.0)
        )
        self._reconcile_interval_sec = (
            float(reconcile_interval_sec)
            if reconcile_interval_sec is not None
            else _env_float("IBKR_FILL_RECONCILE_INTERVAL_SEC", 900.0)
        )
        self._wal_flush_interval_sec = (
            float(wal_flush_interval_sec)
            if wal_flush_interval_sec is not None
            else _env_float("IBKR_FILL_WAL_FLUSH_INTERVAL_SEC", 2.0)
        )
        if self._poll_interval_sec <= 0:
            self._poll_interval_sec = 2.0
        if self._poll_idle_interval_sec <= 0:
            self._poll_idle_interval_sec = self._poll_interval_sec
        if self._poll_idle_after_sec <= 0:
            self._poll_idle_after_sec = 30.0
        if self._reconcile_interval_sec <= 0:
            self._reconcile_interval_sec = 900.0
        if self._wal_flush_interval_sec <= 0:
            self._wal_flush_interval_sec = 2.0

    def _parse_dt(self, value: str | None) -> datetime:
        """Parse an ISO-ish datetime string.

        Older WAL entries were written using `datetime.utcnow().isoformat()` (no tz).
        Treat naive values as UTC to avoid shifting `received_at` by the server TZ.
        """
        if not value:
            return datetime.now(timezone.utc)
        raw = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _seen_before(self, exec_id: str) -> bool:
        if exec_id in self._seen_exec_ids:
            return True
        self._seen_exec_ids.add(exec_id)
        self._seen_exec_ids_fifo.append(exec_id)
        if len(self._seen_exec_ids_fifo) > self._seen_exec_ids_max:
            old = self._seen_exec_ids_fifo.popleft()
            self._seen_exec_ids.discard(old)
        return False
    
    def start(self):
        """Start all capture layers."""
        self._running = True
        self._last_fill_ts = time.monotonic()
        self.ib.execDetailsEvent += self._on_exec_details
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        self._recon_thread = threading.Thread(target=self._reconcile_loop, daemon=True)
        self._recon_thread.start()
        self._wal_thread = threading.Thread(target=self._process_wal_loop, daemon=True)
        self._wal_thread.start()
        logger.info(
            "UnifiedFillProcessor intervals: poll=%.2fs idle=%.2fs(after %.1fs) "
            "reconcile=%.1fs wal_flush=%.1fs",
            self._poll_interval_sec,
            self._poll_idle_interval_sec,
            self._poll_idle_after_sec,
            self._reconcile_interval_sec,
            self._wal_flush_interval_sec,
        )
        logger.info("UnifiedFillProcessor started")
    
    def stop(self):
        """Stop all capture layers."""
        self._running = False
        self.ib.execDetailsEvent -= self._on_exec_details
        self.pool.closeall()
    
    def _on_exec_details(self, trade, fill):
        """Handle execDetailsEvent callback."""
        self._process_fill(fill, source="CALLBACK")

    def _poll_sleep_interval(self) -> float:
        """Return poll sleep interval with idle backoff."""
        if self._last_fill_ts is None:
            return self._poll_interval_sec
        idle_for = time.monotonic() - self._last_fill_ts
        if idle_for >= self._poll_idle_after_sec:
            return max(self._poll_idle_interval_sec, self._poll_interval_sec)
        return self._poll_interval_sec
    
    def _poll_loop(self):
        """Poll Trade.fills at a reduced, adaptive interval."""
        while self._running:
            try:
                trades = self._call_ib(self.ib.trades, timeout=10)
                for trade in trades:
                    for fill in trade.fills:
                        self._process_fill(fill, source="POLL")
            except Exception as e:
                logger.error(f"Poll error: {e}")
            time.sleep(self._poll_sleep_interval())
    
    def _reconcile_loop(self):
        """Request all executions on a slower cadence."""
        while self._running:
            try:
                executions = self._call_ib(self.ib.reqExecutions, timeout=10)
                for exec_detail in executions:
                    self._process_fill(exec_detail.execution, source="RECONCILE")
            except Exception as e:
                logger.error(f"Reconcile error: {e}")
            time.sleep(self._reconcile_interval_sec)
    
    def _process_fill(self, fill, source: str):
        """Process fill with database-level deduplication."""
        self._last_fill_ts = time.monotonic()
        
        # Handle both Fill objects (from trade.fills) and Execution objects (from reqExecutions)
        if hasattr(fill, 'execution'):
            # Fill NamedTuple: Fill(contract, execution, commissionReport, time)
            exec_obj = fill.execution
            symbol = fill.contract.symbol
            commission = fill.commissionReport.commission if fill.commissionReport else 0
        else:
            # Execution object directly
            exec_obj = fill
            symbol = getattr(exec_obj, 'symbol', 'UNKNOWN')
            commission = 0
        
        exec_id = getattr(exec_obj, "execId", None)
        if not exec_id:
            return
        if self._seen_before(str(exec_id)):
            return

        logger.debug(
            "FILL [%s]: %s %s %s@%s order=%s exec_id=%s",
            source,
            symbol,
            exec_obj.side,
            exec_obj.shares,
            exec_obj.price,
            exec_obj.orderId,
            exec_id,
        )
        
        # Normalize side: IBKR uses BOT/SLD, DB expects BUY/SELL
        raw_side = exec_obj.side
        side = 'BUY' if raw_side == 'BOT' else 'SELL' if raw_side == 'SLD' else raw_side
        
        wal_entry = {
            'exec_id': str(exec_id),
            'ibkr_time': str(exec_obj.time),
            'symbol': symbol,
            'side': side,
            'quantity': int(exec_obj.shares),
            'price': float(exec_obj.price),
            'commission': float(commission),
            'exchange': exec_obj.exchange,
            'ibkr_order_id': exec_obj.orderId,
            'ibkr_perm_id': exec_obj.permId,
            'source': source,
            'received_at': datetime.now(timezone.utc).isoformat()
        }
        self._write_wal(wal_entry)
    
    def _write_wal(self, entry: dict):
        """Write to local WAL file (sync)."""
        try:
            wal_file = self.wal_dir / f"fills_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
            with self._lock:
                with open(wal_file, 'a') as f:
                    f.write(json.dumps(entry) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
        except Exception as e:
            logger.error(f"WAL write failed: {e}", exc_info=True)
    
    def _process_wal_loop(self):
        """Process WAL entries to database."""
        while self._running:
            try:
                self._flush_wal_to_db()
            except Exception as e:
                logger.error(f"WAL processing error: {e}")
            time.sleep(self._wal_flush_interval_sec)
    
    def _flush_wal_to_db(self):
        """Read WAL and insert to database - only new entries since last flush."""
        wal_file = self.wal_dir / f"fills_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        pos_file = self.wal_dir / f".fills_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pos"
        if not wal_file.exists():
            return
        
        # Read last processed position
        last_pos = 0
        if pos_file.exists():
            try:
                last_pos = int(pos_file.read_text().strip())
            except (ValueError, OSError):
                last_pos = 0
        
        # Check if file has new content
        file_size = wal_file.stat().st_size
        if last_pos >= file_size:
            return
        
        conn = self.pool.getconn()
        cur = conn.cursor()
        processed = 0
        try:
            with open(wal_file, 'r') as f:
                f.seek(last_pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not entry.get("exec_id"):
                        continue
                    if not entry.get("received_at"):
                        entry["received_at"] = datetime.now(timezone.utc).isoformat()
                    cur.execute("SAVEPOINT wal_line")
                    try:
                        self._insert_execution(conn, entry)
                        processed += 1
                    except Exception as exc:
                        cur.execute("ROLLBACK TO SAVEPOINT wal_line")
                        logger.error(f"DB insert error: {exc}")
                new_pos = f.tell()
            conn.commit()
            pos_file.write_text(str(new_pos))
            if processed > 0:
                logger.info(f"WAL flush: {processed} entries processed")
        except Exception as e:
            conn.rollback()
            logger.error(f"WAL flush error: {e}")
        finally:
            self.pool.putconn(conn)
    
    def _insert_execution(self, conn, entry: dict):
        """Insert execution with ON CONFLICT (deduplication)."""
        cur = conn.cursor()
        trade_id, system = self._lookup_trade_link(cur, entry.get("ibkr_order_id"))
        received_at = self._parse_dt(entry.get("received_at"))
        ibkr_time = self._parse_dt(entry.get("ibkr_time"))
        cur.execute("""
            INSERT INTO executions (
                exec_id, received_at, ibkr_time, symbol, system, side,
                quantity, price, commission, exchange, ibkr_order_id,
                ibkr_perm_id, trade_id, source, raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (exec_id) DO NOTHING
            RETURNING exec_id
        """, (
            entry['exec_id'],
            received_at,
            ibkr_time,
            entry['symbol'],
            system,
            entry['side'],
            entry['quantity'],
            entry['price'],
            entry['commission'],
            entry['exchange'],
            entry['ibkr_order_id'],
            entry.get('ibkr_perm_id'),
            trade_id,
            entry['source'],
            json.dumps(entry),
        ))
        result = cur.fetchone()
        if result:
            logger.info(f"FILL INSERTED: {entry['symbol']} {entry['side']} {entry['quantity']}@{entry['price']} "
                       f"exec_id={entry['exec_id']} order={entry['ibkr_order_id']} trade={trade_id}")
            self._update_trade_from_execution(conn, entry, trade_id)

    def _call_ib(self, func, *args, timeout: float | None = None, **kwargs):
        if self.ib_call is None:
            if not self._ib_call_warned:
                logger.warning(
                    "UnifiedFillProcessor ib_call not provided; background IBKR calls "
                    "may fail if executed off the event loop."
                )
                self._ib_call_warned = True
            return func(*args, **kwargs)
        return self.ib_call(func, *args, timeout=timeout, **kwargs)

    def _lookup_trade_link(self, cur, ibkr_order_id: Optional[int]) -> tuple[Optional[str], str]:
        """Get trade_id/system for an order id."""
        if not ibkr_order_id:
            return None, "unknown"
        cur.execute("""
            SELECT trade_id, system
            FROM trade_order_links
            WHERE ibkr_order_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (ibkr_order_id,))
        row = cur.fetchone()
        if not row:
            return None, "unknown"
        return row[0], row[1] or "unknown"
    
    def _update_trade_from_execution(
        self,
        conn,
        entry: dict,
        trade_id: Optional[str] = None,
    ):
        """Update trade record with new fill."""
        cur = conn.cursor()
        if trade_id:
            cur.execute("""
                SELECT trade_id, direction, entry_fills, exit_fills, status
                FROM trades_v2
                WHERE trade_id = %s
            """, (trade_id,))
        else:
            # Look up trade by ibkr_order_id (linked at order placement time)
            cur.execute("""
                SELECT trade_id, direction, entry_fills, exit_fills, status
                FROM trades_v2
                WHERE trade_id = (
                    SELECT trade_id FROM executions
                    WHERE ibkr_order_id = %s AND trade_id IS NOT NULL
                    LIMIT 1
                )
            """, (entry.get('ibkr_order_id'),))
        row = cur.fetchone()
        if not row:
            return
        trade_id, direction, entry_fills, exit_fills, status = row
        fill_record = {
            'exec_id': entry['exec_id'], 'price': entry['price'],
            'qty': entry['quantity'], 'time': entry['ibkr_time'],
            'exchange': entry['exchange']
        }
        is_entry = (
            (direction == 'long' and entry['side'] == 'BUY') or
            (direction == 'short' and entry['side'] == 'SELL')
        )
        if is_entry and status == 'PENDING':
            fills = entry_fills or []
            fills.append(fill_record)
            vwap = sum(f['price'] * f['qty'] for f in fills) / sum(f['qty'] for f in fills)
            total_qty = sum(f['qty'] for f in fills)
            cur.execute("""
                UPDATE trades_v2 SET entry_fills = %s, entry_fill_count = %s,
                    entry_price = %s, entry_qty = %s, entry_time = COALESCE(entry_time, %s),
                    status = 'OPEN', updated_at = NOW()
                WHERE trade_id = %s
            """, (json.dumps(fills), len(fills), vwap, total_qty, entry['ibkr_time'], trade_id))
        else:
            fills = exit_fills or []
            fills.append(fill_record)
            vwap = sum(f['price'] * f['qty'] for f in fills) / sum(f['qty'] for f in fills)
            total_qty = sum(f['qty'] for f in fills)
            cur.execute("""
                UPDATE trades_v2 SET exit_fills = %s, exit_fill_count = %s,
                    exit_price = %s, exit_qty = %s, exit_time = %s, updated_at = NOW()
                WHERE trade_id = %s
            """, (json.dumps(fills), len(fills), vwap, total_qty, entry['ibkr_time'], trade_id))
            self._maybe_close_trade(conn, trade_id)
    
    def _maybe_close_trade(self, conn, trade_id: str):
        """Close trade if fully filled and calculate P&L."""
        cur = conn.cursor()
        cur.execute("""
            SELECT direction, entry_price, entry_qty, exit_price, exit_qty,
                   signal_price, entry_fills, exit_fills
            FROM trades_v2 WHERE trade_id = %s
        """, (trade_id,))
        row = cur.fetchone()
        if not row or not row[4] or row[4] < row[2]:
            return
        direction, entry_price, entry_qty, exit_price, exit_qty, signal_price, entry_fills, exit_fills = row
        gross_pnl = (exit_price - entry_price) * entry_qty if direction == 'long' else (entry_price - exit_price) * entry_qty
        total_comm = sum(f.get('commission', 0) for f in (entry_fills or [])) + sum(f.get('commission', 0) for f in (exit_fills or []))
        net_pnl = gross_pnl - total_comm
        cur.execute("SELECT EXTRACT(EPOCH FROM (exit_time - entry_time)) FROM trades_v2 WHERE trade_id = %s", (trade_id,))
        hold_seconds = cur.fetchone()[0] or 0
        cur.execute("""
            UPDATE trades_v2 SET gross_pnl = %s, total_commission = %s, net_pnl = %s,
                hold_seconds = %s, status = 'CLOSED', updated_at = NOW()
            WHERE trade_id = %s
        """, (gross_pnl, total_comm, net_pnl, hold_seconds, trade_id))
        logger.info(f"TRADE CLOSED: {trade_id} gross=${gross_pnl:.2f} net=${net_pnl:.2f}")
