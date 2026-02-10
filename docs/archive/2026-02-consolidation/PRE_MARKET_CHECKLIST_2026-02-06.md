# Pre-Market Checklist - 2026-02-06

## Critical Fixes Applied ✅

### 1. Fill Callback Registration (l2-vwap)
- **File**: `l2_vwap_reversion/src/main.py`
- **Change**: Added `self.order_manager.set_fill_callback(self._on_fill)`
- **Impact**: OrderManager will now notify system immediately when fills occur
- **Log**: Look for "FILL CALLBACK:" messages

### 2. WAL Error Handling
- **File**: `cpapi/unified_fill_processor.py`
- **Change**: Added try/except + fsync to `_write_wal()`
- **Impact**: WAL writes won't fail silently, data flushed to disk immediately
- **Log**: Look for "WAL write failed:" errors

### 3. Fill Processing Logging
- **File**: `cpapi/unified_fill_processor.py`
- **Change**: Added "FILL [source]:" log at entry of `_process_fill()`
- **Impact**: Every fill will be logged immediately when received
- **Log**: Look for "FILL [CALLBACK/POLL/RECONCILE]:" messages

### 4. Database Insert Logging
- **File**: `cpapi/unified_fill_processor.py`
- **Change**: Enhanced "FILL INSERTED:" log with exec_id, order_id, trade_id
- **Impact**: Can trace fill from capture → database → trade
- **Log**: Look for "FILL INSERTED:" messages

---

## Pre-Market Verification (Before 09:00 ET)

### 1. IBKR Gateway
```bash
# Start Gateway manually
# Verify listening
ss -ltn | grep :7494

# Test connection
python3 -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1',7494,999); print('OK'); ib.disconnect()"
```

Notes:
- Prefer the repo preflight check for a production-faithful probe (uses `qx_broker.ibkr` and the configured `IBKR_GATEWAY_PORT`, default `7494`):
  `python /home/jacobw/quantstack/scripts/preflight_check.py`

### 2. Database Connection
```bash
# Test PostgreSQL
psql -d trading -U jacobw -c "SELECT 1"

# Check connection pool limits
psql -d trading -U jacobw -c "SHOW max_connections;"
```

### 3. WAL Directory
```bash
# Ensure writable
ls -ld /home/jacobw/quantstack/logs/wal/
touch /home/jacobw/quantstack/logs/wal/test && rm /home/jacobw/quantstack/logs/wal/test
```

### 4. Service Status
```bash
# Check timers
systemctl list-timers | grep -E "l2-|intraday-"

# Verify no crash-looping services
systemctl list-units --state=failed
```

---

## Market Open Monitoring (09:20-09:30 ET)

### Watch Logs in Real-Time
```bash
# Terminal 1: l2-vwap logs
journalctl -u l2-vwap-reversion.service -f | grep -E "FILL|Bracket|Trade DB"

# Terminal 2: Fill processor logs
journalctl -u l2-vwap-reversion.service -f | grep -E "UnifiedFillProcessor|WAL"

# Terminal 3: Database activity
watch -n 2 'psql -d trading -U jacobw -c "SELECT COUNT(*) FROM executions WHERE received_at > NOW() - INTERVAL '\''5 minutes'\''"'
```

### Check WAL Files
```bash
# Watch WAL directory
watch -n 5 'ls -lh /home/jacobw/quantstack/logs/wal/ && echo "---" && tail -3 /home/jacobw/quantstack/logs/wal/fills_$(date +%Y%m%d).jsonl 2>/dev/null'
```

### Monitor Database
```bash
# Real-time fill count
watch -n 2 'psql -d trading -U jacobw -c "SELECT COUNT(*) as total_fills, COUNT(*) FILTER (WHERE trade_id IS NOT NULL) as linked, COUNT(*) FILTER (WHERE trade_id IS NULL) as orphan FROM executions WHERE received_at > NOW() - INTERVAL '\''1 hour'\''"'
```

---

## Expected Log Sequence (First Trade)

```
1. [INFO] execution.order_manager: Bracket order: BUY 10 NVDA | parent=5, SL=172.00 (id=6), TP=174.00 (id=7)
2. [INFO] __main__: Trade DB V2: opened trade_id=abc-123
3. [INFO] __main__: Fill callback registered
4. [INFO] cpapi.unified_fill_processor: FILL [CALLBACK]: NVDA BUY 10@173.00 order=5
5. [INFO] cpapi.unified_fill_processor: FILL INSERTED: NVDA BUY 10@173.00 exec_id=xxx order=5 trade=abc-123
6. [INFO] __main__: FILL CALLBACK: NVDA BUY 10@173.00 order=5 entry=True
```

---

## Success Criteria

✅ **Fill Capture Working**:
- WAL file created: `/home/jacobw/quantstack/logs/wal/fills_20260206.jsonl`
- WAL file growing (new lines added per fill)
- "FILL [CALLBACK]:" logs appearing
- "FILL INSERTED:" logs appearing

✅ **Database Recording Working**:
- `executions` table has new rows
- `trade_id` is NOT NULL (fills linked to trades)
- `trades_v2` status changes from PENDING → OPEN → CLOSED

✅ **Fill Callback Working**:
- "FILL CALLBACK:" logs appearing
- Logs show correct order_id, symbol, quantity, price

---

## Failure Scenarios & Fixes

### Scenario 1: No WAL file created
**Symptom**: `/home/jacobw/quantstack/logs/wal/` is empty  
**Cause**: No fills received OR WAL write failing  
**Check**: Look for "WAL write failed:" errors  
**Fix**: Check IBKR connection, verify orders are actually filling

### Scenario 2: WAL file exists but database empty
**Symptom**: WAL has entries, but `executions` table empty  
**Cause**: WAL flush failing OR database connection issue  
**Check**: Look for "WAL flush error:" or "DB insert error:"  
**Fix**: Check PostgreSQL connection, check pool exhaustion

### Scenario 3: Fills in database but trade_id is NULL
**Symptom**: `executions` has rows but `trade_id` column is NULL  
**Cause**: Order not linked to trade before fill arrived  
**Check**: Verify `trade_order_links` has entry for that order_id  
**Fix**: Ensure `link_order()` is called immediately after order placement

### Scenario 4: No "FILL CALLBACK:" logs
**Symptom**: Fills captured but no callback logs  
**Cause**: Callback not registered OR OrderManager not detecting fills  
**Check**: Verify `set_fill_callback()` was called  
**Fix**: Already fixed in this update

---

## Emergency Rollback

If system fails at market open:

```bash
# Stop services
sudo systemctl stop l2-vwap-reversion.service l2-scalping.service intraday-paper.service

# Revert changes
cd /home/jacobw/quantstack
git diff l2_vwap_reversion/src/main.py cpapi/unified_fill_processor.py
git checkout l2_vwap_reversion/src/main.py cpapi/unified_fill_processor.py

# Restart
sudo systemctl daemon-reload
```

---

## Post-Market Verification

After market close, verify data integrity:

```sql
-- Check all trades have fills
SELECT COUNT(*) FROM trades_v2 WHERE status = 'CLOSED' AND trade_id NOT IN (SELECT DISTINCT trade_id FROM executions WHERE trade_id IS NOT NULL);

-- Check all fills are linked
SELECT COUNT(*) FROM executions WHERE trade_id IS NULL AND received_at::date = CURRENT_DATE;

-- Check PnL calculations
SELECT trade_id, gross_pnl, net_pnl FROM trades_v2 WHERE status = 'CLOSED' AND ABS(gross_pnl) > 1000;
```

---

## Summary

**3 critical fixes applied**:
1. Fill callback registration (immediate fill notification)
2. WAL error handling (no silent failures)
3. Enhanced logging (full visibility into fill flow)

**System is now ready** for market open with full fill capture visibility.
