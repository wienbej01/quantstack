# Trade Database Replacement Plan v2

**Date:** 2026-01-31  
**Status:** Design Complete  
**Timeline:** 4 weeks  
**Priority:** CRITICAL

---

## 1. Problem Statement

Current system has 80% fill recording failure rate due to unreliable `execDetailsEvent` callbacks. This causes:
- Incorrect P&L (using signal prices instead of fill prices)
- Missing trades (906 fills → 4 trades on Jan 30)
- No position reconciliation with IBKR

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FILL CAPTURE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   IBKR API                                                      │
│      │                                                          │
│      ├── Layer 1: execDetailsEvent callback                     │
│      ├── Layer 2: Trade.fills polling (500ms)                   │
│      └── Layer 3: reqExecutions() reconciliation (5min)         │
│      │                                                          │
│      ▼                                                          │
│   UnifiedFillProcessor                                          │
│      │                                                          │
│      ├── 1. Write to local WAL file (sync, durable)             │
│      │                                                          │
│      └── 2. Database writer (async)                             │
│             │                                                   │
│             ├── INSERT INTO executions (immutable log)          │
│             │                                                   │
│             └── UPSERT INTO trades (denormalized)               │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                         TABLES                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   executions ──── Source of truth, append-only                  │
│        │                                                        │
│        ▼                                                        │
│   trades ──────── Denormalized, computed from executions        │
│        │                                                        │
│        ▼                                                        │
│   positions ───── Current state, rebuilt on demand              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema

### 3.1 Executions Table (Source of Truth)

Immutable append-only log. Every fill from IBKR goes here exactly once.

```sql
CREATE TABLE executions (
    -- Primary key: IBKR's unique execution ID
    exec_id         VARCHAR(50) PRIMARY KEY,
    
    -- Timestamps
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ibkr_time       TIMESTAMPTZ NOT NULL,
    
    -- Identification
    symbol          VARCHAR(10) NOT NULL,
    system          VARCHAR(20) NOT NULL,
    
    -- Execution details
    side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity        INTEGER NOT NULL,
    price           DECIMAL(12,4) NOT NULL,
    commission      DECIMAL(10,4) DEFAULT 0,
    exchange        VARCHAR(20),
    
    -- Linking
    ibkr_order_id   INTEGER,
    ibkr_perm_id    INTEGER,
    trade_id        UUID,
    
    -- Capture metadata
    source          VARCHAR(20) NOT NULL CHECK (source IN ('CALLBACK', 'POLL', 'RECONCILE')),
    
    -- Full IBKR object for debugging
    raw_data        JSONB
);

CREATE INDEX idx_exec_time ON executions(ibkr_time);
CREATE INDEX idx_exec_symbol ON executions(symbol);
CREATE INDEX idx_exec_trade ON executions(trade_id);
CREATE INDEX idx_exec_received ON executions(received_at);
```

### 3.2 Trades Table (Denormalized)

Single table contains everything. No joins needed for reporting.

```sql
CREATE TABLE trades_v2 (
    trade_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Identification
    symbol              VARCHAR(10) NOT NULL,
    system              VARCHAR(20) NOT NULL,
    strategy            VARCHAR(50),
    substrategy         VARCHAR(50),
    direction           VARCHAR(5) NOT NULL CHECK (direction IN ('long', 'short')),
    
    -- Signal (embedded, not FK)
    signal_time         TIMESTAMPTZ,
    signal_price        DECIMAL(12,4),
    signal_strength     DECIMAL(8,4),
    signal_edge_bps     DECIMAL(8,2),
    signal_data         JSONB,  -- Full signal snapshot
    
    -- Entry
    entry_time          TIMESTAMPTZ,
    entry_price         DECIMAL(12,4),  -- VWAP of entry fills
    entry_qty           INTEGER,
    entry_slippage_bps  DECIMAL(8,2),
    entry_fills         JSONB DEFAULT '[]',  -- Array of {exec_id, price, qty, time}
    entry_fill_count    INTEGER DEFAULT 0,
    
    -- Exit
    exit_time           TIMESTAMPTZ,
    exit_price          DECIMAL(12,4),  -- VWAP of exit fills
    exit_qty            INTEGER,
    exit_slippage_bps   DECIMAL(8,2),
    exit_fills          JSONB DEFAULT '[]',
    exit_fill_count     INTEGER DEFAULT 0,
    exit_reason         VARCHAR(20),
    
    -- Stop/Target
    initial_stop        DECIMAL(12,4),
    current_stop        DECIMAL(12,4),
    initial_target      DECIMAL(12,4),
    current_target      DECIMAL(12,4),
    stop_adjustments    JSONB DEFAULT '[]',
    
    -- P&L (computed from actual fills)
    gross_pnl           DECIMAL(12,4),
    total_commission    DECIMAL(10,4) DEFAULT 0,
    net_pnl             DECIMAL(12,4),
    
    -- Timing
    hold_seconds        DECIMAL(12,2),
    signal_to_fill_ms   DECIMAL(12,2),
    
    -- Status
    status              VARCHAR(10) NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING', 'OPEN', 'CLOSED', 'CANCELLED')),
    
    -- Metadata
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_symbol ON trades_v2(symbol);
CREATE INDEX idx_trades_system ON trades_v2(system);
CREATE INDEX idx_trades_entry ON trades_v2(entry_time);
CREATE INDEX idx_trades_status ON trades_v2(status);
CREATE INDEX idx_trades_date ON trades_v2((entry_time::date));
```

### 3.3 Positions Table (Current State)

Rebuilt from executions. Single row per symbol per system.

```sql
CREATE TABLE positions (
    id                  SERIAL PRIMARY KEY,
    symbol              VARCHAR(10) NOT NULL,
    system              VARCHAR(20) NOT NULL,
    
    -- Current position
    quantity            INTEGER NOT NULL DEFAULT 0,
    avg_price           DECIMAL(12,4),
    
    -- P&L
    unrealized_pnl      DECIMAL(12,4) DEFAULT 0,
    realized_pnl        DECIMAL(12,4) DEFAULT 0,
    
    -- IBKR reconciliation
    ibkr_quantity       INTEGER,
    ibkr_avg_price      DECIMAL(12,4),
    last_reconcile      TIMESTAMPTZ,
    is_reconciled       BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    opened_at           TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(symbol, system)
);

CREATE INDEX idx_pos_symbol ON positions(symbol);
```

### 3.4 Data Retention & Partitioning

```sql
-- Partition executions by month for performance and archival
CREATE TABLE executions (
    -- ... columns as above ...
) PARTITION BY RANGE (received_at);

-- Create monthly partitions
CREATE TABLE executions_2026_01 PARTITION OF executions
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE executions_2026_02 PARTITION OF executions
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
-- ... create partitions for each month

-- Archival policy: Move partitions older than 1 year to cold storage
-- Run monthly: pg_dump executions_YYYY_MM | gzip > archive/executions_YYYY_MM.sql.gz
-- Then: DROP TABLE executions_YYYY_MM;
```

**Retention Policy:**
- `executions`: 1 year online, then archived to compressed SQL dumps
- `trades_v2`: Indefinite (relatively small volume)
- `positions`: Current state only, no archival needed

### 3.5 Write-Ahead Log Table (Durability)

Local backup in case of database failure.

```sql
CREATE TABLE wal_pending (
    id                  SERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    event_type          VARCHAR(20) NOT NULL,
    payload             JSONB NOT NULL,
    processed           BOOLEAN DEFAULT FALSE,
    processed_at        TIMESTAMPTZ,
    error_message       TEXT
);
```

---

## 4. Core Implementation

### 4.1 Unified Fill Processor

```python
"""
unified_fill_processor.py

Triple-layer fill capture with local WAL durability.
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import psycopg2
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


class UnifiedFillProcessor:
    """Captures fills from IBKR with 100% reliability."""
    
    def __init__(self, ib, db_config: dict, wal_dir: str = "data/wal"):
        self.ib = ib
        self.wal_dir = Path(wal_dir)
        self.wal_dir.mkdir(parents=True, exist_ok=True)
        
        # Connection pool for concurrent access
        self.pool = ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 5432),
            database=db_config.get('database', 'trading'),
            user=db_config.get('user'),
            password=db_config.get('password')
        )
        
        self._running = False
        self._lock = threading.Lock()
    
    def start(self):
        """Start all capture layers."""
        self._running = True
        
        # Layer 1: Event callback
        self.ib.execDetailsEvent += self._on_exec_details
        
        # Layer 2: Polling thread
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        
        # Layer 3: Reconciliation thread
        self._recon_thread = threading.Thread(target=self._reconcile_loop, daemon=True)
        self._recon_thread.start()
        
        # WAL processor thread
        self._wal_thread = threading.Thread(target=self._process_wal_loop, daemon=True)
        self._wal_thread.start()
        
        logger.info("UnifiedFillProcessor started")
    
    def stop(self):
        """Stop all capture layers."""
        self._running = False
        self.ib.execDetailsEvent -= self._on_exec_details
        self.pool.closeall()
    
    # ─────────────────────────────────────────────────────────────
    # Layer 1: Event Callback
    # ─────────────────────────────────────────────────────────────
    
    def _on_exec_details(self, trade, fill):
        """Handle execDetailsEvent callback."""
        self._process_fill(fill, source="CALLBACK")
    
    # ─────────────────────────────────────────────────────────────
    # Layer 2: Polling
    # ─────────────────────────────────────────────────────────────
    
    def _poll_loop(self):
        """Poll Trade.fills every 500ms."""
        while self._running:
            try:
                for trade in self.ib.trades():
                    for fill in trade.fills:
                        self._process_fill(fill, source="POLL")
            except Exception as e:
                logger.error(f"Poll error: {e}")
            time.sleep(0.5)
    
    # ─────────────────────────────────────────────────────────────
    # Layer 3: Reconciliation
    # ─────────────────────────────────────────────────────────────
    
    def _reconcile_loop(self):
        """Request all executions every 5 minutes."""
        while self._running:
            try:
                executions = self.ib.reqExecutions()
                for exec_detail in executions:
                    self._process_fill(exec_detail.execution, source="RECONCILE")
            except Exception as e:
                logger.error(f"Reconcile error: {e}")
            time.sleep(300)  # 5 minutes
    
    # ─────────────────────────────────────────────────────────────
    # Fill Processing (with deduplication)
    # ─────────────────────────────────────────────────────────────
    
    def _process_fill(self, fill, source: str):
        """Process fill with database-level deduplication."""
        exec_id = fill.execId
        
        # Step 1: Write to local WAL (sync, durable)
        wal_entry = {
            'exec_id': exec_id,
            'ibkr_time': str(fill.time),
            'symbol': fill.contract.symbol,
            'side': fill.side,
            'quantity': int(fill.shares),
            'price': float(fill.price),
            'commission': float(fill.commission) if fill.commission else 0,
            'exchange': fill.exchange,
            'ibkr_order_id': fill.orderId,
            'ibkr_perm_id': getattr(fill, 'permId', None),
            'source': source,
            'received_at': datetime.utcnow().isoformat()
        }
        self._write_wal(wal_entry)
        
        # Step 2: Insert to database (async via WAL processor)
        # Deduplication happens at database level via PRIMARY KEY
    
    def _write_wal(self, entry: dict):
        """Write to local WAL file (sync)."""
        wal_file = self.wal_dir / f"fills_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
        with self._lock:
            with open(wal_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
    
    def _process_wal_loop(self):
        """Process WAL entries to database."""
        while self._running:
            try:
                self._flush_wal_to_db()
            except Exception as e:
                logger.error(f"WAL processing error: {e}")
            time.sleep(1)
    
    def _flush_wal_to_db(self):
        """Read WAL and insert to database."""
        wal_file = self.wal_dir / f"fills_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
        if not wal_file.exists():
            return
        
        conn = self.pool.getconn()
        try:
            with open(wal_file, 'r') as f:
                for line in f:
                    entry = json.loads(line.strip())
                    self._insert_execution(conn, entry)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"DB insert error: {e}")
        finally:
            self.pool.putconn(conn)
    
    def _insert_execution(self, conn, entry: dict):
        """Insert execution with ON CONFLICT (deduplication)."""
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO executions (
                exec_id, received_at, ibkr_time, symbol, system, side,
                quantity, price, commission, exchange, ibkr_order_id,
                ibkr_perm_id, source, raw_data
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (exec_id) DO NOTHING
            RETURNING exec_id
        """, (
            entry['exec_id'],
            entry['received_at'],
            entry['ibkr_time'],
            entry['symbol'],
            self._get_system_for_order(entry.get('ibkr_perm_id')),
            entry['side'],
            entry['quantity'],
            entry['price'],
            entry['commission'],
            entry['exchange'],
            entry['ibkr_order_id'],
            entry.get('ibkr_perm_id'),
            entry['source'],
            json.dumps(entry)
        ))
        
        result = cur.fetchone()
        if result:
            # New execution inserted, update trade
            logger.info(f"FILL [{entry['source']}]: {entry['symbol']} "
                       f"{entry['side']} {entry['quantity']}@{entry['price']}")
            self._update_trade_from_execution(conn, entry)
    
    def _get_system_for_order(self, perm_id: Optional[int]) -> str:
        """Determine which system placed the order."""
        # TODO: Implement order tracking by system
        return "unknown"
    
    def _update_trade_from_execution(self, conn, entry: dict):
        """Update trade record with new fill."""
        # Find trade by order
        cur = conn.cursor()
        cur.execute("""
            SELECT trade_id, direction, entry_fills, exit_fills, status
            FROM trades_v2
            WHERE trade_id = (
                SELECT trade_id FROM executions 
                WHERE ibkr_perm_id = %s AND trade_id IS NOT NULL
                LIMIT 1
            )
        """, (entry.get('ibkr_perm_id'),))
        
        row = cur.fetchone()
        if not row:
            return
        
        trade_id, direction, entry_fills, exit_fills, status = row
        
        fill_record = {
            'exec_id': entry['exec_id'],
            'price': entry['price'],
            'qty': entry['quantity'],
            'time': entry['ibkr_time'],
            'exchange': entry['exchange']
        }
        
        # Determine if entry or exit fill
        is_entry = (
            (direction == 'long' and entry['side'] == 'BUY') or
            (direction == 'short' and entry['side'] == 'SELL')
        )
        
        if is_entry and status == 'PENDING':
            # Entry fill
            fills = entry_fills or []
            fills.append(fill_record)
            vwap = sum(f['price'] * f['qty'] for f in fills) / sum(f['qty'] for f in fills)
            total_qty = sum(f['qty'] for f in fills)
            
            cur.execute("""
                UPDATE trades_v2 SET
                    entry_fills = %s,
                    entry_fill_count = %s,
                    entry_price = %s,
                    entry_qty = %s,
                    entry_time = COALESCE(entry_time, %s),
                    status = 'OPEN',
                    updated_at = NOW()
                WHERE trade_id = %s
            """, (json.dumps(fills), len(fills), vwap, total_qty, 
                  entry['ibkr_time'], trade_id))
        else:
            # Exit fill
            fills = exit_fills or []
            fills.append(fill_record)
            vwap = sum(f['price'] * f['qty'] for f in fills) / sum(f['qty'] for f in fills)
            total_qty = sum(f['qty'] for f in fills)
            
            cur.execute("""
                UPDATE trades_v2 SET
                    exit_fills = %s,
                    exit_fill_count = %s,
                    exit_price = %s,
                    exit_qty = %s,
                    exit_time = %s,
                    updated_at = NOW()
                WHERE trade_id = %s
            """, (json.dumps(fills), len(fills), vwap, total_qty,
                  entry['ibkr_time'], trade_id))
            
            # Check if fully closed
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
        if not row:
            return
        
        direction, entry_price, entry_qty, exit_price, exit_qty, signal_price, entry_fills, exit_fills = row
        
        if not exit_qty or exit_qty < entry_qty:
            return  # Not fully closed
        
        # Calculate P&L
        if direction == 'long':
            gross_pnl = (exit_price - entry_price) * entry_qty
            entry_slip = (entry_price - signal_price) * 10000 / signal_price if signal_price else 0
            exit_slip = (signal_price - exit_price) * 10000 / signal_price if signal_price else 0
        else:
            gross_pnl = (entry_price - exit_price) * entry_qty
            entry_slip = (signal_price - entry_price) * 10000 / signal_price if signal_price else 0
            exit_slip = (exit_price - signal_price) * 10000 / signal_price if signal_price else 0
        
        # Sum commissions
        total_comm = sum(f.get('commission', 0) for f in (entry_fills or [])) + \
                     sum(f.get('commission', 0) for f in (exit_fills or []))
        
        net_pnl = gross_pnl - total_comm
        
        # Calculate hold time
        cur.execute("""
            SELECT EXTRACT(EPOCH FROM (exit_time - entry_time))
            FROM trades_v2 WHERE trade_id = %s
        """, (trade_id,))
        hold_seconds = cur.fetchone()[0] or 0
        
        cur.execute("""
            UPDATE trades_v2 SET
                gross_pnl = %s,
                total_commission = %s,
                net_pnl = %s,
                entry_slippage_bps = %s,
                exit_slippage_bps = %s,
                hold_seconds = %s,
                status = 'CLOSED',
                updated_at = NOW()
            WHERE trade_id = %s
        """, (gross_pnl, total_comm, net_pnl, entry_slip, exit_slip, hold_seconds, trade_id))
        
        logger.info(f"TRADE CLOSED: {trade_id} gross=${gross_pnl:.2f} net=${net_pnl:.2f}")
```


### 4.2 Trade Database Interface

```python
"""
trade_database.py

Simple interface for trade operations.
"""

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
            minconn=2, maxconn=10,
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 5432),
            database=db_config.get('database', 'trading'),
            user=db_config.get('user'),
            password=db_config.get('password')
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
        signal_data: dict = None
    ) -> str:
        """Create new trade record. Returns trade_id."""
        trade_id = str(uuid.uuid4())
        
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO trades_v2 (
                    trade_id, symbol, system, direction, strategy, substrategy,
                    signal_time, signal_price, signal_data,
                    initial_stop, current_stop, initial_target, current_target,
                    status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
            """, (
                trade_id, symbol, system, direction, strategy, substrategy,
                signal_time, signal_price, json.dumps(signal_data or {}),
                initial_stop, initial_stop, initial_target, initial_target
            ))
            conn.commit()
            return trade_id
        finally:
            self.pool.putconn(conn)
    
    def link_order_to_trade(self, trade_id: str, ibkr_perm_id: int, is_entry: bool):
        """Link IBKR order to trade for fill matching."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            # Update any existing executions with this perm_id
            cur.execute("""
                UPDATE executions SET trade_id = %s
                WHERE ibkr_perm_id = %s AND trade_id IS NULL
            """, (trade_id, ibkr_perm_id))
            conn.commit()
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
                cur.execute("""
                    SELECT * FROM trades_v2 WHERE status IN ('PENDING', 'OPEN')
                """)
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
    
    def update_stop(self, trade_id: str, new_stop: float, reason: str = None):
        """Update stop price with audit trail."""
        conn = self.pool.getconn()
        try:
            cur = conn.cursor()
            # Get current stop
            cur.execute("SELECT current_stop, stop_adjustments FROM trades_v2 WHERE trade_id = %s", (trade_id,))
            row = cur.fetchone()
            if not row:
                return
            
            old_stop, adjustments = row
            adjustments = adjustments or []
            adjustments.append({
                'time': datetime.utcnow().isoformat(),
                'old': float(old_stop) if old_stop else None,
                'new': new_stop,
                'reason': reason
            })
            
            cur.execute("""
                UPDATE trades_v2 SET 
                    current_stop = %s, 
                    stop_adjustments = %s,
                    updated_at = NOW()
                WHERE trade_id = %s
            """, (new_stop, json.dumps(adjustments), trade_id))
            conn.commit()
        finally:
            self.pool.putconn(conn)
    
    def close(self):
        """Close connection pool."""
        self.pool.closeall()
```

### 4.3 Position Tracker

```python
"""
position_tracker.py

Real-time position tracking with IBKR reconciliation.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class PositionTracker:
    """Tracks positions and reconciles with IBKR.
    
    Consistency Model: "Last Write Wins" with eventual consistency.
    - Fills update positions immediately via UPSERT
    - IBKR reconciliation runs every 5 minutes
    - Discrepancies logged but not auto-corrected (manual review required)
    - Race condition between fills and reconciliation accepted as tolerable
      since reconciliation only updates ibkr_* columns, not quantity/avg_price
    """
    
    def __init__(self, db: TradeDatabase, ib):
        self.db = db
        self.ib = ib
    
    def update_from_fill(self, symbol: str, system: str, side: str, qty: int, price: float):
        """Update position from fill."""
        conn = self.db.pool.getconn()
        try:
            cur = conn.cursor()
            
            # Get current position
            cur.execute("""
                SELECT quantity, avg_price, realized_pnl
                FROM positions WHERE symbol = %s AND system = %s
            """, (symbol, system))
            row = cur.fetchone()
            
            if row:
                old_qty, old_avg, realized = row
            else:
                old_qty, old_avg, realized = 0, 0, 0
            
            # Calculate new position
            if side == 'BUY':
                if old_qty >= 0:
                    # Adding to long or opening long
                    new_qty = old_qty + qty
                    new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty else 0
                else:
                    # Covering short
                    new_qty = old_qty + qty
                    pnl = (old_avg - price) * min(qty, abs(old_qty))
                    realized += pnl
                    new_avg = old_avg if new_qty < 0 else price
            else:  # SELL
                if old_qty <= 0:
                    # Adding to short or opening short
                    new_qty = old_qty - qty
                    new_avg = ((abs(old_qty) * old_avg) + (qty * price)) / abs(new_qty) if new_qty else 0
                else:
                    # Closing long
                    new_qty = old_qty - qty
                    pnl = (price - old_avg) * min(qty, old_qty)
                    realized += pnl
                    new_avg = old_avg if new_qty > 0 else 0
            
            # Upsert position
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
        
        # Get IBKR positions
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
            
            # Find discrepancies
            all_symbols = set(ibkr_positions.keys()) | set(db_positions.keys())
            
            for symbol in all_symbols:
                ibkr_qty = ibkr_positions.get(symbol, {}).get('quantity', 0)
                db_qty = db_positions.get(symbol, 0)
                
                if ibkr_qty != db_qty:
                    discrepancies.append({
                        'symbol': symbol,
                        'ibkr_qty': ibkr_qty,
                        'db_qty': db_qty,
                        'diff': ibkr_qty - db_qty
                    })
                    logger.warning(f"Position mismatch {symbol}: IBKR={ibkr_qty} DB={db_qty}")
            
            # Update IBKR columns
            for symbol, data in ibkr_positions.items():
                cur.execute("""
                    UPDATE positions SET
                        ibkr_quantity = %s,
                        ibkr_avg_price = %s,
                        last_reconcile = NOW(),
                        is_reconciled = (quantity = %s)
                    WHERE symbol = %s
                """, (data['quantity'], data['avg_price'], data['quantity'], symbol))
            
            conn.commit()
            
        finally:
            self.db.pool.putconn(conn)
        
        return discrepancies
```

---

## 5. System Integration

### 5.1 Integration Points

Each trading system needs minimal changes:

```python
# In each system's main.py

from trading_db import TradeDatabase, UnifiedFillProcessor

class TradingSystem:
    def __init__(self):
        # Initialize shared database
        self.db = TradeDatabase({
            'host': 'localhost',
            'database': 'trading',
            'user': 'jacobw',
            'password': 'trading123'
        })
        
        # Initialize fill processor (shared across systems)
        self.fill_processor = UnifiedFillProcessor(
            ib=self.ib,
            db_config={...}
        )
        self.fill_processor.start()
    
    def on_signal(self, signal):
        # Open trade in database
        trade_id = self.db.open_trade(
            symbol=signal.symbol,
            system='l2-scalping',  # or 'l2-vwap', 'intraday-paper'
            direction=signal.direction,
            signal_price=signal.price,
            signal_time=datetime.utcnow(),
            strategy=signal.strategy,
            initial_stop=signal.stop,
            initial_target=signal.target,
            signal_data=signal.to_dict()
        )
        
        # Place order
        order = self.place_order(signal)
        
        # Link order to trade
        self.db.link_order_to_trade(trade_id, order.permId, is_entry=True)
        
        return trade_id
```

### 5.2 Migration from Old System

```sql
-- Migrate existing trades to new schema
INSERT INTO trades_v2 (
    trade_id, symbol, system, direction, strategy,
    signal_time, signal_price,
    entry_time, entry_price, entry_qty,
    exit_time, exit_price, exit_qty, exit_reason,
    gross_pnl, total_commission, net_pnl,
    hold_seconds, status
)
SELECT 
    trade_id, symbol, 
    COALESCE(system, 'intraday-paper') as system,
    direction, strategy,
    entry_time::timestamptz as signal_time,
    COALESCE(signal_entry_price, entry_price) as signal_price,
    entry_time::timestamptz, entry_price, entry_qty,
    exit_time::timestamptz, exit_price, exit_qty, exit_reason,
    gross_pnl, commission, net_pnl,
    hold_time_seconds, status
FROM trades
WHERE NOT EXISTS (
    SELECT 1 FROM trades_v2 WHERE trades_v2.trade_id = trades.trade_id::uuid
);
```

---

## 6. Implementation Timeline

### Week 1: Foundation
| Day | Task | Deliverable |
|-----|------|-------------|
| 1 | Create schema | `schema.sql` executed |
| 2 | TradeDatabase class | Basic CRUD working |
| 3 | UnifiedFillProcessor | Triple-layer capture |
| 4 | Local WAL | Durability tested |
| 5 | Unit tests | 90% coverage |

### Week 2: Integration
| Day | Task | Deliverable |
|-----|------|-------------|
| 6-7 | l2-scalping integration | System using new DB |
| 8 | l2-vwap integration | System using new DB |
| 9 | intraday-paper integration | System using new DB |
| 10 | Position tracker | Reconciliation working |

### Week 3: Validation
| Day | Task | Deliverable |
|-----|------|-------------|
| 11-15 | Parallel running | Both systems recording |
| - | Compare fill counts | IBKR log vs DB |
| - | Validate P&L | Actual vs calculated |

### Week 4: Cutover
| Day | Task | Deliverable |
|-----|------|-------------|
| 16 | Data migration | Historical trades moved |
| 17 | Switch to new system | Old system disabled |
| 18-19 | Monitoring | Alerts configured |
| 20 | Documentation | Runbook complete |

---

## 7. Monitoring & Alerts

### 7.1 Key Metrics

```sql
-- Fill capture rate (should be 100%)
SELECT 
    source,
    COUNT(*) as fills,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as pct
FROM executions
WHERE received_at > NOW() - INTERVAL '1 day'
GROUP BY source;

-- Unlinked fills (should be 0)
SELECT COUNT(*) FROM executions WHERE trade_id IS NULL;

-- Position discrepancies
SELECT * FROM positions WHERE NOT is_reconciled;
```

### 7.2 Alerts

| Condition | Severity | Action |
|-----------|----------|--------|
| Fill capture < 95% | CRITICAL | Page on-call |
| Unlinked fills > 0 | WARNING | Investigate |
| Position mismatch | WARNING | Manual reconcile |
| WAL backlog > 100 | WARNING | Check DB connection |

---

## 8. Acceptance Criteria

- [ ] 100% fill capture rate (verified against IBKR API log)
- [ ] All fills linked to trades
- [ ] P&L calculated from actual fill prices
- [ ] Position reconciliation passes
- [ ] No duplicate fills (exec_id uniqueness)
- [ ] WAL durability tested (DB down scenario)
- [ ] All three systems integrated
- [ ] Parallel run for 5 trading days with zero discrepancies

---

## 9. Rollback Plan

If new system fails:

1. Stop new fill processor
2. Re-enable old event_store.py
3. Old tables remain intact (never deleted)
4. Investigate and fix
5. Re-attempt migration

Feature flag in each system:
```python
USE_NEW_DB = os.getenv('USE_NEW_TRADE_DB', 'false').lower() == 'true'
```

---

## Summary

This revised plan:

1. **Simplifies schema** to 3 tables (executions, trades, positions)
2. **Adds durability** via local WAL
3. **Uses database-level deduplication** (not in-memory)
4. **Handles partial fills** with VWAP calculation
5. **Extends timeline** to 4 weeks for proper testing
6. **Includes monitoring** from day 1
7. **Has rollback plan** with feature flags
