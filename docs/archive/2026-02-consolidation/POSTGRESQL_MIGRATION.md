# PostgreSQL Migration Complete

## Summary

Successfully migrated the trading system from SQLite to PostgreSQL to eliminate database lock issues during concurrent writes from multiple systems (l2-scalping, intraday-paper).

## What Was Done

### 1. PostgreSQL Installation & Configuration
- Installed PostgreSQL 17
- Created `trading` database and `jacobw` user
- Configured peer authentication (no password needed)
- Installed `psycopg2-binary` in both venvs

### 2. EventStore PostgreSQL Support
- Added `use_postgres` flag and `pg_config` parameter to EventStore
- Implemented dynamic placeholder support (`%s` for PostgreSQL, `?` for SQLite)
- Wrapped SQLite-specific PRAGMA statements in conditionals
- Fixed all SQL statements to use dynamic placeholders
- Fixed row_factory handling in all query methods:
  - `close_trade()` - now uses cursor.description for PostgreSQL
  - `get_trades_for_date()` - proper row conversion
  - `get_decisions_for_date()` - proper row conversion
  - `get_fills_for_date()` - proper row conversion
  - `get_open_trades()` - proper row conversion
  - `update_trade_fills()` - dynamic placeholders

### 3. Data Migration
- Created migration script: `/home/jacobw/quantstack/scripts/migrate_to_postgres.py`
- Migrated all existing data:
  - 68 trades
  - 250,225 decisions
  - 75 orders
  - 41 fills
- Added missing `system` column to PostgreSQL trades table

### 4. Service Configuration Updates
- **l2-scalping**: `/home/jacobw/quantstack/l2_scalping/src/reporting/trade_journal.py`
- **intraday-paper**: `/home/jacobw/intraday_stack/scripts/paper_trade.py`
- **daily report**: `/home/jacobw/intraday_stack/src/reporting/daily_paper_report.py`

All now use:
```python
EventStore(
    use_postgres=True,
    pg_config={'database': 'trading', 'user': 'jacobw'}
)
```

### 5. Testing
- Created test script: `/home/jacobw/quantstack/scripts/test_postgres_eventstore.py`
- Verified trades write and read correctly
- Confirmed P&L calculations work properly

## Connection Details

- **Database**: `trading`
- **User**: `jacobw`
- **Authentication**: Peer (local Unix socket)
- **Port**: 5432 (default)

## Benefits

1. **No More Database Locks**: PostgreSQL handles concurrent writes from multiple systems
2. **Better Performance**: PostgreSQL optimized for concurrent access
3. **Production Ready**: Industry-standard database for trading systems
4. **Backward Compatible**: SQLite support maintained for development/testing

## Verification Commands

```bash
# Check PostgreSQL connection
psql -U jacobw -d trading -c "SELECT version();"

# View recent trades
psql -U jacobw -d trading -c "SELECT trade_id, symbol, strategy, entry_time, status FROM trades ORDER BY entry_time DESC LIMIT 10;"

# Count records
psql -U jacobw -d trading -c "SELECT 
  (SELECT COUNT(*) FROM trades) as trades,
  (SELECT COUNT(*) FROM decisions) as decisions,
  (SELECT COUNT(*) FROM orders) as orders,
  (SELECT COUNT(*) FROM fills) as fills;"

# Test EventStore
cd /home/jacobw/intraday_stack && source .venv/bin/activate && python /home/jacobw/quantstack/scripts/test_postgres_eventstore.py
```

## Next Steps

1. **Monitor First Live Session**: Watch for any database errors during next trading session
2. **Verify L2-Scalping Trades**: Confirm l2-scalping now records trades to database (not just logs)
3. **Check Reports**: Ensure trading_report.py works with PostgreSQL
4. **Backup Strategy**: Set up PostgreSQL backups (pg_dump)

## Rollback (If Needed)

To rollback to SQLite:

```python
# In trade_journal.py, paper_trade.py, daily_paper_report.py
self.event_store = EventStore("/home/jacobw/intraday_stack/data/journal/events.db")
```

SQLite database still contains all historical data up to migration point.

## Files Modified

- `/home/jacobw/intraday_stack/src/journal/event_store.py` - PostgreSQL support
- `/home/jacobw/quantstack/l2_scalping/src/reporting/trade_journal.py` - Use PostgreSQL
- `/home/jacobw/intraday_stack/scripts/paper_trade.py` - Use PostgreSQL
- `/home/jacobw/intraday_stack/src/reporting/daily_paper_report.py` - Use PostgreSQL
- `/home/jacobw/quantstack/scripts/migrate_to_postgres.py` - Migration script (new)
- `/home/jacobw/quantstack/scripts/test_postgres_eventstore.py` - Test script (new)
