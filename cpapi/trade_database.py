"""Trade database interface."""
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from psycopg2.pool import ThreadedConnectionPool


def _json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    item = getattr(obj, "item", None)
    if callable(item):
        return item()
    tolist = getattr(obj, "tolist", None)
    if callable(tolist):
        return tolist()
    raise TypeError(f"Type {type(obj)} not serializable")


def _coerce_datetime_value(value: datetime | float | int | str | None) -> datetime | None:
    """Accept epoch timestamps and ISO strings in canonical writers."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    raise TypeError(f"Unsupported datetime value: {type(value)}")


def _normalize_uuid_value(value: str | None) -> str | None:
    """Accept legacy string ids by mapping them into stable UUIDs."""
    if value in (None, ""):
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, str(value)))


class TradeDatabase:
    """Database interface for all trading systems."""
    
    def __init__(
        self,
        db_config: dict,
        pool: ThreadedConnectionPool | None = None,
        ensure_schema: bool = True,
    ):
        self._owns_pool = pool is None
        self.pool = pool or ThreadedConnectionPool(
            minconn=2, maxconn=10,
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 5432),
            database=db_config.get('database', 'trading'),
            user=db_config.get('user'),
            password=db_config.get('password')
        )
        if ensure_schema:
            self._ensure_schema_compatibility()

    def _ensure_schema_compatibility(self) -> None:
        """Apply compatibility migrations and canonical table creation."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            schema_path = Path(__file__).with_name("schema.sql")
            cur.execute(schema_path.read_text(encoding="utf-8"))
            cur.execute(
                "ALTER TABLE trades_v2 ADD COLUMN IF NOT EXISTS exit_order_id INTEGER"
            )
            cur.execute(
                "ALTER TABLE trade_order_links ADD COLUMN IF NOT EXISTS symbol VARCHAR(16)"
            )
            cur.execute(
                "ALTER TABLE orders_v2 DROP CONSTRAINT IF EXISTS orders_v2_ibkr_order_id_key"
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_orders_v2_ibkr_lookup
                ON orders_v2(ibkr_order_id, symbol, system, updated_at)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trade_order_links_order_symbol
                ON trade_order_links(ibkr_order_id, symbol, created_at)
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)

    @staticmethod
    def _slippage_bps(reference_price: float | None, actual_price: float | None, side: str | None) -> float | None:
        if reference_price in (None, 0) or actual_price is None or not side:
            return None
        reference = float(reference_price)
        actual = float(actual_price)
        side_upper = side.upper()
        if side_upper in {"BUY", "BOT", "LONG"}:
            return (actual - reference) / reference * 10000.0
        if side_upper in {"SELL", "SLD", "SHORT"}:
            return (reference - actual) / reference * 10000.0
        return None

    @staticmethod
    def _resolve_exit_reference_price(
        reason: str | None,
        exit_order_price: float | None,
        current_stop: float | None,
        current_target: float | None,
        exit_price: float | None,
    ) -> float | None:
        if exit_order_price is not None:
            return float(exit_order_price)
        if reason == "STOP_LOSS":
            return float(current_stop) if current_stop is not None else exit_price
        if reason == "TAKE_PROFIT":
            return float(current_target) if current_target is not None else exit_price
        return exit_price
    
    def open_trade(self, symbol: str, system: str, direction: str, signal_price: float,
                   signal_time: datetime, strategy: str = None, substrategy: str = None,
                   initial_stop: float = None, initial_target: float = None,
                   signal_data: dict = None) -> str:
        """Create new trade record. Returns trade_id."""
        trade_id = str(uuid.uuid4())
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO trades_v2 (
                    trade_id, symbol, system, direction, strategy, substrategy,
                    signal_time, signal_price, signal_data,
                    initial_stop, current_stop, initial_target, current_target, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
            """, (trade_id, symbol, system, direction, strategy, substrategy,
                  signal_time, signal_price, json.dumps(signal_data or {}, default=_json_serial),
                  initial_stop, initial_stop, initial_target, initial_target))
            conn.commit()
            return trade_id
        finally:
            self.pool.putconn(conn)

    def record_signal(
        self,
        *,
        system: str,
        symbol: str,
        strategy: str | None = None,
        substrategy: str | None = None,
        direction: str | None = None,
        signal_time: datetime | None = None,
        signal_price: float | None = None,
        signal_strength: float | None = None,
        signal_edge_bps: float | None = None,
        decision: str = "TRADE",
        rejection_reason: str | None = None,
        features: dict[str, Any] | None = None,
        raw_signal: dict[str, Any] | None = None,
        signal_id: str | None = None,
        conn=None,
    ) -> str:
        """Persist a canonical strategy signal row."""
        own_conn = conn is None
        conn = conn or self.pool.getconn()
        signal_id = _normalize_uuid_value(signal_id) or str(uuid.uuid4())
        signal_time = _coerce_datetime_value(signal_time) or datetime.now(timezone.utc)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO signals_v2 (
                    signal_id, system, symbol, strategy, substrategy, direction,
                    signal_time, signal_price, signal_strength, signal_edge_bps,
                    decision, rejection_reason, features, raw_signal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    signal_id,
                    system,
                    symbol,
                    strategy,
                    substrategy,
                    direction,
                    signal_time,
                    signal_price,
                    signal_strength,
                    signal_edge_bps,
                    decision,
                    rejection_reason,
                    json.dumps(features or {}, default=_json_serial),
                    json.dumps(raw_signal or {}, default=_json_serial),
                ),
            )
            if own_conn:
                conn.commit()
            return signal_id
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                self.pool.putconn(conn)

    def upsert_order(
        self,
        *,
        system: str,
        symbol: str,
        ibkr_order_id: int | None = None,
        ibkr_perm_id: int | None = None,
        trade_id: str | None = None,
        signal_id: str | None = None,
        side: str | None = None,
        order_type: str | None = None,
        role: str | None = None,
        parent_ibkr_order_id: int | None = None,
        order_ref: str | None = None,
        quantity: int | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        target_price: float | None = None,
        status: str = "CREATED",
        submitted_at: datetime | None = None,
        last_event_time: datetime | None = None,
        raw_order: dict[str, Any] | None = None,
        order_id: str | None = None,
        conn=None,
    ) -> str:
        """Insert or update a canonical order row."""
        own_conn = conn is None
        conn = conn or self.pool.getconn()
        order_id = _normalize_uuid_value(order_id) or str(uuid.uuid4())
        trade_id = _normalize_uuid_value(trade_id)
        signal_id = _normalize_uuid_value(signal_id)
        submitted_at = _coerce_datetime_value(submitted_at)
        last_event_time = _coerce_datetime_value(last_event_time)
        try:
            cur = conn.cursor()
            if ibkr_order_id is not None:
                if trade_id:
                    cur.execute(
                        """
                        SELECT order_id
                        FROM orders_v2
                        WHERE ibkr_order_id = %s
                          AND symbol = %s
                          AND system = %s
                          AND trade_id = %s
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (ibkr_order_id, symbol, system, trade_id),
                    )
                elif order_ref:
                    cur.execute(
                        """
                        SELECT order_id
                        FROM orders_v2
                        WHERE ibkr_order_id = %s
                          AND symbol = %s
                          AND system = %s
                          AND order_ref = %s
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (ibkr_order_id, symbol, system, order_ref),
                    )
                else:
                    cur.execute(
                        """
                        SELECT order_id
                        FROM orders_v2
                        WHERE ibkr_order_id = %s
                          AND symbol = %s
                          AND system = %s
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (ibkr_order_id, symbol, system),
                    )
                row = cur.fetchone()
                raw_order_json = json.dumps(raw_order or {}, default=_json_serial)
                if row:
                    stored_order_id = row[0]
                    cur.execute(
                        """
                        UPDATE orders_v2
                        SET ibkr_perm_id = COALESCE(%s, ibkr_perm_id),
                            trade_id = COALESCE(%s, trade_id),
                            signal_id = COALESCE(%s, signal_id),
                            side = COALESCE(%s, side),
                            order_type = COALESCE(%s, order_type),
                            role = COALESCE(%s, role),
                            parent_ibkr_order_id = COALESCE(%s, parent_ibkr_order_id),
                            order_ref = COALESCE(%s, order_ref),
                            quantity = COALESCE(%s, quantity),
                            limit_price = COALESCE(%s, limit_price),
                            stop_price = COALESCE(%s, stop_price),
                            target_price = COALESCE(%s, target_price),
                            status = COALESCE(%s, status),
                            submitted_at = COALESCE(%s, submitted_at),
                            last_event_time = COALESCE(%s, last_event_time),
                            raw_order = CASE
                                WHEN %s::jsonb = '{}'::jsonb THEN raw_order
                                ELSE %s::jsonb
                            END,
                            updated_at = NOW()
                        WHERE order_id = %s
                        """,
                        (
                            ibkr_perm_id,
                            trade_id,
                            signal_id,
                            side,
                            order_type,
                            role,
                            parent_ibkr_order_id,
                            order_ref,
                            quantity,
                            limit_price,
                            stop_price,
                            target_price,
                            status,
                            submitted_at,
                            last_event_time,
                            raw_order_json,
                            raw_order_json,
                            stored_order_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO orders_v2 (
                            order_id, ibkr_order_id, ibkr_perm_id, trade_id, signal_id,
                            system, symbol, side, order_type, role, parent_ibkr_order_id,
                            order_ref, quantity, limit_price, stop_price, target_price,
                            status, submitted_at, last_event_time, raw_order
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                        RETURNING order_id
                        """,
                        (
                            order_id,
                            ibkr_order_id,
                            ibkr_perm_id,
                            trade_id,
                            signal_id,
                            system,
                            symbol,
                            side,
                            order_type,
                            role,
                            parent_ibkr_order_id,
                            order_ref,
                            quantity,
                            limit_price,
                            stop_price,
                            target_price,
                            status,
                            submitted_at,
                            last_event_time,
                            raw_order_json,
                        ),
                    )
                    stored_order_id = cur.fetchone()[0]
            else:
                cur.execute(
                    """
                    INSERT INTO orders_v2 (
                        order_id, ibkr_perm_id, trade_id, signal_id, system, symbol,
                        side, order_type, role, parent_ibkr_order_id, order_ref,
                        quantity, limit_price, stop_price, target_price, status,
                        submitted_at, last_event_time, raw_order
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING order_id
                    """,
                    (
                        order_id,
                        ibkr_perm_id,
                        trade_id,
                        signal_id,
                        system,
                        symbol,
                        side,
                        order_type,
                        role,
                        parent_ibkr_order_id,
                        order_ref,
                        quantity,
                        limit_price,
                        stop_price,
                        target_price,
                        status,
                        submitted_at,
                        last_event_time,
                        json.dumps(raw_order or {}, default=_json_serial),
                    ),
                )
                stored_order_id = cur.fetchone()[0]
            if own_conn:
                conn.commit()
            return str(stored_order_id)
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                self.pool.putconn(conn)

    def append_order_event(
        self,
        *,
        system: str,
        event_type: str,
        ibkr_order_id: int | None = None,
        order_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        message: str | None = None,
        event_time: datetime | None = None,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
        conn=None,
    ) -> str:
        """Append an immutable canonical order lifecycle event."""
        own_conn = conn is None
        conn = conn or self.pool.getconn()
        event_id = _normalize_uuid_value(event_id) or str(uuid.uuid4())
        order_id = _normalize_uuid_value(order_id)
        event_time = _coerce_datetime_value(event_time) or datetime.now(timezone.utc)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO order_events_v2 (
                    event_id, order_id, ibkr_order_id, system, symbol, event_type,
                    status, message, event_time, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id,
                    order_id,
                    ibkr_order_id,
                    system,
                    symbol,
                    event_type,
                    status,
                    message,
                    event_time,
                    json.dumps(payload or {}, default=_json_serial),
                ),
            )
            if ibkr_order_id is not None:
                cur.execute(
                    """
                    WITH target AS (
                        SELECT order_id
                        FROM orders_v2
                        WHERE ibkr_order_id = %s
                          AND system = %s
                          AND (%s IS NULL OR symbol = %s)
                        ORDER BY updated_at DESC
                        LIMIT 1
                    )
                    UPDATE orders_v2
                    SET last_event_time = %s,
                        status = COALESCE(%s, status),
                        updated_at = NOW()
                    WHERE order_id IN (SELECT order_id FROM target)
                    """,
                    (ibkr_order_id, system, symbol, symbol, event_time, status),
                )
            elif order_id is not None:
                cur.execute(
                    """
                    UPDATE orders_v2
                    SET last_event_time = %s,
                        status = COALESCE(%s, status),
                        updated_at = NOW()
                    WHERE order_id = %s
                    """,
                    (event_time, status, order_id),
                )
            if own_conn:
                conn.commit()
            return event_id
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                self.pool.putconn(conn)
    
    def link_order_to_trade(
        self,
        trade_id: str,
        ibkr_order_id: int,
        is_entry: bool,
        system: str | None = None,
        symbol: str | None = None,
    ):
        """Link IBKR order to trade for fill matching by order_id + symbol."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            # Resolve symbol from trade if not provided
            if not symbol:
                cur.execute("SELECT symbol FROM trades_v2 WHERE trade_id = %s", (trade_id,))
                row = cur.fetchone()
                if row:
                    symbol = row[0]

            cur.execute("""
                INSERT INTO trade_order_links (trade_id, ibkr_order_id, symbol, system, is_entry)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (trade_id, ibkr_order_id) DO NOTHING
            """, (trade_id, ibkr_order_id, symbol, system, is_entry))
            # Link by ibkr_order_id + symbol to prevent cross-symbol contamination
            if symbol:
                cur.execute("""
                    UPDATE executions
                    SET trade_id = %s,
                        system = COALESCE(NULLIF(system, 'unknown'), %s)
                    WHERE ibkr_order_id = %s AND symbol = %s AND trade_id IS NULL
                """, (trade_id, system or 'unknown', ibkr_order_id, symbol))
            else:
                cur.execute("""
                    UPDATE executions SET trade_id = %s
                    WHERE ibkr_order_id = %s AND trade_id IS NULL
                """, (trade_id, ibkr_order_id))
            # Backfill any existing executions for this order into trades_v2
            self._backfill_trade_from_executions(
                cur,
                trade_id,
                ibkr_order_id,
                symbol,
                is_entry_order=is_entry,
            )
            conn.commit()
        finally:
            self.pool.putconn(conn)

    def _backfill_trade_from_executions(
        self,
        cur,
        trade_id: str,
        ibkr_order_id: int,
        symbol: str | None = None,
        is_entry_order: bool | None = None,
    ) -> None:
        """Apply existing executions to trades_v2 if fills arrived before linking."""
        if symbol:
            cur.execute("""
                SELECT exec_id, price, quantity, side, ibkr_time, exchange, commission
                FROM executions
                WHERE trade_id = %s AND ibkr_order_id = %s AND symbol = %s
                ORDER BY ibkr_time
            """, (trade_id, ibkr_order_id, symbol))
        else:
            cur.execute("""
                SELECT exec_id, price, quantity, side, ibkr_time, exchange, commission
                FROM executions
                WHERE trade_id = %s AND ibkr_order_id = %s
                ORDER BY ibkr_time
            """, (trade_id, ibkr_order_id))
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
                ibkr_order_id=ibkr_order_id,
                is_entry_order=is_entry_order,
            )

    def apply_execution_to_trade(
        self,
        trade_id: str,
        exec_id: str,
        price: float,
        quantity: int,
        side: str,
        ibkr_time,
        exchange: str | None,
        commission: float,
        ibkr_order_id: int | None = None,
        is_entry_order: bool | None = None,
        conn=None,
    ) -> None:
        """Apply a single execution to trades_v2 using the canonical fill path."""
        own_conn = conn is None
        conn = conn or self.pool.getconn()
        try:
            cur = conn.cursor()
            self._apply_execution_to_trade(
                cur,
                trade_id=trade_id,
                exec_id=exec_id,
                price=price,
                quantity=quantity,
                side=side,
                ibkr_time=ibkr_time,
                exchange=exchange,
                commission=commission,
                ibkr_order_id=ibkr_order_id,
                is_entry_order=is_entry_order,
            )
            if own_conn:
                conn.commit()
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                self.pool.putconn(conn)

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
        ibkr_order_id: int | None = None,
        is_entry_order: bool | None = None,
    ) -> None:
        """Apply a single execution to trades_v2 (idempotent)."""
        cur.execute("""
            SELECT direction, entry_fills, exit_fills, status, signal_price
            FROM trades_v2
            WHERE trade_id = %s
        """, (trade_id,))
        row = cur.fetchone()
        if not row:
            return
        direction, entry_fills, exit_fills, status, signal_price = row
        fill_record = {
            'exec_id': exec_id,
            'ibkr_order_id': ibkr_order_id,
            'price': price,
            'qty': quantity,
            'side': side,
            'time': ibkr_time,
            'exchange': exchange,
            'commission': commission,
        }

        if is_entry_order is None:
            is_entry_fill = (
                (direction == 'long' and side == 'BUY') or
                (direction == 'short' and side == 'SELL')
            )
        else:
            is_entry_fill = bool(is_entry_order)

        if is_entry_fill:
            fills = entry_fills or []
            if any(f.get('exec_id') == exec_id for f in fills):
                return
            fills.append(fill_record)
            vwap = sum(f['price'] * f['qty'] for f in fills) / sum(f['qty'] for f in fills)
            total_qty = sum(f['qty'] for f in fills)
            cur.execute("""
                UPDATE trades_v2 SET entry_fills = %s, entry_fill_count = %s,
                    entry_price = %s, entry_qty = %s, entry_time = COALESCE(entry_time, %s),
                    entry_slippage_bps = %s,
                    signal_to_fill_ms = COALESCE(
                        signal_to_fill_ms,
                        CASE
                            WHEN signal_time IS NULL THEN NULL
                            ELSE EXTRACT(EPOCH FROM (%s - signal_time)) * 1000
                        END
                    ),
                    status = CASE WHEN status = 'CLOSED' THEN status ELSE 'OPEN' END,
                    updated_at = NOW()
                WHERE trade_id = %s
            """, (
                json.dumps(fills, default=_json_serial),
                len(fills),
                vwap,
                total_qty,
                ibkr_time,
                self._slippage_bps(signal_price, vwap, side),
                ibkr_time,
                trade_id,
            ))
            return

        fills = exit_fills or []
        if any(f.get('exec_id') == exec_id for f in fills):
            return
        fills.append(fill_record)
        vwap = sum(f['price'] * f['qty'] for f in fills) / sum(f['qty'] for f in fills)
        total_qty = sum(f['qty'] for f in fills)
        cur.execute("""
            UPDATE trades_v2 SET exit_fills = %s, exit_fill_count = %s,
                exit_price = %s, exit_qty = %s, exit_time = %s, updated_at = NOW()
            WHERE trade_id = %s
        """, (json.dumps(fills, default=_json_serial), len(fills), vwap, total_qty, ibkr_time, trade_id))
        self._maybe_close_trade(cur, trade_id, exit_order_id=ibkr_order_id)

    def _maybe_close_trade(
        self,
        cur,
        trade_id: str,
        exit_order_id: int | None = None,
    ) -> None:
        """Close trade if fully filled and calculate P&L."""
        cur.execute("""
            SELECT direction, entry_price, entry_qty, exit_price, exit_qty,
                   entry_fills, exit_fills, exit_reason
            FROM trades_v2 WHERE trade_id = %s
        """, (trade_id,))
        row = cur.fetchone()
        if not row or not row[2] or not row[4] or row[4] < row[2]:
            return
        direction, entry_price, entry_qty, exit_price, exit_qty, entry_fills, exit_fills, exit_reason = row
        entry_px = float(entry_price)
        exit_px = float(exit_price)
        trade_qty = int(entry_qty)
        gross_pnl = (
            (exit_px - entry_px) * trade_qty
            if direction == 'long'
            else (entry_px - exit_px) * trade_qty
        )
        total_comm = sum(f.get('commission', 0) for f in (entry_fills or [])) + sum(
            f.get('commission', 0) for f in (exit_fills or [])
        )
        net_pnl = gross_pnl - total_comm
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM (exit_time - entry_time)) FROM trades_v2 WHERE trade_id = %s",
            (trade_id,),
        )
        hold_seconds = cur.fetchone()[0] or 0
        cur.execute("""
            UPDATE trades_v2 SET gross_pnl = %s, total_commission = %s, net_pnl = %s,
                hold_seconds = %s, exit_order_id = COALESCE(%s, exit_order_id),
                exit_reason = COALESCE(%s, exit_reason),
                status = 'CLOSED', updated_at = NOW()
            WHERE trade_id = %s
        """, (gross_pnl, total_comm, net_pnl, hold_seconds, exit_order_id, exit_reason, trade_id))

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_qty: int,
        pnl: float | None = None,
        reason: str | None = "SIGNAL_EXIT",
        exit_order_id: int | None = None,
        gross_pnl: float | None = None,
        commission: float | None = None,
        hold_seconds: float | None = None,
        exit_time: datetime | None = None,
    ) -> bool:
        """Explicitly close a trade and persist all canonical close metadata."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT direction, entry_price, entry_qty, entry_time, entry_fills, exit_fills,
                       total_commission, exit_time, current_stop, current_target, status
                FROM trades_v2
                WHERE trade_id = %s
            """, (trade_id,))
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return False

            (
                direction,
                entry_price,
                entry_qty,
                entry_time_db,
                entry_fills,
                exit_fills,
                total_commission_db,
                exit_time_db,
                current_stop,
                current_target,
                status,
            ) = row

            if status == "CLOSED" and exit_time_db is not None:
                conn.rollback()
                return False

            computed_gross = None
            if entry_price is not None and entry_qty:
                computed_gross = (
                    (float(exit_price) - float(entry_price)) * int(entry_qty)
                    if direction == "long"
                    else (float(entry_price) - float(exit_price)) * int(entry_qty)
                )

            effective_commission = commission
            if effective_commission is None:
                if total_commission_db is not None:
                    effective_commission = float(total_commission_db)
                else:
                    effective_commission = sum(
                        float(fill.get("commission", 0.0))
                        for fill in (entry_fills or []) + (exit_fills or [])
                    )

            effective_gross = (
                float(gross_pnl)
                if gross_pnl is not None
                else (computed_gross if computed_gross is not None else float(pnl or 0.0))
            )
            effective_net = (
                float(pnl)
                if pnl is not None and gross_pnl is None and commission is None and computed_gross is None
                else effective_gross - float(effective_commission or 0.0)
            )

            effective_exit_time = exit_time_db or exit_time or datetime.now(timezone.utc)
            effective_hold_seconds = hold_seconds
            if effective_hold_seconds is None and entry_time_db and effective_exit_time:
                effective_hold_seconds = (
                    effective_exit_time - entry_time_db
                ).total_seconds()

            exit_order_price = None
            if exit_order_id is not None:
                cur.execute(
                    """
                    SELECT COALESCE(limit_price, stop_price, target_price)
                    FROM orders_v2
                    WHERE ibkr_order_id = %s AND trade_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (exit_order_id, trade_id),
                )
                exit_order_row = cur.fetchone()
                if exit_order_row:
                    exit_order_price = exit_order_row[0]
            exit_reference = self._resolve_exit_reference_price(
                reason,
                float(exit_order_price) if exit_order_price is not None else None,
                float(current_stop) if current_stop is not None else None,
                float(current_target) if current_target is not None else None,
                float(exit_price),
            )
            exit_slippage_bps = self._slippage_bps(
                exit_reference,
                exit_price,
                "SELL" if direction == "long" else "BUY",
            )

            cur.execute("""
                UPDATE trades_v2
                SET status = 'CLOSED',
                    exit_price = %s,
                    exit_qty = %s,
                    exit_time = %s,
                    exit_slippage_bps = %s,
                    exit_reason = %s,
                    exit_order_id = %s,
                    gross_pnl = %s,
                    total_commission = %s,
                    net_pnl = %s,
                    hold_seconds = %s,
                    updated_at = NOW()
                WHERE trade_id = %s
            """, (
                exit_price,
                exit_qty,
                effective_exit_time,
                exit_slippage_bps,
                reason,
                exit_order_id,
                effective_gross,
                effective_commission,
                effective_net,
                effective_hold_seconds,
                trade_id,
            ))
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)
    
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
                cur.execute("""
                    SELECT * FROM trades_v2 
                    WHERE status IN ('PENDING', 'OPEN') AND system = %s
                """, (system,))
            else:
                cur.execute("SELECT * FROM trades_v2 WHERE status IN ('PENDING', 'OPEN')")
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
                cur.execute("""
                    SELECT * FROM trades_v2 
                    WHERE entry_time::date = %s AND system = %s
                    ORDER BY entry_time
                """, (date_str, system))
            else:
                cur.execute("""
                    SELECT * FROM trades_v2 
                    WHERE entry_time::date = %s
                    ORDER BY entry_time
                """, (date_str,))
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            self.pool.putconn(conn)
    
    def set_initial_exits(self, trade_id: str, stop: float, target: float):
        """Set initial stop/target when computed after fill (fill-based exits)."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE trades_v2
                SET initial_stop = %s, current_stop = %s,
                    initial_target = %s, current_target = %s, updated_at = NOW()
                WHERE trade_id = %s AND initial_stop IS NULL
            """, (stop, stop, target, target, trade_id))
            conn.commit()
        finally:
            self.pool.putconn(conn)

    def update_stop(self, trade_id: str, new_stop: float, reason: str = None):
        """Update stop price with audit trail."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT current_stop, stop_adjustments FROM trades_v2 WHERE trade_id = %s", (trade_id,))
            row = cur.fetchone()
            if not row:
                return
            old_stop, adjustments = row
            adjustments = adjustments or []
            adjustments.append({
                'time': datetime.now(timezone.utc).isoformat(),
                'old': float(old_stop) if old_stop else None,
                'new': new_stop, 'reason': reason
            })
            cur.execute("""
                UPDATE trades_v2 SET current_stop = %s, stop_adjustments = %s, updated_at = NOW()
                WHERE trade_id = %s
            """, (new_stop, json.dumps(adjustments, default=_json_serial), trade_id))
            conn.commit()
        finally:
            self.pool.putconn(conn)
    
    def close(self):
        """Close connection pool."""
        if self._owns_pool:
            self.pool.closeall()
