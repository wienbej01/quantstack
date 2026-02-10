# Trade Database Complete Replacement Plan

**Date:** 2026-01-31
**Status:** Design Phase
**Priority:** CRITICAL

## Executive Summary

Complete replacement of the current trade database system to address:
1. **80% fill recording failure rate** - execDetailsEvent callbacks not firing
2. **Incorrect P&L calculations** - using signal prices instead of actual fills
3. **Missing data** - no signal timestamps, order lifecycle, position tracking
4. **Fragmented systems** - 3 trading systems with inconsistent recording

## Part 1: Current System Analysis

### Current Database Schema (PostgreSQL `trading`)

```
Tables:
├── decisions    - ML/signal decisions (11 columns)
├── orders       - Order submissions (14 columns)  
├── fills        - Execution fills (12 columns)
├── trades       - Trade lifecycle (28 columns)
└── risk_events  - Risk control events (5 columns)
```

### Critical Gaps Identified

| Gap | Impact | Severity |
|-----|--------|----------|
| No signal timestamp | Can't measure signal-to-order latency | HIGH |
| No order state machine | Can't track order lifecycle | HIGH |
| No position table | Can't reconcile with IBKR | CRITICAL |
| No fill-to-trade linking | Fills orphaned from trades | CRITICAL |
| No substrategy field | Can't analyze strategy variants | MEDIUM |
| No stop/target adjustments | Can't track trailing stops | MEDIUM |
| TEXT timestamps | Poor query performance | MEDIUM |

### Trading Systems Integration Status

| System | Database | Fill Recording | Issues |
|--------|----------|----------------|--------|
| l2-scalping | PostgreSQL | TradeJournal class | 906 fills → 4 trades (Jan 30) |
| l2-vwap | PostgreSQL | event_store.py | Same callback issue |
| intraday-paper | PostgreSQL | event_store.py | 5 trades → 1 fill recorded |

### Root Cause: Fill Recording Failure

```
IBKR API → execDetailsEvent callback → NOT FIRING (80% failure)
         → Trade.fills list → ALWAYS POPULATED (ib_insync internal)
```

The `ib.execDetailsEvent += handler` callback is unreliable, but `Trade.fills` list is always maintained by ib_insync internally.

## Part 2: Data Points to Capture

### Signal Lifecycle
- `signal_id` (UUID)
- `signal_time` (TIMESTAMPTZ) - when signal generated
- `symbol`, `direction`, `strategy`, `substrategy`
- `signal_price` - price at signal generation
- `signal_strength`, `confidence`, `edge_bps`
- `l2_features` (JSONB) - L2 snapshot at signal time
- `market_context` (JSONB) - regime, volatility, spread
- `decision` - TRADE/NO_TRADE
- `rejection_reason`

### Order Lifecycle
- `order_id` (IBKR perm_id)
- `client_order_id` (our reference)
- `signal_id` (FK)
- `order_time` (TIMESTAMPTZ)
- `order_type` - MKT/LMT/IOC
- `limit_price`, `stop_price`, `target_price`
- `quantity`
- `status` - PENDING/SUBMITTED/PARTIAL/FILLED/CANCELLED/REJECTED
- `status_time` - last status change
- `tif` - DAY/IOC/GTC

### Fill Lifecycle
- `fill_id` (UUID)
- `exec_id` (IBKR execution ID)
- `order_id` (FK)
- `fill_time` (TIMESTAMPTZ)
- `fill_price`
- `fill_qty`
- `commission`
- `exchange`
- `liquidity` - ADD/REMOVE
- `latency_ms` - order_time to fill_time

### Trade Lifecycle
- `trade_id` (UUID)
- `signal_id` (FK)
- `entry_order_id`, `exit_order_id` (FK)
- Entry: `entry_time`, `entry_price`, `entry_qty`, `entry_slippage`
- Exit: `exit_time`, `exit_price`, `exit_qty`, `exit_slippage`, `exit_reason`
- Stops: `initial_stop`, `current_stop`, `stop_adjustments` (JSONB)
- Targets: `initial_target`, `current_target`, `target_adjustments` (JSONB)
- P&L: `gross_pnl`, `commission`, `net_pnl`
- Timing: `hold_time_seconds`, `time_to_fill_ms`
- Status: `status` - OPEN/CLOSED/PARTIAL

### Position Tracking
- `position_id` (UUID)
- `symbol`
- `quantity` - signed (+ long, - short)
- `avg_price`
- `unrealized_pnl`
- `realized_pnl`
- `last_update` (TIMESTAMPTZ)
- `ibkr_position` - IBKR reported position
- `reconciled` - boolean

### Risk Events
- `event_id` (UUID)
- `event_time` (TIMESTAMPTZ)
- `event_type` - CIRCUIT_BREAKER/PDT_REJECT/MAX_LOSS/EOD_FLATTEN
- `symbol`
- `details` (JSONB)


## Part 3: New Database Schema

### Database: PostgreSQL (existing `trading` database)

```sql
-- ============================================
-- SIGNALS TABLE - Signal generation events
-- ============================================
CREATE TABLE signals (
    signal_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_time     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Identification
    symbol          VARCHAR(10) NOT NULL,
    system          VARCHAR(20) NOT NULL,  -- l2-scalping, l2-vwap, intraday-paper
    strategy        VARCHAR(50) NOT NULL,
    substrategy     VARCHAR(50),
    
    -- Signal details
    direction       VARCHAR(5) NOT NULL CHECK (direction IN ('long', 'short')),
    signal_price    DECIMAL(12,4) NOT NULL,
    signal_strength DECIMAL(8,4),
    confidence      DECIMAL(5,4),
    edge_bps        DECIMAL(8,2),
    
    -- Context at signal time
    bid_price       DECIMAL(12,4),
    ask_price       DECIMAL(12,4),
    spread_bps      DECIMAL(8,2),
    l2_features     JSONB,
    market_context  JSONB,
    
    -- Decision
    decision        VARCHAR(10) NOT NULL CHECK (decision IN ('TRADE', 'NO_TRADE')),
    rejection_reason VARCHAR(100),
    
    -- Indexes
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_signals_time ON signals(signal_time);
CREATE INDEX idx_signals_symbol ON signals(symbol);
CREATE INDEX idx_signals_system ON signals(system);

-- ============================================
-- ORDERS TABLE - Order lifecycle tracking
-- ============================================
CREATE TABLE orders_v2 (
    order_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- IBKR identifiers
    ibkr_order_id   INTEGER,          -- IBKR's orderId
    ibkr_perm_id    INTEGER UNIQUE,   -- IBKR's permanent ID
    client_ref      VARCHAR(50),      -- Our reference string
    
    -- Relationships
    signal_id       UUID REFERENCES signals(signal_id),
    trade_id        UUID,             -- Set when trade opened
    
    -- Order details
    symbol          VARCHAR(10) NOT NULL,
    system          VARCHAR(20) NOT NULL,
    action          VARCHAR(4) NOT NULL CHECK (action IN ('BUY', 'SELL')),
    quantity        INTEGER NOT NULL,
    order_type      VARCHAR(10) NOT NULL,  -- MKT, LMT, IOC, STP, etc.
    limit_price     DECIMAL(12,4),
    stop_price      DECIMAL(12,4),
    tif             VARCHAR(10) DEFAULT 'DAY',
    
    -- Lifecycle timestamps
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    submitted_at    TIMESTAMPTZ,
    filled_at       TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,
    
    -- Status tracking
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    status_message  TEXT,
    filled_qty      INTEGER DEFAULT 0,
    avg_fill_price  DECIMAL(12,4),
    
    -- Purpose
    order_purpose   VARCHAR(10) CHECK (order_purpose IN ('ENTRY', 'EXIT', 'STOP', 'TARGET'))
);

CREATE INDEX idx_orders_v2_signal ON orders_v2(signal_id);
CREATE INDEX idx_orders_v2_trade ON orders_v2(trade_id);
CREATE INDEX idx_orders_v2_ibkr ON orders_v2(ibkr_perm_id);
CREATE INDEX idx_orders_v2_status ON orders_v2(status);
CREATE INDEX idx_orders_v2_created ON orders_v2(created_at);

-- ============================================
-- FILLS TABLE - Execution details
-- ============================================
CREATE TABLE fills_v2 (
    fill_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- IBKR identifiers
    exec_id         VARCHAR(50) UNIQUE NOT NULL,  -- IBKR execution ID
    
    -- Relationships
    order_id        UUID REFERENCES orders_v2(order_id),
    trade_id        UUID,
    
    -- Fill details
    symbol          VARCHAR(10) NOT NULL,
    system          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity        INTEGER NOT NULL,
    price           DECIMAL(12,4) NOT NULL,
    
    -- Execution details
    fill_time       TIMESTAMPTZ NOT NULL,
    exchange        VARCHAR(20),
    liquidity       VARCHAR(10),  -- ADD, REMOVE
    commission      DECIMAL(10,4) DEFAULT 0,
    
    -- Timing
    latency_ms      DECIMAL(10,2),  -- order submit to fill
    
    -- Source tracking
    source          VARCHAR(20) NOT NULL,  -- CALLBACK, POLL, RECONCILE
    
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fills_v2_order ON fills_v2(order_id);
CREATE INDEX idx_fills_v2_trade ON fills_v2(trade_id);
CREATE INDEX idx_fills_v2_time ON fills_v2(fill_time);
CREATE INDEX idx_fills_v2_exec ON fills_v2(exec_id);

-- ============================================
-- TRADES TABLE - Complete trade lifecycle
-- ============================================
CREATE TABLE trades_v2 (
    trade_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationships
    signal_id       UUID REFERENCES signals(signal_id),
    entry_order_id  UUID REFERENCES orders_v2(order_id),
    exit_order_id   UUID REFERENCES orders_v2(order_id),
    
    -- Identification
    symbol          VARCHAR(10) NOT NULL,
    system          VARCHAR(20) NOT NULL,
    strategy        VARCHAR(50),
    substrategy     VARCHAR(50),
    direction       VARCHAR(5) NOT NULL CHECK (direction IN ('long', 'short')),
    
    -- Entry
    entry_time      TIMESTAMPTZ,
    entry_price     DECIMAL(12,4),
    entry_qty       INTEGER,
    signal_entry_price DECIMAL(12,4),  -- Price at signal
    entry_slippage  DECIMAL(12,4),
    entry_fill_count INTEGER DEFAULT 0,
    
    -- Exit
    exit_time       TIMESTAMPTZ,
    exit_price      DECIMAL(12,4),
    exit_qty        INTEGER,
    signal_exit_price DECIMAL(12,4),
    exit_slippage   DECIMAL(12,4),
    exit_fill_count INTEGER DEFAULT 0,
    exit_reason     VARCHAR(20),  -- TARGET, STOP, FLATTEN, MANUAL, TIMEOUT
    
    -- Stop/Target management
    initial_stop    DECIMAL(12,4),
    current_stop    DECIMAL(12,4),
    initial_target  DECIMAL(12,4),
    current_target  DECIMAL(12,4),
    stop_adjustments JSONB DEFAULT '[]',
    target_adjustments JSONB DEFAULT '[]',
    
    -- P&L
    gross_pnl       DECIMAL(12,4),
    commission      DECIMAL(10,4) DEFAULT 0,
    net_pnl         DECIMAL(12,4),
    
    -- Timing
    hold_time_seconds DECIMAL(12,2),
    signal_to_fill_ms DECIMAL(12,2),
    
    -- Status
    status          VARCHAR(10) NOT NULL DEFAULT 'PENDING',
    
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_v2_signal ON trades_v2(signal_id);
CREATE INDEX idx_trades_v2_symbol ON trades_v2(symbol);
CREATE INDEX idx_trades_v2_system ON trades_v2(system);
CREATE INDEX idx_trades_v2_entry ON trades_v2(entry_time);
CREATE INDEX idx_trades_v2_status ON trades_v2(status);

-- ============================================
-- POSITIONS TABLE - Real-time position tracking
-- ============================================
CREATE TABLE positions (
    position_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    symbol          VARCHAR(10) NOT NULL,
    system          VARCHAR(20) NOT NULL,
    
    -- Position state
    quantity        INTEGER NOT NULL DEFAULT 0,  -- Signed: + long, - short
    avg_price       DECIMAL(12,4),
    
    -- P&L tracking
    unrealized_pnl  DECIMAL(12,4) DEFAULT 0,
    realized_pnl    DECIMAL(12,4) DEFAULT 0,
    
    -- IBKR reconciliation
    ibkr_quantity   INTEGER,
    ibkr_avg_price  DECIMAL(12,4),
    reconciled      BOOLEAN DEFAULT FALSE,
    last_reconcile  TIMESTAMPTZ,
    
    -- Timestamps
    opened_at       TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(symbol, system)
);

CREATE INDEX idx_positions_symbol ON positions(symbol);
CREATE INDEX idx_positions_system ON positions(system);

-- ============================================
-- RISK_EVENTS TABLE - Risk control events
-- ============================================
CREATE TABLE risk_events_v2 (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    system          VARCHAR(20) NOT NULL,
    event_type      VARCHAR(30) NOT NULL,
    symbol          VARCHAR(10),
    
    reason          TEXT,
    details         JSONB,
    
    -- Action taken
    action_taken    VARCHAR(50),
    
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_risk_events_time ON risk_events_v2(event_time);
CREATE INDEX idx_risk_events_type ON risk_events_v2(event_type);

-- ============================================
-- IBKR_RECONCILIATION TABLE - Daily reconciliation
-- ============================================
CREATE TABLE ibkr_reconciliation (
    recon_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recon_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- IBKR reported
    ibkr_positions  JSONB,
    ibkr_fills      JSONB,
    
    -- Our records
    db_positions    JSONB,
    db_fills        JSONB,
    
    -- Discrepancies
    position_diffs  JSONB,
    fill_diffs      JSONB,
    
    -- Resolution
    resolved        BOOLEAN DEFAULT FALSE,
    resolution_notes TEXT
);
```


## Part 4: IBKR Integration Architecture

### The Problem

```
Current: execDetailsEvent callback → 80% failure rate
         ↓
         Fills not recorded → Wrong P&L → Bad reports
```

### The Solution: Triple-Layer Fill Capture

```
┌─────────────────────────────────────────────────────────────┐
│                    IBKR FILL CAPTURE                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: EVENT CALLBACK (Primary)                          │
│  ├── ib.execDetailsEvent += _on_exec_details                │
│  ├── Immediate processing when callback fires               │
│  └── ~20% success rate currently                            │
│                                                             │
│  Layer 2: TRADE.FILLS POLLING (Fallback)                    │
│  ├── Poll Trade.fills list every 500ms                      │
│  ├── ib_insync maintains this list internally               │
│  ├── 100% reliable - always populated                       │
│  └── Catches callbacks that don't fire                      │
│                                                             │
│  Layer 3: IBKR RECONCILIATION (Safety Net)                  │
│  ├── ib.reqExecutions() - request all executions            │
│  ├── Run every 5 minutes during market hours                │
│  ├── Run at EOD before reports                              │
│  └── Catches any fills missed by Layer 1 & 2                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Implementation: Unified Fill Processor

```python
class UnifiedFillProcessor:
    """Triple-layer fill capture with deduplication."""
    
    def __init__(self, ib: IB, db: TradeDatabase):
        self.ib = ib
        self.db = db
        self.processed_exec_ids: set[str] = set()
        self._lock = threading.Lock()
        
    def start(self):
        """Initialize all three capture layers."""
        # Layer 1: Event callback
        self.ib.execDetailsEvent += self._on_exec_details
        
        # Layer 2: Polling thread
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True
        )
        self._poll_thread.start()
        
        # Layer 3: Reconciliation scheduler
        self._schedule_reconciliation()
    
    def _on_exec_details(self, trade: Trade, fill: Fill):
        """Layer 1: Event callback handler."""
        self._process_fill(fill, source="CALLBACK")
    
    def _poll_loop(self):
        """Layer 2: Poll Trade.fills for missed callbacks."""
        while self._running:
            for trade in self.ib.trades():
                for fill in trade.fills:
                    self._process_fill(fill, source="POLL")
            time.sleep(0.5)  # 500ms interval
    
    def _reconcile(self):
        """Layer 3: Request all executions from IBKR."""
        executions = self.ib.reqExecutions()
        for exec_detail in executions:
            fill = exec_detail.execution
            self._process_fill(fill, source="RECONCILE")
    
    def _process_fill(self, fill: Fill, source: str):
        """Process fill with deduplication."""
        with self._lock:
            exec_id = fill.execId
            if exec_id in self.processed_exec_ids:
                return  # Already processed
            
            self.processed_exec_ids.add(exec_id)
            
            # Record to database
            self.db.record_fill(
                exec_id=exec_id,
                order_id=fill.orderId,
                symbol=fill.contract.symbol,
                side=fill.side,
                quantity=fill.shares,
                price=fill.price,
                fill_time=fill.time,
                exchange=fill.exchange,
                commission=fill.commission,
                source=source
            )
            
            # Update trade with fill
            self._update_trade_from_fill(fill)
```

### Fill-to-Trade Linking

```python
def _update_trade_from_fill(self, fill: Fill):
    """Link fill to trade and update prices."""
    
    # Find order by IBKR order ID
    order = self.db.get_order_by_ibkr_id(fill.orderId)
    if not order:
        logger.warning(f"No order found for fill {fill.execId}")
        return
    
    # Find trade by order
    trade = self.db.get_trade_by_order(order.order_id)
    if not trade:
        return
    
    # Update trade with actual fill price
    if order.order_purpose == 'ENTRY':
        self.db.update_trade_entry(
            trade_id=trade.trade_id,
            entry_price=fill.price,
            entry_time=fill.time,
            entry_fill_count=trade.entry_fill_count + 1
        )
        # Recalculate entry slippage
        slippage = fill.price - trade.signal_entry_price
        if trade.direction == 'short':
            slippage = -slippage
        self.db.update_trade_slippage(trade.trade_id, entry_slippage=slippage)
        
    elif order.order_purpose in ('EXIT', 'STOP', 'TARGET'):
        self.db.update_trade_exit(
            trade_id=trade.trade_id,
            exit_price=fill.price,
            exit_time=fill.time,
            exit_fill_count=trade.exit_fill_count + 1,
            exit_reason=order.order_purpose
        )
        # Calculate P&L
        self._calculate_and_store_pnl(trade, fill)
```

### Position Reconciliation

```python
def reconcile_positions(self):
    """Reconcile database positions with IBKR."""
    
    # Get IBKR positions
    ibkr_positions = {
        p.contract.symbol: {
            'quantity': p.position,
            'avg_price': p.avgCost
        }
        for p in self.ib.positions()
    }
    
    # Get database positions
    db_positions = self.db.get_all_positions()
    
    discrepancies = []
    
    for symbol, ibkr_pos in ibkr_positions.items():
        db_pos = db_positions.get(symbol, {'quantity': 0})
        
        if ibkr_pos['quantity'] != db_pos['quantity']:
            discrepancies.append({
                'symbol': symbol,
                'ibkr_qty': ibkr_pos['quantity'],
                'db_qty': db_pos['quantity'],
                'diff': ibkr_pos['quantity'] - db_pos['quantity']
            })
            
            # Auto-correct database
            self.db.update_position(
                symbol=symbol,
                quantity=ibkr_pos['quantity'],
                avg_price=ibkr_pos['avg_price'],
                ibkr_quantity=ibkr_pos['quantity'],
                reconciled=True
            )
    
    if discrepancies:
        self.db.log_reconciliation(discrepancies)
        logger.warning(f"Position discrepancies found: {discrepancies}")
    
    return discrepancies
```

## Part 5: Implementation Plan

### Phase 1: Database Setup (Day 1)
1. Create new tables with `_v2` suffix (non-destructive)
2. Add indexes and constraints
3. Test connection pooling (multiple simultaneous connections)
4. Verify schema with sample data

### Phase 2: Unified Fill Processor (Day 2-3)
1. Create `UnifiedFillProcessor` class
2. Implement triple-layer capture
3. Add deduplication logic
4. Test with paper trading

### Phase 3: Trading System Integration (Day 4-6)
1. Create `TradeDatabase` class with all CRUD operations
2. Integrate with l2-scalping
3. Integrate with l2-vwap
4. Integrate with intraday-paper
5. Remove old event_store.py dependencies

### Phase 4: Position Tracking (Day 7)
1. Implement real-time position updates
2. Add IBKR reconciliation
3. Create position monitoring dashboard

### Phase 5: Migration & Validation (Day 8-10)
1. Run parallel recording (old + new)
2. Compare results
3. Validate fill capture rate
4. Switch to new system
5. Archive old tables

### Phase 6: Reporting (Day 11-12)
1. Update EOD report to use new schema
2. Add execution quality metrics
3. Create reconciliation reports

## Part 6: Testing Strategy

### Unit Tests
- Fill deduplication
- P&L calculations
- Slippage calculations
- Position tracking

### Integration Tests
- IBKR connection handling
- Fill capture from all three layers
- Database concurrent access

### Paper Trading Validation
- Run for 3 full trading days
- Compare fill counts: IBKR API log vs database
- Verify 100% fill capture rate
- Validate P&L accuracy

### Acceptance Criteria
- [ ] 100% fill capture rate (vs IBKR API log)
- [ ] All fills linked to trades
- [ ] P&L matches actual fills (not signal prices)
- [ ] Position reconciliation passes
- [ ] No duplicate fills
- [ ] All three trading systems integrated

## Part 7: File Structure

```
quantstack/
├── trading_db/
│   ├── __init__.py
│   ├── schema.sql              # All CREATE TABLE statements
│   ├── database.py             # TradeDatabase class
│   ├── fill_processor.py       # UnifiedFillProcessor
│   ├── position_tracker.py     # Position management
│   ├── reconciliation.py       # IBKR reconciliation
│   └── migrations/
│       ├── 001_create_tables.sql
│       └── 002_migrate_data.sql
├── l2_scalping/
│   └── src/
│       └── db_integration.py   # L2 scalping adapter
├── l2_vwap_reversion/
│   └── src/
│       └── db_integration.py   # L2 VWAP adapter
└── intraday_stack/
    └── src/
        └── journal/
            └── db_integration.py  # Intraday adapter
```

## Summary

This plan addresses all identified issues:

1. **Fill Recording**: Triple-layer capture ensures 100% fill recording
2. **Data Integrity**: Proper foreign keys and relationships
3. **Timestamps**: TIMESTAMPTZ for all time fields
4. **Position Tracking**: Real-time with IBKR reconciliation
5. **Multi-System**: Single database, unified schema
6. **Concurrent Access**: PostgreSQL handles multiple connections
7. **Audit Trail**: Complete lifecycle from signal to P&L
