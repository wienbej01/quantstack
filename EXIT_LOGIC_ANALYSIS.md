# Exit Logic Analysis - Intraday Paper Trading
**Date**: 2026-01-23  
**Issue**: 2 positions held overnight (ASTS, GLSI entered 09:35 ET, held 6h 25m)

---

## Root Cause Analysis

### Issue 1: EOD Flatten Logic Not Executing

**Code Location**: `/home/jacobw/intraday_stack/scripts/paper_trade.py:762-765`

```python
if self.is_market_hours():
    # Check for EOD flatten (once per day)
    if self.is_eod_flatten_time():
        today = datetime.now(ET).date()
        if self._last_eod_check != today:
            self.flatten_all_positions("EOD")
            self._last_eod_check = today
    else:
        # Normal trading
        self.run_decision_cycle()
```

**Problem**: EOD flatten logic is present but **no log evidence it executed**
- Logs show portfolio updates at 15:50, 15:53, 15:56, 15:59, 16:00+ but no "FLATTENING" messages
- Expected log: `"FLATTENING {len(self._active_trades)} positions: EOD"`
- This log message was never written

**Possible Causes**:
1. `self._active_trades` was empty (positions not tracked)
2. `self._last_eod_check` was already set to today (flatten already ran)
3. Exception occurred before log message
4. Logic never reached due to earlier condition failure

### Issue 2: Bracket Orders Not Triggering

**Expected Behavior**: Each entry should have stop-loss and profit-target orders
- ASTS short @ $105.395 should have stop ~$106.45 (10 bps), target ~$104.34 (15 bps)
- GLSI long @ $22.30 should have stop ~$22.08 (10 bps), target ~$22.52 (15 bps)

**Observation**: Positions held for 6h 25m without hitting stops or targets
- ASTS moved from $105.395 → $116.39 (10.4% adverse move!)
- GLSI moved from $22.30 → $23.49 (5.3% favorable move)

**Possible Causes**:
1. Bracket orders not actually placed with IBKR
2. Bracket orders cancelled prematurely
3. Bracket order IDs not tracked correctly in `self._active_trades`
4. Order fill detection not working (orders filled but not detected)

### Issue 3: Position Tracking Mismatch

**Evidence from Database**:
```
ASTS: entry_time = 2026-01-22T14:35:11.126455 (09:35 ET)
GLSI: entry_time = 2026-01-22T14:35:14.032111 (09:35 ET)
```

**Evidence from IBKR Portfolio** (from logs):
- ASTS position = 0 (not in portfolio updates after 15:50)
- GLSI position = 0 (not in portfolio updates after 15:50)

**Discrepancy**: Database shows OPEN, but IBKR portfolio shows 0 position
- This suggests positions were closed in IBKR but not detected by paper trading system
- Position sync (`_sync_positions()`) runs every 5 minutes but didn't detect closure

---

## Detailed Findings

### 1. Emergency EOD Script Failure (Fixed)
✅ **Fixed**: Updated PostgreSQL syntax from `?` to `%s`  
✅ **Tested**: Script now connects and queries successfully  
⚠️ **Note**: This is backup system, primary flatten should have worked

### 2. EOD Flatten Logic Issues

**Code Review**:
```python
def is_eod_flatten_time(self) -> bool:
    """Check if we should flatten positions (15 min before close)."""
    et_now = datetime.now(ET)
    if et_now.weekday() >= 5:
        return False
    return et_now.time() >= dt_time(15, 45)  # 3:45 PM ET
```

**Logic Flow**:
- 15:45 ET: `is_eod_flatten_time()` returns True
- Should call `flatten_all_positions("EOD")`
- Should log: `"FLATTENING {len(self._active_trades)} positions: EOD"`
- **No such log found in paper_20260122.log**

**Hypothesis**: `self._active_trades` was empty
- Positions entered at 09:35 ET
- If tracking failed, `self._active_trades` would be empty
- `flatten_all_positions()` returns early if no active trades

### 3. Position Tracking Investigation

**Entry Logic** (`paper_trade.py:700-740`):
```python
self._active_trades[parent_id] = {
    "trade_id": trade_id,
    "symbol": rc.symbol,
    "direction": rc.direction,
    "entry_qty": intent.quantity,
    "stop_id": stop_id,
    "target_id": target_id,
    "entry_price": intent.entry_price,
    "stop_price": intent.stop_price,
    "target_price": intent.target_price,
}
```

**Exit Detection** (`paper_trade.py:279-320`):
- Monitors order fills via `on_order_fill()` callback
- Checks if fill is for stop_id or target_id
- Closes trade in database and removes from `self._active_trades`

**Position Sync** (`paper_trade.py:380-430`):
- Runs every 5 minutes
- Compares IBKR positions with `self._active_trades`
- Should detect if position closed in IBKR but not in tracking

### 4. Bracket Order Investigation

**Bracket Order Placement**:
```python
# From order_manager or adapter
bracket_ids = [parent_id, target_id, stop_id]
```

**Tracking**:
```python
target_id = order.bracket_ids[1] if len(order.bracket_ids) > 1 else None
stop_id = order.bracket_ids[2] if len(order.bracket_ids) > 2 else None
```

**Potential Issue**: If `order.bracket_ids` is empty or malformed:
- `target_id` and `stop_id` would be None
- No exit detection would occur
- Position would remain open indefinitely

---

## Evidence Summary

### What We Know:
1. ✅ 2 positions entered at 09:35 ET (ASTS, GLSI)
2. ✅ Positions recorded in database with status='OPEN'
3. ✅ IBKR portfolio shows 0 position for both (after 15:50)
4. ❌ No EOD flatten log messages
5. ❌ No bracket order fill detection
6. ❌ Position sync didn't detect closure
7. ❌ Emergency EOD script failed (now fixed)

### What We Don't Know:
1. ❓ Were bracket orders actually placed with IBKR?
2. ❓ Were bracket orders filled but not detected?
3. ❓ Was `self._active_trades` empty at 15:45 ET?
4. ❓ Did position sync run and fail silently?

---

## Recommended Fixes

### Priority 1: Add Logging
```python
def flatten_all_positions(self, reason: str = "EOD"):
    """Force close all open positions."""
    logger.info(f"flatten_all_positions called: reason={reason}, active_trades={len(self._active_trades)}")
    
    if not self._active_trades:
        logger.warning("No active trades to flatten")
        return
    
    logger.warning(f"FLATTENING {len(self._active_trades)} positions: {reason}")
    # ... rest of logic
```

### Priority 2: Add Position Tracking Validation
```python
def run_decision_cycle(self):
    # At start of each cycle
    logger.debug(f"Active trades: {len(self._active_trades)}, symbols: {[t['symbol'] for t in self._active_trades.values()]}")
```

### Priority 3: Add Bracket Order Validation
```python
# After placing bracket order
if not target_id or not stop_id:
    logger.error(f"Bracket order incomplete: parent={parent_id}, target={target_id}, stop={stop_id}")
else:
    logger.info(f"Bracket order complete: parent={parent_id}, target={target_id}, stop={stop_id}")
```

### Priority 4: Improve Position Sync Logging
```python
def _sync_positions(self):
    logger.info(f"Position sync: tracking={len(self._active_trades)}, ibkr_positions={len(ibkr_positions)}")
    # ... existing logic
```

### Priority 5: Add EOD Check Logging
```python
if self.is_eod_flatten_time():
    logger.info(f"EOD flatten time reached: last_check={self._last_eod_check}, today={today}")
    if self._last_eod_check != today:
        logger.info("Triggering EOD flatten")
        self.flatten_all_positions("EOD")
        self._last_eod_check = today
    else:
        logger.info("EOD flatten already ran today")
```

---

## Testing Plan

### Test 1: Verify Bracket Orders
```bash
# During next trading session, check logs for:
grep "Bracket order complete" /home/jacobw/intraday_stack/logs/paper_*.log
grep "bracket_ids" /home/jacobw/intraday_stack/logs/paper_*.log
```

### Test 2: Verify Position Tracking
```bash
# Check active trades count throughout session
grep "Active trades:" /home/jacobw/intraday_stack/logs/paper_*.log
```

### Test 3: Verify EOD Flatten
```bash
# Check EOD flatten execution
grep "EOD flatten" /home/jacobw/intraday_stack/logs/paper_*.log
grep "FLATTENING" /home/jacobw/intraday_stack/logs/paper_*.log
```

### Test 4: Manual EOD Test
```python
# Run emergency EOD script manually (now fixed)
python3 /home/jacobw/quantstack/scripts/emergency_eod_close.py
```

---

## Immediate Actions

1. ✅ **Fixed emergency EOD script** - PostgreSQL syntax corrected
2. ✅ **Tested emergency EOD script** - Connects and queries successfully
3. ⏳ **Add comprehensive logging** - Implement Priority 1-5 fixes above
4. ⏳ **Test during next session** - Verify bracket orders and position tracking
5. ⏳ **Monitor EOD flatten** - Confirm it executes at 15:45 ET

---

## Long-term Improvements

1. **Add position reconciliation alerts** - Alert if database != IBKR positions
2. **Add bracket order validation** - Fail entry if bracket orders incomplete
3. **Add max hold time** - Force exit after N hours regardless of stops/targets
4. **Add pre-EOD position check** - Alert at 15:30 if positions still open
5. **Improve error handling** - Don't silently fail on position sync errors

---

## Conclusion

**Root Cause**: Likely a combination of:
1. Bracket orders not placed or not tracked correctly
2. Position tracking lost (entries not added to `self._active_trades`)
3. EOD flatten didn't execute because `self._active_trades` was empty
4. Position sync didn't detect IBKR closure
5. Emergency EOD script failed due to PostgreSQL syntax error

**Immediate Fix**: Emergency EOD script now works (tested)  
**Next Steps**: Add comprehensive logging and test during next trading session  
**Risk**: Without logging, we can't definitively determine root cause
