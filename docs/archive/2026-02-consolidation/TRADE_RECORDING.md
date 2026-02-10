# Trade Recording System

**Last Updated**: 2026-01-30  
**Status**: ✅ Production Ready

## Overview

The trade recording system ensures all trading activity (fills and trades) is accurately captured in the database for analysis, reporting, and compliance.

## Architecture

### Components

1. **Fill Recording** - Captures individual order executions
2. **Trade Recording** - Links entry/exit fills into complete trades
3. **Validation** - Nightly checks for data integrity
4. **Monitoring** - Alerts on recording failures

### Data Flow

```
Order Fill → record_fill() → fills table
           ↓
           → record_trade_entry() → trades table (OPEN)
           ↓
Exit Fill  → record_trade_exit() → trades table (CLOSED)
```

## Systems

### L2 Scalping

**File**: `/home/jacobw/quantstack/l2_scalping/src/main.py`

**Recording Logic**:
- Entry fills trigger `record_trade_entry()`
- Exit fills trigger `record_trade_exit()`
- Tracks active trades via `active_trades` dict

**Key Methods**:
- `_legacy_fill_handler()` - Processes fills and records trades
- `_extract_rule_from_ref()` - Parses rule name from order reference
- `_determine_exit_reason()` - Determines exit type (STOP_LOSS, TAKE_PROFIT, etc.)

### Intraday Paper Trading

**File**: `/home/jacobw/intraday_stack/scripts/paper_trade.py`

**Recording Logic**:
- Normal exits use actual fill prices
- EOD force close queries fills table for actual prices
- Fallback priority: fills table → live quote → entry price

**Key Fix**:
- EOD closes now query fills table first (source of truth)
- Prevents recording entry_price as exit_price

### L2 VWAP Reversion

**File**: `/home/jacobw/quantstack/l2_vwap_reversion/src/main.py`

**Recording Logic**:
- Uses signal-driven architecture
- Calls `event_store.open_trade()` and `close_trade()` directly
- No fixes needed - already correct

## Validation

### Automated Checks

**Script**: `/home/jacobw/quantstack/scripts/validate_trade_recording.py`

**Schedule**: Daily at 1:00 AM (cron)

**Checks**:
1. **Orphaned Fills** - Fills without corresponding trades
2. **Zero-Slippage Exits** - Trades with entry_price == exit_price
3. **L2 Recording Status** - L2 fills but no trades

**Alerts**: NTFY notifications sent on failures

### Database Functions

```sql
-- Check for orphaned fills
SELECT * FROM validate_fills_have_trades();

-- Check for suspicious exits
SELECT * FROM validate_exit_prices();
```

## Monitoring

### NTFY Alerts

**Topic**: `ntfy.sh/quantstack_alerts`

**Alert Priorities**:
- Orphaned fills: HIGH
- Zero-slippage exits: HIGH
- L2 recording failure: URGENT

### Logs

**Validation Log**: `~/quantstack/logs/validation.log`

```bash
# View recent validation results
tail -f ~/quantstack/logs/validation.log
```

## Historical Issues

### Jan 29, 2026

**L2 Scalping**:
- Issue: 3,591 fills but 0 trades recorded
- Cause: `record_trade_entry()` never called
- Fix: Added trade recording to `_legacy_fill_handler()`
- Status: Fixed 2026-01-30, data gap documented

**Intraday Paper**:
- Issue: 5 trades with $0 P&L (entry_price == exit_price)
- Cause: EOD force close used entry_price as fallback
- Fix: Query fills table for actual exit prices
- Status: Fixed 2026-01-30, historical data corrected to -$373

## Troubleshooting

### No Trades Recorded

**Symptoms**: Fills in database but no trades

**Check**:
```bash
# Run validation manually
python3 ~/quantstack/scripts/validate_trade_recording.py
```

**Common Causes**:
- `record_trade_entry()` not called
- Exception in trade recording code
- Database connection issues

### Incorrect Exit Prices

**Symptoms**: entry_price == exit_price, gross_pnl = 0

**Check**:
```sql
SELECT * FROM validate_exit_prices();
```

**Common Causes**:
- EOD force close using wrong price source
- Quote lookup failure with no fallback
- Fills table not queried

### Missing NTFY Notifications

**Symptoms**: Trades recorded but no notifications

**Check**:
- Verify `record_trade_entry()` is called
- Check NTFY service availability
- Review trade journal logs

## Maintenance

### Daily Tasks

- ✅ Automated via cron (1:00 AM)
- ✅ Validation runs automatically
- ✅ Alerts sent on failures

### Weekly Tasks

- Review validation logs
- Check for recurring issues
- Verify alert delivery

### Monthly Tasks

- Analyze validation trends
- Update thresholds if needed
- Archive old validation logs

## Files

### Production Code
- `/home/jacobw/quantstack/l2_scalping/src/main.py`
- `/home/jacobw/intraday_stack/scripts/paper_trade.py`
- `/home/jacobw/quantstack/scripts/validate_trade_recording.py`
- `/home/jacobw/quantstack/scripts/validation_functions.sql`

### Documentation
- `/home/jacobw/quantstack/docs/TRADE_RECORDING.md` (this file)
- `/home/jacobw/quantstack/docs/archive/2026-01-30-trade-recording-fix/` (historical)

### Archived
- `/home/jacobw/quantstack/scripts/archive/fix_jan29_intraday_exits.py`
- `/home/jacobw/quantstack/scripts/archive/fix_trade_recording_plan.md`

## References

- [Audit Logging](AUDIT_LOGGING.md)
- [System Guide](SYSTEM_GUIDE.md)
- [EOD Report](EOD_REPORT.md)
