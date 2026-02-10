# Trade Database

Production trade recording system with 100% fill capture via triple-layer capture, WAL durability, and database-level deduplication.

## Schema

Three tables in PostgreSQL (`trading` database):

### executions (Source of Truth)

Immutable fill log. Every IBKR execution is recorded exactly once.

| Column | Type | Description |
|--------|------|-------------|
| exec_id | VARCHAR(50) PK | IBKR execution ID |
| received_at | TIMESTAMPTZ | When we received the fill |
| ibkr_time | TIMESTAMPTZ | IBKR's execution timestamp |
| symbol | VARCHAR(10) | Ticker |
| system | VARCHAR(20) | l2-scalping, l2-vwap, etc. |
| side | VARCHAR(4) | BUY or SELL |
| quantity | INTEGER | Shares filled |
| price | DECIMAL(12,4) | Fill price |
| commission | DECIMAL(10,4) | Commission |
| exchange | VARCHAR(20) | Exchange code |
| ibkr_order_id | INTEGER | IBKR order ID |
| ibkr_perm_id | INTEGER | IBKR permanent ID |
| trade_id | UUID | Link to trades_v2 |
| source | VARCHAR(20) | CALLBACK, POLL, or RECONCILE |
| raw_data | JSONB | Full IBKR execution object |

Deduplication: `ON CONFLICT (exec_id) DO NOTHING`

### trades_v2 (Denormalized)

Trade records computed from executions.

| Column | Type | Description |
|--------|------|-------------|
| trade_id | UUID PK | Trade identifier |
| symbol | VARCHAR(10) | Ticker |
| system | VARCHAR(20) | Trading system |
| strategy | VARCHAR(50) | Strategy name |
| direction | VARCHAR(5) | long or short |
| signal_time | TIMESTAMPTZ | When signal fired |
| signal_price | DECIMAL(12,4) | Price at signal |
| signal_data | JSONB | Signal metadata |
| entry_time | TIMESTAMPTZ | First fill time |
| entry_price | DECIMAL(12,4) | VWAP entry price |
| entry_qty | INTEGER | Total entry shares |
| entry_fills | JSONB | Array of fill details |
| exit_time | TIMESTAMPTZ | Last exit fill time |
| exit_price | DECIMAL(12,4) | VWAP exit price |
| exit_qty | INTEGER | Total exit shares |
| exit_fills | JSONB | Array of fill details |
| exit_reason | VARCHAR(20) | stop, target, manual, etc. |
| initial_stop | DECIMAL(12,4) | Original stop loss |
| initial_target | DECIMAL(12,4) | Original take profit |
| gross_pnl | DECIMAL(12,4) | P&L before commission |
| total_commission | DECIMAL(10,4) | Total commission |
| net_pnl | DECIMAL(12,4) | P&L after commission |
| hold_seconds | DECIMAL(12,2) | Duration |
| status | VARCHAR(10) | PENDING, OPEN, CLOSED, CANCELLED |

### positions (Current State)

Real-time position tracking with IBKR reconciliation.

| Column | Type | Description |
|--------|------|-------------|
| symbol | VARCHAR(10) | Ticker |
| system | VARCHAR(20) | Trading system |
| quantity | INTEGER | Current position |
| avg_price | DECIMAL(12,4) | Average cost |
| unrealized_pnl | DECIMAL(12,4) | Open P&L |
| realized_pnl | DECIMAL(12,4) | Closed P&L |
| ibkr_quantity | INTEGER | IBKR's position |
| ibkr_avg_price | DECIMAL(12,4) | IBKR's avg price |
| last_reconcile | TIMESTAMPTZ | Last reconciliation |
| is_reconciled | BOOLEAN | Matches IBKR? |

Unique constraint: `(symbol, system)`

Consistency model: "Last Write Wins" - fills update immediately via UPSERT, reconciliation only updates ibkr_* columns.

## Architecture

### Triple-Layer Fill Capture

1. **Callbacks** (~10ms) - `execDetailsEvent` from IBKR
2. **Polling** (500ms) - Poll `Trade.fills` continuously  
3. **Reconciliation** (5min) - `reqExecutions()` safety net

All three layers write to the same WAL and use the same deduplication.

### Write-Ahead Log (WAL)

Location: `logs/wal/fills_YYYYMMDD.jsonl`

- Fills written to local file immediately (sync)
- Async processing to database
- Automatic recovery on startup
- Survives database outages

### Data Retention

| Table | Retention | Partitioning |
|-------|-----------|--------------|
| executions | 1 year online, then archived | Monthly |
| trades_v2 | Indefinite | None (low volume) |
| positions | Current state only | None |

Archives: Compressed SQL dumps to `~/quantstack/backups/`

## Usage

### Integration API

```python
from cpapi.trade_integration import TradeIntegration

# Initialize
trade_db = TradeIntegration(ib=ib, system_name="l2-scalping")
trade_db.start()

# Open trade
trade_id = trade_db.open_trade(
    symbol="AAPL",
    direction="LONG",
    signal_price=150.0,
    stop_loss=149.0,
    take_profit=151.0,
    metadata={"rule": "momentum"}
)

# Link order to trade
trade_db.link_order(trade_id, order_id, is_entry=True)

# Shutdown
trade_db.stop()
```

### Common Queries

```sql
-- Recent trades
SELECT symbol, direction, entry_price, exit_price, net_pnl 
FROM trades_v2 ORDER BY entry_time DESC LIMIT 10;

-- Fill capture by source
SELECT source, COUNT(*) FROM executions GROUP BY source;

-- Current positions
SELECT symbol, quantity, avg_price FROM positions WHERE quantity != 0;

-- Unreconciled positions
SELECT symbol, quantity, ibkr_quantity 
FROM positions WHERE NOT is_reconciled;

-- Daily P&L
SELECT SUM(net_pnl) FROM trades_v2 
WHERE entry_time::date = CURRENT_DATE AND status = 'CLOSED';
```

### Verification

```bash
python3 scripts/verify_trade_db_v2.py
```

## Files

| File | Purpose |
|------|---------|
| `cpapi/schema.sql` | Database schema |
| `cpapi/unified_fill_processor.py` | Triple-layer capture |
| `cpapi/trade_database.py` | Trade operations |
| `cpapi/position_tracker.py` | Position tracking |
| `cpapi/trade_integration.py` | Integration API |

## Performance

- Throughput: >500 trades/sec
- Query latency: <10ms
- Fill capture: 10ms (callback) to 5min (reconciliation)
- WAL write: <1ms
