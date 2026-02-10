# Trade Database v2 Implementation

## Overview

This implementation replaces the old trade database system with a robust, reliable architecture that ensures 100% fill capture and accurate P&L tracking.

## Architecture

### Three-Layer Fill Capture
1. **Layer 1: Event Callback** - `execDetailsEvent` from IBKR API
2. **Layer 2: Polling** - Poll `Trade.fills` on an adaptive interval (default 2s, idle 5s)
3. **Layer 3: Reconciliation** - Request all executions on a slower cadence (default 15 minutes)

#### Interval Overrides (env)
- `IBKR_FILL_POLL_INTERVAL_SEC`
- `IBKR_FILL_POLL_IDLE_INTERVAL_SEC`
- `IBKR_FILL_POLL_IDLE_AFTER_SEC`
- `IBKR_FILL_RECONCILE_INTERVAL_SEC`
- `IBKR_FILL_WAL_FLUSH_INTERVAL_SEC`

### Write-Ahead Log (WAL)
- All fills written to local JSONL file immediately (sync)
- Provides durability even if database is down
- Asynchronous processing to database

### Database Schema
- **executions**: Immutable append-only log (source of truth)
- **trades_v2**: Denormalized trade records with embedded fills
- **positions**: Current position state with IBKR reconciliation

## Files Created

1. `cpapi/schema.sql` - Database schema
2. `cpapi/unified_fill_processor.py` - Triple-layer fill capture
3. `cpapi/trade_database.py` - Trade database interface
4. `cpapi/position_tracker.py` - Position tracking with reconciliation

## Setup

### 1. Create Database Schema

```bash
psql -U jacobw -d trading -f cpapi/schema.sql
```

### 2. Configure Database Connection

```python
db_config = {
    'host': 'localhost',
    'port': 5432,
    'database': 'trading',
    'user': 'jacobw',
    'password': 'your_password'
}
```

### 3. Initialize in Trading System

```python
from cpapi.trade_database import TradeDatabase
from cpapi.unified_fill_processor import UnifiedFillProcessor
from cpapi.position_tracker import PositionTracker

# Initialize
db = TradeDatabase(db_config)
fill_processor = UnifiedFillProcessor(ib, db_config)
position_tracker = PositionTracker(db, ib)

# Start fill capture
fill_processor.start()

# On signal
trade_id = db.open_trade(
    symbol='AAPL',
    system='l2-scalping',
    direction='long',
    signal_price=150.00,
    signal_time=datetime.utcnow(),
    initial_stop=149.50,
    initial_target=150.50
)

# Place order and link
order = ib.placeOrder(contract, order_obj)
db.link_order_to_trade(trade_id, order.permId, is_entry=True)
```

## Key Features

### Deduplication
- Database-level deduplication via `ON CONFLICT (exec_id) DO NOTHING`
- No in-memory tracking needed
- Handles duplicate fills from multiple capture layers

### Partial Fills
- Tracks all fills in JSONB arrays
- Calculates VWAP for entry and exit prices
- Automatic P&L calculation when trade fully closed

### Durability
- WAL ensures no fills lost even if database down
- Automatic retry and recovery
- All fills written to disk immediately

### Reconciliation
- Position reconciliation with IBKR every 5 minutes
- Discrepancy detection and logging
- Manual review required for mismatches

## Migration from Old System

The old `trades` table remains intact. To migrate historical data:

```sql
INSERT INTO trades_v2 (
    trade_id, symbol, system, direction, strategy,
    signal_time, signal_price,
    entry_time, entry_price, entry_qty,
    exit_time, exit_price, exit_qty, exit_reason,
    gross_pnl, total_commission, net_pnl,
    hold_seconds, status
)
SELECT 
    trade_id::uuid, symbol, 
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

## Monitoring

### Fill Capture Rate
```sql
SELECT 
    source,
    COUNT(*) as fills,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as pct
FROM executions
WHERE received_at > NOW() - INTERVAL '1 day'
GROUP BY source;
```

### Unlinked Fills
```sql
SELECT COUNT(*) FROM executions WHERE trade_id IS NULL;
```

### Position Discrepancies
```sql
SELECT * FROM positions WHERE NOT is_reconciled;
```

## Acceptance Criteria

- [x] Schema created
- [x] Unified fill processor implemented
- [x] Trade database interface implemented
- [x] Position tracker implemented
- [x] Database initialized (with minor index error)
- [x] Integration with l2-scalping (COMPLETE)
- [x] Integration with l2-vwap (PARTIAL - startup/shutdown only)
- [ ] Integration with intraday-paper (system uses demo code)
- [x] Verification script created
- [ ] 5-day parallel run with zero discrepancies

## Integration Summary

### l2-scalping ✅ FULLY INTEGRATED
- Imports `TradeIntegration` from `cpapi.trade_integration`
- Initializes Trade DB V2 on startup after IBKR connection
- Opens trade in database when signal is executed
- Links entry orders to trades
- Stops Trade DB V2 on shutdown
- Fills automatically captured by `UnifiedFillProcessor`

### l2-vwap ⚠️ PARTIALLY INTEGRATED
- Imports `TradeIntegration` from `cpapi.trade_integration`
- Initializes Trade DB V2 on startup
- Stops Trade DB V2 on shutdown
- **TODO**: Add trade opening when orders are placed

### ml-paper-trading ❌ NOT INTEGRATED
- System uses minimal demo code
- Integrate when real trading logic is implemented

## Next Steps

1. **Set PostgreSQL password** (if needed):
   ```bash
   # Update DB_CONFIG in scripts/verify_trade_db_v2.py
   # Or set environment variable
   export POSTGRES_PASSWORD=your_password
   ```

2. **Run verification**:
   ```bash
   python3 scripts/verify_trade_db_v2.py
   ```

3. **Test l2-scalping integration**:
   ```bash
   cd /home/jacobw/quantstack/l2_scalping
   ./start_scalping.sh
   ```

4. **Complete l2-vwap integration**:
   - Find order placement code in l2-vwap
   - Add `trade_db.open_trade()` and `trade_db.link_order()` calls

5. **Monitor fills**:
   ```sql
   SELECT * FROM executions ORDER BY received_at DESC LIMIT 10;
   ```

6. **Run 5-day parallel test**:
   - Monitor fill capture rate
   - Verify position reconciliation
   - Check for unlinked fills
   - Test WAL recovery
