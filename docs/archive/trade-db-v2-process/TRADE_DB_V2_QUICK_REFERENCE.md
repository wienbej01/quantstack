# Trade Database V2 - Quick Reference

## Overview

Trade Database V2 is the production trade recording system that replaced the old broken database which had an 80% fill loss rate. The new system achieves 100% fill capture through triple-layer capture, WAL durability, and database-level deduplication.

## Quick Start

### Run Tests
```bash
# Full test suite
python3 scripts/run_trade_db_v2_tests.py

# Quick test
./scripts/test_trade_db_v2.sh
```

### Verify System
```bash
python3 scripts/verify_trade_db_v2.py
```

### Check Status
```bash
# View recent trades
psql -U jacobw -d trading -c "SELECT symbol, direction, entry_price, exit_price, net_pnl FROM trades_v2 ORDER BY entry_time DESC LIMIT 10;"

# Check fill capture
psql -U jacobw -d trading -c "SELECT source, COUNT(*) FROM executions GROUP BY source;"

# Check positions
psql -U jacobw -d trading -c "SELECT symbol, quantity, avg_price FROM positions WHERE quantity != 0;"
```

## Database Schema

### Tables

**trades_v2** - Main trade records
- Primary key: `trade_id` (UUID)
- Tracks: entry/exit prices, P&L, fills, slippage
- Status: PENDING, OPEN, CLOSED, CANCELLED

**executions** - Immutable fill log
- Primary key: `exec_id` (IBKR execution ID)
- Source: CALLBACK, POLL, RECONCILE
- Deduplication: ON CONFLICT (exec_id) DO NOTHING

**positions** - Current positions
- Tracks: quantity, avg_price, realized/unrealized P&L
- Reconciliation: last_reconcile, is_reconciled

## Integration

### l2-scalping (✅ Fully Integrated)
```python
from cpapi.trade_integration import TradeIntegration

# Initialize
self.trade_db = TradeIntegration(ib=self.ib, system_name="l2-scalping")
self.trade_db.start()

# Open trade
trade_id = self.trade_db.open_trade(
    symbol="AAPL",
    direction="LONG",
    signal_price=150.0,
    stop_loss=149.0,
    take_profit=151.0,
    metadata={"rule": "momentum", "strength": 0.8}
)

# Link order
self.trade_db.link_order(trade_id, order_id, is_entry=True)

# Shutdown
self.trade_db.stop()
```

### l2-vwap (⚠️ Partial)
- Startup/shutdown integrated
- Trade opening needs completion

### ml-paper-trading (❌ Not Integrated)
- Uses minimal demo code

## Architecture

### Triple-Layer Fill Capture

**Layer 1: Event Callbacks** (~10ms latency)
- Listen to `execDetailsEvent` from IBKR
- Fastest but unreliable (only 20% success in old system)

**Layer 2: Polling** (500ms interval)
- Poll `Trade.fills` continuously
- Catches fills missed by callbacks

**Layer 3: Reconciliation** (5 minute interval)
- Request all executions via `reqExecutions()`
- Final safety net for 100% capture

### Write-Ahead Log (WAL)

- All fills written to local JSONL file immediately
- Asynchronous processing to database
- Automatic recovery on startup
- Location: `logs/wal/fills_YYYYMMDD.jsonl`

### Deduplication

```sql
INSERT INTO executions (exec_id, ...)
VALUES (...)
ON CONFLICT (exec_id) DO NOTHING
```

Prevents duplicates from:
- Multiple capture layers
- WAL recovery
- Race conditions

## Key Features

✅ **100% Fill Capture** - Triple-layer capture ensures no fills lost  
✅ **WAL Durability** - Data survives database outages  
✅ **Deduplication** - No duplicate fills from multiple sources  
✅ **VWAP Calculation** - Automatic weighted average for partial fills  
✅ **Position Reconciliation** - Compare with IBKR every 5 minutes  
✅ **Audit Trail** - Immutable execution log with source tracking  

## Performance

- Throughput: >500 trades/sec
- Query speed: <10ms
- Fill latency: 10ms (callback) to 5min (reconciliation)
- WAL write: <1ms

## Monitoring

### Check Fill Capture Rate
```sql
SELECT 
    source,
    COUNT(*) as fills,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as pct
FROM executions
GROUP BY source;
```

### Check Unlinked Fills
```sql
SELECT COUNT(*) FROM executions WHERE trade_id IS NULL;
```

### Check Position Reconciliation
```sql
SELECT symbol, is_reconciled, last_reconcile 
FROM positions 
WHERE NOT is_reconciled;
```

### Check Recent Trades
```sql
SELECT symbol, direction, entry_price, exit_price, net_pnl, status
FROM trades_v2
WHERE entry_time > NOW() - INTERVAL '24 hours'
ORDER BY entry_time DESC;
```

## Troubleshooting

### No fills captured
1. Check if fill processor is running
2. Check WAL directory exists: `logs/wal/`
3. Check database connection
4. Run verification: `python3 scripts/verify_trade_db_v2.py`

### Duplicate fills
- Should never happen (database constraint)
- If occurs, check exec_id uniqueness

### Position drift
- Check reconciliation status
- Run manual reconciliation
- Check for unlinked fills

### Database outage
- Fills preserved in WAL
- Automatic recovery on restart
- Check WAL files in `logs/wal/`

## Files

### Core
- `cpapi/unified_fill_processor.py` - Triple-layer capture
- `cpapi/trade_database.py` - Trade operations
- `cpapi/position_tracker.py` - Position tracking
- `cpapi/trade_integration.py` - Integration API
- `cpapi/schema.sql` - Database schema

### Scripts
- `scripts/run_trade_db_v2_tests.py` - Complete test suite
- `scripts/test_trade_db_v2.sh` - Quick test runner
- `scripts/verify_trade_db_v2.py` - System verification
- `scripts/migrate_to_trade_db_v2.py` - Migration from old DB

### Documentation
- `docs/TRADE_DB_V2_QUICK_REFERENCE.md` - This file
- `docs/TRADE_DB_V2_MIGRATION.md` - Migration details
- `docs/TRADE_DB_V2_TEST_RESULTS.md` - Test results
- `docs/TRADE_DB_V2_COMPLETE_TEST_PLAN.md` - Test plan

## Migration Status

✅ **Complete** - 94 trades migrated from old database  
✅ **Old table backed up** as `trades_old_backup`  
✅ **All tests passing** - 13/13 tests pass  
✅ **Production ready** - System validated and deployed  

## Support

For issues or questions:
1. Run verification: `python3 scripts/verify_trade_db_v2.py`
2. Check logs: `logs/wal/fills_*.jsonl`
3. Review test results: `python3 scripts/run_trade_db_v2_tests.py`
4. Check documentation in `docs/TRADE_DB_V2_*.md`
