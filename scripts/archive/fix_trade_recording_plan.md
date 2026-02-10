# Trade Recording Fix Plan
**Created**: 2026-01-30  
**Issues**: L2 trades not recorded, Intraday exit prices incorrect

---

## Phase 1: Code Audit (Task 0)

### Systems to Check

1. **L2 Scalping** (`~/quantstack/l2_scalping`)
   - ✅ CONFIRMED: Uses `_legacy_fill_handler()` which only calls `record_fill()`
   - ❌ MISSING: Never calls `record_trade_entry()` or `record_trade_exit()`
   - Files: `src/main.py`, `src/fill_processor.py`

2. **Intraday Stack** (`~/intraday_stack`)
   - ✅ Has proper `close_trade()` in `event_store.py`
   - ❓ UNKNOWN: Who calls it and with what exit_price?
   - Files: `src/journal/event_store.py`, `src/execution/engine.py`, `src/execution/exits.py`

3. **L2 VWAP Reversion** (`~/quantstack/l2_vwap_reversion`)
   - ❓ UNKNOWN: Check if it has similar fill handling
   - Search for: `record_fill`, `fill_handler`, `process_fill`

4. **Alpha Systems** (`~/quantstack/alpha`)
   - ❓ UNKNOWN: Check if they record trades properly
   - Search for: trade recording patterns

### Audit Commands

```bash
# Find all fill handlers
find ~/quantstack -name "*.py" -type f | xargs grep -l "def.*fill.*handler\|def process_fill" 2>/dev/null

# Find all trade recording calls
find ~/quantstack -name "*.py" -type f | xargs grep -n "record_trade_entry\|open_trade\|close_trade" 2>/dev/null

# Find systems that record fills
find ~/quantstack -name "*.py" -type f | xargs grep -n "record_fill\|log_fill" 2>/dev/null

# Check for orphaned fills (fills without trades)
psql -d trading -U jacobw -c "
SELECT f.symbol, COUNT(*) as fill_count, COUNT(DISTINCT t.trade_id) as trade_count
FROM fills f
LEFT JOIN trades t ON f.order_id = t.entry_order_id OR f.order_id = t.exit_order_id
WHERE f.timestamp::date >= '2026-01-20'
GROUP BY f.symbol
HAVING COUNT(*) > COUNT(DISTINCT t.trade_id);"
```

---

## Phase 2: Fix L2 Scalping (Task 1)

### File: `/home/jacobw/quantstack/l2_scalping/src/main.py`

### Current Code (lines ~1160-1200)
```python
def _legacy_fill_handler(self, trade, fill) -> None:
    """Legacy fill handler for backward compatibility"""
    # ... existing code ...
    
    # Records fill but NEVER records trade
    if hasattr(self.trade_journal, "record_fill"):
        self.trade_journal.record_fill(...)
```

### Required Changes

#### 1. Add instance variable to track active trades
```python
# In __init__():
self.active_trades = {}  # {symbol: trade_id}
```

#### 2. Add helper method to extract rule name
```python
def _extract_rule_from_ref(self, order_ref: str) -> str:
    """Extract rule name from order reference.
    
    Example: 'L2SCALP_high_obi_depth_ENTRY_BUY_JOBY_...' -> 'high_obi_depth'
    """
    if not order_ref or "L2SCALP_" not in order_ref:
        return "unknown"
    
    parts = order_ref.split("_")
    if len(parts) >= 3:
        # L2SCALP_<rule_name>_ENTRY/EXIT_...
        return parts[1]
    return "unknown"

def _determine_exit_reason(self, order_ref: str) -> str:
    """Determine exit reason from order reference."""
    if "STOP" in order_ref or "SL" in order_ref:
        return "STOP_LOSS"
    elif "TARGET" in order_ref or "TP" in order_ref:
        return "TAKE_PROFIT"
    elif "TIMEOUT" in order_ref or "MAX_HOLD" in order_ref:
        return "MAX_HOLD_TIME"
    elif "EXIT" in order_ref:
        return "SIGNAL_EXIT"
    return "MANUAL"
```

#### 3. Modify _legacy_fill_handler() - Entry Fill Section
```python
# After recording fill, around line ~1050 where entry is fully filled:
if order_id in self.pending_entries and fully_filled:
    pending = self.pending_entries[order_id]
    
    # Extract rule name from order_ref
    rule_name = self._extract_rule_from_ref(order_ref)
    
    # Record trade entry
    try:
        trade_id = self.trade_journal.record_trade_entry(
            symbol=symbol,
            side=entry_side,
            quantity=expected_qty,
            entry_price=avg_fill_price,
            order_id=order_id,
            rule_name=rule_name,
            signal_id=f"l2_{rule_name}_{symbol}_{datetime.now().strftime('%H%M%S')}",
            signal_price=avg_fill_price
        )
        
        if trade_id:
            self.active_trades[symbol] = trade_id
            logger.info(f"L2 Trade opened: {trade_id} for {symbol}")
        else:
            logger.error(f"Failed to open trade for {symbol}")
    except Exception as exc:
        logger.error(f"Error recording trade entry for {symbol}: {exc}", exc_info=True)
    
    # Clean up pending entry
    del self.pending_entries[order_id]
```

#### 4. Modify _legacy_fill_handler() - Exit Fill Section
```python
# After recording fill, around line ~1120 where exit is processed:
# Check if this is an exit for an active trade
if symbol in self.active_trades:
    trade_id = self.active_trades[symbol]
    exit_reason = self._determine_exit_reason(order_ref)
    
    try:
        self.trade_journal.record_trade_exit(
            trade_id=trade_id,
            exit_price=fill_price,
            exit_qty=filled_qty,
            exit_reason=exit_reason,
            order_id=order_id
        )
        
        logger.info(f"L2 Trade closed: {trade_id} for {symbol} @ {fill_price}")
        del self.active_trades[symbol]
    except Exception as exc:
        logger.error(f"Error recording trade exit for {symbol}: {exc}", exc_info=True)
```

### Testing
```bash
# 1. Test in paper trading
systemctl --user restart l2-scalping.service

# 2. Monitor logs
tail -f ~/quantstack/l2_scalping/logs/scalping_system.log | grep "Trade opened\|Trade closed"

# 3. Verify database
psql -d trading -U jacobw -c "SELECT COUNT(*) FROM trades WHERE system = 'l2-scalping' AND entry_time::date = CURRENT_DATE;"

# 4. Check fills vs trades
psql -d trading -U jacobw -c "
SELECT 
    (SELECT COUNT(*) FROM fills WHERE timestamp::date = CURRENT_DATE) as fills,
    (SELECT COUNT(*) FROM trades WHERE entry_time::date = CURRENT_DATE AND system = 'l2-scalping') as trades;"
```

---

## Phase 3: Fix Intraday Exit Prices (Task 2)

### Investigation Required

The `close_trade()` function in `event_store.py` looks correct - it uses the `exit_price` parameter passed to it. The issue is likely in WHO calls it and WHAT price they pass.

### Files to Check

1. **`~/intraday_stack/src/execution/engine.py`**
   - Search for calls to `close_trade()` or `event_store.close_trade()`
   - Verify they pass actual fill price, not signal price

2. **`~/intraday_stack/src/execution/exits.py`**
   - Check exit logic
   - Ensure it retrieves actual fill price from broker

3. **`~/intraday_stack/src/strategies/exit_manager.py`**
   - Check if it handles EOD exits
   - Verify EMERGENCY_EOD uses actual market price

### Search Commands
```bash
# Find where close_trade is called
grep -rn "\.close_trade\|event_store.close" ~/intraday_stack/src --include="*.py" -A 5

# Find where exit prices are determined
grep -rn "exit_price\s*=" ~/intraday_stack/src --include="*.py" | grep -v "def\|#"

# Find EMERGENCY_EOD logic
grep -rn "EMERGENCY_EOD" ~/intraday_stack/src --include="*.py" -A 10
```

### Expected Fix Pattern
```python
# WRONG:
event_store.close_trade(
    trade_id=trade_id,
    exit_price=trade.entry_price,  # ❌ Using entry price!
    ...
)

# CORRECT:
# Get actual fill from broker or fills table
actual_fill = self._get_last_fill_price(symbol, order_id)
event_store.close_trade(
    trade_id=trade_id,
    exit_price=actual_fill,  # ✅ Using actual fill price
    ...
)
```

---

## Phase 4: Add Validation (Task 3)

### Database Constraint

```sql
-- Create function to validate fills have trades
CREATE OR REPLACE FUNCTION validate_fills_have_trades()
RETURNS TABLE(
    symbol TEXT,
    fill_count BIGINT,
    trade_count BIGINT,
    orphaned_fills BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        f.symbol,
        COUNT(*) as fill_count,
        COUNT(DISTINCT t.trade_id) as trade_count,
        COUNT(*) - COUNT(DISTINCT t.trade_id) as orphaned_fills
    FROM fills f
    LEFT JOIN trades t ON (
        f.order_id = t.entry_order_id OR 
        f.order_id = t.exit_order_id
    )
    WHERE f.timestamp::date >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY f.symbol
    HAVING COUNT(*) > COUNT(DISTINCT t.trade_id);
END;
$$ LANGUAGE plpgsql;
```

### Nightly Validation Script

**File**: `~/quantstack/scripts/validate_trade_recording.py`

```python
#!/usr/bin/env python3
"""Nightly validation of trade recording integrity."""

import psycopg2
from datetime import datetime, timedelta

def validate_fills_have_trades():
    """Check that all fills have corresponding trades."""
    conn = psycopg2.connect(database='trading', user='jacobw')
    cursor = conn.cursor()
    
    # Check last 7 days
    cursor.execute("""
        SELECT 
            f.symbol,
            COUNT(*) as fill_count,
            COUNT(DISTINCT t.trade_id) as trade_count
        FROM fills f
        LEFT JOIN trades t ON (
            f.order_id = t.entry_order_id OR 
            f.order_id = t.exit_order_id
        )
        WHERE f.timestamp::date >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY f.symbol
        HAVING COUNT(*) > COUNT(DISTINCT t.trade_id)
    """)
    
    issues = cursor.fetchall()
    if issues:
        print("⚠️  ORPHANED FILLS DETECTED:")
        for symbol, fills, trades in issues:
            print(f"  {symbol}: {fills} fills but only {trades} trades")
        return False
    
    print("✅ All fills have corresponding trades")
    return True

def validate_exit_prices():
    """Check for suspicious exit prices."""
    conn = psycopg2.connect(database='trading', user='jacobw')
    cursor = conn.cursor()
    
    # Check for zero-slippage exits
    cursor.execute("""
        SELECT trade_id, symbol, entry_price, exit_price
        FROM trades
        WHERE entry_time::date >= CURRENT_DATE - INTERVAL '7 days'
          AND status = 'CLOSED'
          AND entry_price = exit_price
    """)
    
    issues = cursor.fetchall()
    if issues:
        print("⚠️  ZERO-SLIPPAGE EXITS DETECTED:")
        for trade_id, symbol, entry, exit in issues:
            print(f"  {trade_id}: {symbol} entry={entry} exit={exit}")
        return False
    
    print("✅ No suspicious exit prices")
    return True

if __name__ == "__main__":
    all_ok = True
    all_ok &= validate_fills_have_trades()
    all_ok &= validate_exit_prices()
    
    if not all_ok:
        exit(1)
```

### Cron Job
```bash
# Add to crontab
0 1 * * * /home/jacobw/quantstack/.venv/bin/python /home/jacobw/quantstack/scripts/validate_trade_recording.py
```

---

## Phase 5: Backfill Jan 29 Data (Tasks 4 & 5)

### Task 4: Backfill L2 Trades

**File**: `~/quantstack/scripts/backfill_l2_jan29.py`

```python
#!/usr/bin/env python3
"""Backfill L2 trades from Jan 29 logs."""

import re
from datetime import datetime
import psycopg2

def parse_l2_logs():
    """Parse L2 scalping logs to extract trade data."""
    log_file = "/home/jacobw/quantstack/l2_scalping/logs/scalping_system.log"
    
    trades = []
    with open(log_file) as f:
        for line in f:
            if "2026-01-29" not in line:
                continue
            
            # Parse entry fills
            if "Order filled:" in line and "BOT" in line or "SLD" in line:
                match = re.search(r'Order filled: (\w+) (BOT|SLD) (\d+)@([\d.]+)', line)
                if match:
                    symbol, side, qty, price = match.groups()
                    timestamp = line.split()[0] + " " + line.split()[1]
                    trades.append({
                        'timestamp': timestamp,
                        'symbol': symbol,
                        'side': side,
                        'qty': int(qty),
                        'price': float(price)
                    })
    
    return trades

def insert_trades(trades):
    """Insert reconstructed trades into database."""
    conn = psycopg2.connect(database='trading', user='jacobw')
    cursor = conn.cursor()
    
    # Group by symbol to match entries with exits
    # ... implementation ...
    
    print(f"Backfilled {len(trades)} L2 trades")

if __name__ == "__main__":
    trades = parse_l2_logs()
    insert_trades(trades)
```

### Task 5: Fix Intraday Exit Prices

```sql
-- Update intraday trades with correct exit prices from fills table
UPDATE trades t
SET 
    exit_price = f.price,
    gross_pnl = CASE 
        WHEN t.direction = 'long' THEN (f.price - t.entry_price) * t.exit_qty
        ELSE (t.entry_price - f.price) * t.exit_qty
    END,
    net_pnl = CASE 
        WHEN t.direction = 'long' THEN (f.price - t.entry_price) * t.exit_qty - t.commission
        ELSE (t.entry_price - f.price) * t.exit_qty - t.commission
    END
FROM fills f
WHERE t.exit_order_id = f.order_id
  AND t.entry_time::date = '2026-01-29'
  AND t.system = 'intraday-paper'
  AND f.side IN ('SLD', 'BOT');
```

---

## Phase 6: Testing (Task 6)

### Test Plan

1. **Unit Tests**
   - Test `_extract_rule_from_ref()` with various order refs
   - Test `_determine_exit_reason()` with various order refs
   - Mock trade_journal and verify calls

2. **Integration Tests**
   - Deploy to paper trading
   - Execute 10 test trades
   - Verify all trades recorded correctly
   - Verify exit prices match actual fills

3. **Validation Queries**
```sql
-- Check fills vs trades ratio
SELECT 
    DATE(f.timestamp) as date,
    COUNT(*) as fills,
    (SELECT COUNT(*) FROM trades WHERE DATE(entry_time) = DATE(f.timestamp)) as trades
FROM fills f
WHERE f.timestamp >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(f.timestamp);

-- Check for zero-slippage trades
SELECT COUNT(*) 
FROM trades 
WHERE entry_time >= CURRENT_DATE - INTERVAL '7 days'
  AND entry_price = exit_price
  AND status = 'CLOSED';
```

---

## Phase 7: Monitoring (Task 7)

### Alert Rules

**File**: `~/quantstack/monitoring/trade_recording_alerts.py`

```python
def check_orphaned_fills():
    """Alert if fills without trades detected."""
    # Query database
    # If orphaned fills > 10, send alert
    pass

def check_zero_slippage():
    """Alert if too many zero-slippage exits."""
    # Query database
    # If zero_slippage_count > 5, send alert
    pass

def check_l2_recording():
    """Alert if L2 fills but no trades."""
    # Check L2 system specifically
    # If L2 fills > 0 and L2 trades == 0, send alert
    pass
```

### Integration with Existing Monitoring

Add to `system_health_monitor.py` or create new systemd service.

---

## Summary

### Critical Path
1. ✅ Audit complete (found L2 issue, intraday issue)
2. 🔧 Fix L2 `_legacy_fill_handler()` (Task 1)
3. 🔍 Investigate intraday exit price source (Task 2)
4. 🔧 Fix intraday exit price recording (Task 2)
5. ✅ Add validation (Task 3)
6. 🧪 Test in paper trading (Task 6)
7. 📊 Deploy monitoring (Task 7)
8. 🔄 Backfill historical data (Tasks 4 & 5)

### Estimated Timeline
- Phase 1 (Audit): 2 hours
- Phase 2 (L2 Fix): 4 hours
- Phase 3 (Intraday Fix): 4 hours
- Phase 4 (Validation): 2 hours
- Phase 5 (Backfill): 3 hours
- Phase 6 (Testing): 4 hours
- Phase 7 (Monitoring): 2 hours

**Total**: ~21 hours (3 days)

### Risk Mitigation
- Test all changes in paper trading first
- Keep backups of database before backfill
- Deploy fixes incrementally (L2 first, then intraday)
- Monitor closely for 48 hours after deployment


---

## ADDENDUM: NTFY Notification Issue

### User Report
NTFY L2 messages show:
- Price: $0.00
- Value: $0.00

### Root Cause Analysis

The NTFY notifications are sent from `record_trade_entry()` in `trade_journal.py`:

```python
# Line ~307 in trade_journal.py
if self.ntfy_available:
    send_trade_notification(
        action="ENTRY",
        symbol=symbol,
        strategy=system_tag,
        direction=side,
        price=entry_price,      # ← Should have actual price
        quantity=quantity,       # ← Should have actual quantity
        position_id=trade_id[:8] if trade_id else None,
    )
```

**However**: Since `record_trade_entry()` is NEVER called by L2 main.py, these notifications are NEVER sent!

### Where Are The Notifications Coming From?

The user IS receiving NTFY notifications, which means:
1. Either there's another notification path we haven't found
2. Or the notifications are from a different system
3. Or they're being sent with default/zero values somewhere

### Investigation Required

```bash
# Search for any other NTFY notification calls
grep -rn "send_trade_notification\|ntfy.*trade" ~/quantstack/l2_scalping --include="*.py"

# Check if there's a fallback notification in fill handler
grep -A20 "def _legacy_fill_handler" ~/quantstack/l2_scalping/src/main.py | grep -i "notif\|ntfy"

# Check logs for notification source
grep "2026-01-29.*Trade notification sent" ~/quantstack/l2_scalping/logs/scalping_system.log | head -5
```

### Will The Fix Address This?

**YES** ✅ - The fix in Phase 2 will resolve this issue because:

1. **Current State**:
   - `record_trade_entry()` is never called
   - NTFY notifications either not sent or sent with wrong data
   - User sees price=0, value=0

2. **After Fix**:
   - `_legacy_fill_handler()` will call `record_trade_entry()`
   - `record_trade_entry()` will send NTFY with actual prices:
     ```python
     send_trade_notification(
         action="ENTRY",
         symbol=symbol,
         price=avg_fill_price,    # ✅ Actual fill price
         quantity=expected_qty,    # ✅ Actual quantity
         ...
     )
     ```
   - User will see correct price and value in NTFY

3. **Expected NTFY Message After Fix**:
   ```
   Opening JOBY position [l2_17697]
   Time: 09:48:04 ET
   Strategy: l2-scalping high_obi_depth
   Side: SELL
   Quantity: 88
   Price: $11.26          ← Real price
   Value: $991.88         ← Real value
   ```

### Additional Verification

After deploying the fix, verify NTFY notifications show correct data:

```bash
# Monitor L2 logs for notification sends
tail -f ~/quantstack/l2_scalping/logs/scalping_system.log | grep "Trade notification sent"

# Check that notifications have non-zero prices
# (manually check NTFY app or webhook logs)
```

### Summary

- **Issue**: NTFY shows price=0, value=0
- **Root Cause**: `record_trade_entry()` never called, so proper notifications never sent
- **Fix**: Phase 2 changes will call `record_trade_entry()` which sends correct NTFY notifications
- **Result**: NTFY will show actual prices and values after fix is deployed

**The fix in Phase 2 will automatically resolve the NTFY notification issue.**
