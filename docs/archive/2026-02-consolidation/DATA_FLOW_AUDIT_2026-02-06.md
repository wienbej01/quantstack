# Trading System Data Flow Audit Report
**Date**: 2026-02-06  
**Auditor**: System Analysis  
**Scope**: Order execution → Fill capture → Database recording

---

## Executive Summary

**Update (2026-02-06, ~10:10 ET):**
- `l2-scalping`, `intraday-paper`, and `l2-vwap-reversion` were all running under systemd.
- `l2-scalping` traded at the 09:30 ET open (6 trade opens recorded in audit and `trades`).
- `l2-vwap-reversion` was started and placed/filled at least 2 trades (audit + DB).
- `UnifiedFillProcessor` was writing to WAL and inserting into `executions` (but see timestamp + dedup issues below).

**CRITICAL ISSUES FOUND (impacting paper trading correctness / health checks):**
1. **VWAP internal position shares were fixed at 100** even when bracket order quantity was larger.
   - This caused incorrect `TRADE_CLOSE` quantities (e.g. exit logged as 100 when execution was 264/268).
   - It also risked incorrect emergency exits/EOD flatten behavior (market exit would use 100).
   - Fix implemented in `l2_vwap_reversion/src/main.py` and `l2_vwap_reversion/src/strategy.py`.
2. **`executions.received_at` timestamp skew** due to naive UTC strings being inserted into `timestamptz`.
   - `received_at` was written using `datetime.utcnow().isoformat()` (no timezone) then interpreted in server TZ.
   - This can cause false negatives in any "recent execution activity" checks using `received_at`.
   - Fix implemented in `cpapi/unified_fill_processor.py` (timezone-aware + parsing).
3. **WAL/log spam and disk growth** from polling all historical fills every loop.
   - `UnifiedFillProcessor` processed the same `exec_id` repeatedly and appended duplicates to WAL.
   - Fix implemented in `cpapi/unified_fill_processor.py` (in-memory exec_id dedup + FILL logs to debug).
   - Note: requires restarting each service to pick up changes.
4. **`executions.system` shows `unknown` for many `l2-scalping` fills** because those order IDs are not present in `trade_order_links`.
   - Result: health checks that filter by system may report "no recording" even though `executions` rows exist.
   - Remediation: ensure `l2-scalping` links order IDs to system in `trade_order_links` (not yet implemented).

---

## Database Integrity Analysis

### Current State
```
Total trades:        17
├─ PENDING:          17 (100%)
├─ OPEN:             0
└─ CLOSED:           0

Orphan fills:        84 (fills with no trade_id)
Trades with no fills: 17 (all PENDING trades)
Trade-order links:   41 (3 per trade: entry + 2 bracket orders)
```

### Orphan Fills Detail
- **Symbol**: RMBS (all 84 fills)
- **Order ID**: 12 (all same order)
- **System**: 'unknown' (not linked to any trading system)
- **Side**: SELL
- **Total quantity**: ~3,400 shares across partial fills
- **Conclusion**: Manual trade or external system, not from l2-vwap/l2-scalping

### PENDING Trades Detail
- **System**: l2-vwap (all 17 trades)
- **Symbols**: HIMS, NVDA, QCOM
- **Date**: 2026-02-05 22:36 - 23:40 (trading session)
- **Order IDs**: 5-75 (sequential)
- **Status**: All have trade_order_links but NO executions

---

## Data Flow Analysis

### Expected Flow
```
Signal → OrderManager.submit_bracket_order()
       → IBKR API (parent + SL + TP orders)
       → TradeDatabase.open_trade()
       → TradeDatabase.link_order() × 3
       → [WAIT FOR FILLS]
       → UnifiedFillProcessor._on_exec_details() OR _poll_loop()
       → _process_fill()
       → _write_wal()
       → _flush_wal_to_db()
       → _insert_execution()
       → _update_trade_from_execution()
       → _maybe_close_trade()
```

### Actual Flow (Feb 05 session)
```
✅ Signal generated
✅ OrderManager.submit_bracket_order() - logs show bracket orders created
✅ IBKR API - orders submitted (parent IDs: 5, 9, 13, 18, 22, 47, 51, 56, 60, 64, 68, 73)
✅ TradeDatabase.open_trade() - 17 trades created
✅ TradeDatabase.link_order() - 41 links created (3 per trade)
✅ UnifiedFillProcessor started - logs confirm initialization
❌ NO FILLS CAPTURED - no WAL files, no executions in database
❌ NO FILL EVENTS - no logs showing _process_fill() or FILL messages
```

---

## Root Cause Analysis

### Issue 1: Orders Never Filled
**Evidence:**
- No executions in database for order IDs 5-75
- No WAL files created (processor would write even if DB insert failed)
- No "FILL" log messages from UnifiedFillProcessor

**Possible Causes:**
1. Orders were cancelled before fill (no cancel logs found)
2. Orders are still pending (unlikely after 24+ hours)
3. Orders were rejected by IBKR (no rejection logs)
4. **Most likely**: Orders were placed but IBKR Gateway was disconnected/crashed

**Verification Needed:**
- Check IBKR Gateway logs for disconnections around 22:36-23:40 on Feb 05
- Check if orders still exist in IBKR TWS/Gateway
- Verify IBKR API connection was stable during session

### Issue 2: Fill Callback Not Connected
**Evidence:**
```python
# OrderManager has fill callback mechanism
def set_fill_callback(self, callback) -> None:
    self._fill_callback = callback

def _on_order_status(self, trade: Trade) -> None:
    if status == "Filled" and filled > 0 and self._fill_callback:
        self._fill_callback(order_id, symbol, side, filled, avg_price, is_entry)
```

**Problem:**
- `set_fill_callback()` is NEVER called in l2-vwap main.py
- OrderManager detects fills via `orderStatusEvent` but has no callback registered
- Even if orders filled, no notification to TradeDatabase

**Impact:**
- Fills detected by OrderManager but not propagated to database
- Relies entirely on UnifiedFillProcessor polling/callbacks
- Single point of failure if processor misses events

### Issue 3: UnifiedFillProcessor Event Subscription
**Evidence:**
```python
def start(self):
    self.ib.execDetailsEvent += self._on_exec_details  # Event subscription
    self._poll_thread.start()  # Polling backup
    self._recon_thread.start()  # Reconciliation backup
```

**Verification Needed:**
- Check if `ib.execDetailsEvent` is properly subscribed
- Verify `ib.trades()` returns fills in poll loop
- Check if `ib.reqExecutions()` works in reconcile loop

### Issue 4: WAL Directory Permissions
**Evidence:**
- WAL directory exists: `/home/jacobw/quantstack/logs/wal/`
- Directory is empty (no fills_*.jsonl files)
- Processor started successfully (logs confirm)

**Possible Causes:**
1. No fills to write (orders never filled)
2. Write permission issue (unlikely - directory owned by jacobw)
3. Exception in `_write_wal()` silently caught

---

## Code Issues Found

### 1. Missing Fill Callback Registration (l2-vwap)
**File**: `l2_vwap_reversion/src/main.py`  
**Issue**: OrderManager created but `set_fill_callback()` never called

**Fix**:
```python
# After OrderManager initialization
self.order_manager.set_fill_callback(self._on_fill)

def _on_fill(self, order_id, symbol, side, filled_qty, avg_price, is_entry):
    """Handle fill notification from OrderManager."""
    logger.info(f"Fill callback: {symbol} {side} {filled_qty}@{avg_price} (order={order_id})")
    # Trigger immediate database sync or position update
```

### 2. No Error Handling in WAL Write
**File**: `cpapi/unified_fill_processor.py:_write_wal()`  
**Issue**: No try/except, silent failures possible

**Current**:
```python
def _write_wal(self, entry: dict):
    wal_file = self.wal_dir / f"fills_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
    with self._lock:
        with open(wal_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
```

**Fix**:
```python
def _write_wal(self, entry: dict):
    try:
        wal_file = self.wal_dir / f"fills_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
        with self._lock:
            with open(wal_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')
                f.flush()  # Ensure write to disk
    except Exception as e:
        logger.error(f"WAL write failed: {e}", exc_info=True)
```

### 3. No Logging in Fill Processing
**File**: `cpapi/unified_fill_processor.py:_process_fill()`  
**Issue**: No log message when fill is processed (only in `_insert_execution`)

**Fix**: Add logging at entry:
```python
def _process_fill(self, fill, source: str):
    self._last_fill_ts = time.monotonic()
    logger.debug(f"Processing fill from {source}: {fill}")  # ADD THIS
    # ... rest of code
```

### 4. Race Condition in _maybe_close_trade
**File**: `cpapi/trade_database.py:_maybe_close_trade()`  
**Issue**: Checks `exit_qty < entry_qty` but partial fills may arrive out of order

**Current**:
```python
if not row or not row[4] or row[4] < row[2]:
    return  # Exit if exit_qty < entry_qty
```

**Risk**: If exit fill arrives before all entry fills processed, trade won't close

**Fix**: Add timeout-based closure or explicit "all fills received" flag

### 5. No Audit Logging for Fills
**File**: All trading systems  
**Issue**: Fills are not logged to audit logs (only to database)

**Impact**: Reconciliation requires database + IBKR logs, no audit trail

**Fix**: Add audit logging in UnifiedFillProcessor:
```python
from cpapi.audit_logger import get_audit_logger
_audit = get_audit_logger("fill-processor")

def _insert_execution(self, conn, entry: dict):
    # ... existing code ...
    if result:
        _audit.log_event(
            "FILL_CAPTURED",
            f"{entry['symbol']} {entry['side']} {entry['quantity']}@{entry['price']}",
            context={
                "exec_id": entry['exec_id'],
                "order_id": entry['ibkr_order_id'],
                "trade_id": trade_id,
                "source": entry['source']
            }
        )
```

---

## Reconciliation Gaps

### Gap 1: IBKR API Logs vs Database
**Problem**: IBKR logs show fills, database shows no fills  
**Cause**: Fill processor not capturing events  
**Detection**: Run `scripts/reconcile_trades.py` (already exists)

### Gap 2: Audit Logs vs Database
**Problem**: Audit logs show trade open, but no fill events  
**Cause**: Fills not logged to audit system  
**Detection**: Compare audit TRADE_OPEN events with database trades

### Gap 3: Order Status vs Database
**Problem**: OrderManager detects fills, database doesn't update  
**Cause**: No callback registered to propagate fills  
**Detection**: Compare OrderManager._pending_orders with database

---

## Recommendations

### Immediate (Pre-Market Open)

1. **Add Fill Callback to l2-vwap** (5 min)
   ```python
   self.order_manager.set_fill_callback(self._on_fill)
   ```

2. **Add WAL Error Handling** (5 min)
   - Wrap `_write_wal()` in try/except
   - Add flush() to ensure disk write

3. **Add Fill Debug Logging** (2 min)
   - Log every fill in `_process_fill()`
   - Log WAL writes

4. **Verify IBKR Connection Stability** (10 min)
   - Check Gateway logs for disconnections
   - Add connection monitoring

### Short-Term (This Week)

5. **Add Audit Logging for Fills** (15 min)
   - Log FILL_CAPTURED events
   - Include exec_id, order_id, trade_id

6. **Add Fill Callback to l2-scalping** (10 min)
   - Same pattern as l2-vwap fix

7. **Add Position Reconciliation Alerts** (20 min)
   - Alert if IBKR position != database position
   - Run every 5 minutes during market hours

8. **Create Fill Monitoring Dashboard** (30 min)
   - Real-time fill count
   - WAL file size
   - Database insert rate

### Medium-Term (Next Sprint)

9. **Implement Dual-Write Pattern** (1 hour)
   - Write fills to both WAL and database immediately
   - Use WAL only for recovery, not primary path

10. **Add Order Status Polling** (1 hour)
    - Poll IBKR for order status every 10 seconds
    - Compare with database, alert on mismatch

11. **Build Reconciliation Service** (2 hours)
    - Continuous reconciliation during market hours
    - Auto-fix orphan fills (link to trades)
    - Alert on unresolvable mismatches

12. **Add Circuit Breaker for Fill Capture** (1 hour)
    - If no fills captured for 5 minutes during active trading, alert
    - Auto-restart fill processor if stuck

---

## Testing Plan

### Test 1: Fill Capture (Manual)
1. Place small test order (1 share)
2. Verify WAL file created
3. Verify database execution record
4. Verify audit log entry
5. Verify trade status updated

### Test 2: Bracket Order Flow (Manual)
1. Place bracket order
2. Verify 3 order links created
3. Wait for entry fill
4. Verify trade status = OPEN
5. Cancel bracket, verify trade closed

### Test 3: Reconciliation (Automated)
1. Run `scripts/reconcile_trades.py` for Feb 05
2. Verify it detects 17 PENDING trades with no fills
3. Verify it detects 84 orphan RMBS fills
4. Generate reconciliation report

### Test 4: Fill Processor Resilience (Automated)
1. Start fill processor
2. Simulate IBKR disconnect
3. Reconnect
4. Verify fills captured after reconnect
5. Verify WAL recovery works

---

## Monitoring Additions

### Metrics to Track
1. **Fill capture rate**: fills/minute during market hours
2. **WAL file size**: bytes written/minute
3. **Database insert rate**: executions/minute
4. **Orphan fill count**: fills with no trade_id
5. **PENDING trade age**: time since trade created
6. **Order-to-fill latency**: time from order placement to fill capture

### Alerts to Add
1. **No fills for 5 minutes** during active trading
2. **Orphan fill count > 10**
3. **PENDING trade age > 1 hour**
4. **WAL file not growing** during active trading
5. **Database insert failures**

---

## Appendix: SQL Queries for Monitoring

```sql
-- Real-time fill capture rate (last 5 minutes)
SELECT COUNT(*) as fills_last_5min
FROM executions
WHERE received_at > NOW() - INTERVAL '5 minutes';

-- Orphan fills
SELECT COUNT(*) as orphan_count, symbol, ibkr_order_id
FROM executions
WHERE trade_id IS NULL
GROUP BY symbol, ibkr_order_id
ORDER BY orphan_count DESC;

-- Stale PENDING trades
SELECT trade_id, symbol, system, 
       EXTRACT(EPOCH FROM (NOW() - signal_time))/3600 as hours_pending
FROM trades_v2
WHERE status = 'PENDING'
  AND signal_time < NOW() - INTERVAL '1 hour'
ORDER BY signal_time;

-- Fill-to-database latency
SELECT 
  AVG(EXTRACT(EPOCH FROM (received_at::timestamp - ibkr_time::timestamp))) as avg_latency_sec,
  MAX(EXTRACT(EPOCH FROM (received_at::timestamp - ibkr_time::timestamp))) as max_latency_sec
FROM executions
WHERE received_at > NOW() - INTERVAL '1 hour';
```

---

## Conclusion

The trading system has a **critical data capture gap**: orders are placed and linked to trades, but fills are not being captured. This is likely due to:

1. **IBKR Gateway disconnection** during the Feb 05 session (orders never filled)
2. **Missing fill callback** in l2-vwap (even if filled, not propagated to database)
3. **No audit logging for fills** (reconciliation relies on database only)

**Immediate action required** before market open:
- Add fill callback registration
- Add WAL error handling and logging
- Verify IBKR connection stability
- Test fill capture with small order

**System is NOT production-ready** until fill capture is verified working end-to-end.
