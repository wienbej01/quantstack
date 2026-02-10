# ERROR REPORT & ANALYSIS - January 27, 2026 ET

**Report Date**: 2026-01-28
**Trading Date**: 2026-01-27
**System Version**: 8.0 (systemd timers + PostgreSQL)
**Report Type**: Critical Incident Analysis

---

## Executive Summary

On January 27, 2026, the Quantstack Trading System experienced **multiple critical failures**:

1. **L2 Scalping executed 6,964 fills with ZERO database records** - complete trade journaling failure
2. **Intraday Paper Trading P&L reporting incorrect** - $229 loss recorded as $0
3. **OVERNIGHT POSITION VIOLATION** - L2 Scalping held -58 shares INTC SHORT overnight
4. **Emergency EOD safeguards failed** to flatten positions

**Severity**: CRITICAL - Multiple system layers failed simultaneously

---

## Remediation Status (as of 2026-01-28)

### Implemented Fixes

- Entry orders now default to **market** via config (`orders.entry_order_type: MKT`).
- Exit pricing can be switched to **fill-based** (`orders.exit_price_source: fill`).
- Fill-based exits submit OCA stop/target **after fills**, with **quantity resizing** on
  partial fills.
- Partial fills create/update positions immediately; exit orders track partials.
- Exit orders are now **market-only** (IOC removed from exit path).
- EOD flatten uses market orders and cancels open orders before flattening.
- Emergency EOD script attempts IBKR market flatten before DB-only closure.

### Remaining Risk Notes

- Runtime monitoring still assumes IBKR availability; a gateway outage could delay
  exit order acknowledgements even though emergency EOD now attempts IBKR first.
- Exit P&L and trade journal are now fill-based, but backfill for 2026-01-27
  remains out of scope.

### Verification Status

- `make lint`: **PASSED** (updated ML paths, fixed SIM103 lint in labeling).
- `make check-types`: **PASSED**.
- `make install`: **PASSED** (uv install completed).
- `pytest test_system_integration.py`: **PASSED** (1 warning: event loop).

---

## 1. L2 SCALPING ANALYSIS

### 1.1 Trading Activity (Actual vs. Recorded)

| Metric | Actual (Logs) | Database | Status |
|--------|---------------|----------|--------|
| Total Signals | 28,829 | 28,829 | ✓ Match |
| **Total Fills** | **6,964** | **0** | ❌ **CRITICAL** |
| Trades Recorded | 6,964 | 0 | ❌ **100% LOSS** |
| Symbols Traded | INTC, GM, NTLA | None | ❌ |

### 1.2 Fill Breakdown by Symbol

| Symbol | Fill Count | Share Sizes | Final Position |
|--------|------------|-------------|----------------|
| **INTC** | 1,438 | 11, 12, 22, 23 shares | **-58 SHORT** ⚠️ |
| **GM** | 2,020 | 11, 12, 22, 23 shares | FLAT |
| **NTLA** | 24 | Various sizes | FLAT |

### 1.3 Sample Fills from Logs

```
2026-01-27 09:30:06 - BOT 22 INTC @ $43.84
2026-01-27 09:30:07 - SLD 22 INTC @ $43.84
2026-01-27 09:30:08 - BOT 22 INTC @ $43.90
2026-01-27 09:30:09 - BOT 22 INTC @ $43.93
2026-01-27 09:30:10 - BOT 22 INTC @ $43.86
2026-01-27 09:30:11 - SLD 14 INTC @ $43.86
2026-01-27 09:30:11 - SLD 8 INTC @ $43.86
... (6,964 total fills)
```

### 1.4 NTFY Notifications

User received **hundreds of ntfy notifications** for ENTRY signals. Analysis confirms:
- Notifications sent for each ENTRY signal
- Signals resulted in actual fills (6,964 total)
- **None of these fills were recorded to database**

---

## 2. INTRADAY PAPER TRADING ANALYSIS

### 2.1 P&L Reporting Error

The PostgreSQL `trades` table contains **INCORRECT** data:

| Symbol | Direction | Entry (DB) | Exit (DB) | P&L (DB) | Entry (Actual) | Exit (Actual) | Real P&L | Error |
|--------|-----------|------------|-----------|----------|----------------|---------------|----------|-------|
| PUMP | LONG | $10.365 | $10.365 | $0.00 | $10.39 | $10.60 | **+$21.00** | -$21.00 |
| GLW | SHORT | $104.52 | $104.52 | $0.00 | $104.42 | $106.35 | **-$193.00** | +$193.00 |
| NTLA | LONG | $15.30 | $15.30 | $0.00 | $15.42 | $14.85 | **-$57.00** | +$57.00 |

**Database P&L**: $0.00
**Actual P&L**: **-$229.00**
**Error**: +$229.00 (reporting profit when actually loss)

### 2.2 Fills Table (CORRECT)

```
event_id: b3bfd66a-6e3f-43a8-a507-3e5719336b1a
timestamp: 2026-01-27T14:42:13
symbol: PUMP, side: BOT, qty: 100, price: $10.39

event_id: 669192de-b998-4603-840c-ad91cfe730a5
timestamp: 2026-01-27T14:49:10
symbol: PUMP, side: SLD, qty: 100, price: $10.60
(P&L = +$21.00)

event_id: b4460617-74e5-43bc-b9ec-0e38c44ff301
timestamp: 2026-01-27T14:49:49
symbol: GLW, side: SLD, qty: 100, price: $104.42

event_id: a030b274-e727-4abd-aecc-3cc5575553b0
timestamp: 2026-01-27T14:57:50
symbol: GLW, side: BOT, qty: 100, price: $106.35
(P&L = -$193.00)

event_id: 2ec6cb0b-504f-4adb-a8c7-dddefe944852
timestamp: 2026-01-27T15:00:35
symbol: NTLA, side: BOT, qty: 100, price: $15.42

event_id: e80de311-12eb-46b2-b2a3-931383e520a6
timestamp: 2026-01-27T17:23:05
symbol: NTLA, side: SLD, qty: 100, price: $14.85
(P&L = -$57.00)
```

### 2.3 Root Cause: Signal Price vs. Fill Price

The system is recording **signal generation price** instead of **actual fill execution price**:

**Example - NTLA Trade**:
- Signal generated at: $15.30 (recorded in DB)
- Actual fill entry: $15.42 (from fills table)
- Actual fill exit: $14.85 (from fills table)
- DB shows: entry=$15.30, exit=$15.30 (WRONG - both using signal price!)

---

## 3. OVERNIGHT POSITION VIOLATION

### 3.1 Critical Failure

**L2 Scalping ended trading day with OPEN POSITION**:

```
Date: 2026-01-27 15:50:23 ET (EOD)
Symbol: INTC
Position: -58 shares SHORT
Average Cost: $43.87234515
Market Value: -$2,547.94
```

### 3.2 5-Layer Protection System Status

| Protection Layer | Design | Status on Jan 27 |
|------------------|--------|-------------------|
| 1. Bracket Orders | Auto SL/TP on every entry | ❌ **FAILED** - Position still open |
| 2. Entry Curfew | Block entries after 15:49 ET | ⚠️ Partial - Last entry 15:48:32 |
| 3. Force Exit | Market order at 600s max hold | ❌ **FAILED** - Position held >6 hours |
| 4. Polling Backup | Check exits every 10ms | ❌ **FAILED** - No exit triggered |
| 5. Emergency EOD | Timer at 15:55 ET | ❌ **FAILED** - -58 shares remained |

### 3.3 Timeline of INTC Position

```
09:26 ET - L2 Scalping starts
09:30 ET - First INTC fills begin (massive trading activity)
15:48 ET - Last INTC position update: -80 shares SHORT @ $43.877
15:48 ET - Partial exit to -58 shares SHORT @ $43.872
15:50 ET - Final position: -58 shares SHORT @ $43.872
15:55 ET - Emergency EOD timer fires (position remains open)
17:01 ET - L2 Scalping shuts down (-58 shares STILL SHORT)
```

**Position held overnight for ~16 hours** until next trading day

---

## 4. DATABASE INTEGRITY ISSUES

### 4.1 Trades Table Query Results

```sql
SELECT * FROM trades WHERE DATE(entry_time) = '2026-01-27';
```

**Results**: 3 rows, all from `intraday-paper` system

```sql
SELECT * FROM trades WHERE strategy = 'l2_scalping';
```

**Results**: 6 rows total, NONE from 2026-01-27
- Last l2_scalping trade: 2026-01-09
- **18 days of trading activity missing from database**

### 4.2 Database Schema vs. Reality

| Table | Expected Records (Jan 27) | Actual Records | Status |
|-------|---------------------------|----------------|--------|
| `fills` | ~7,000 | 6 | ❌ Only intraday-paper fills |
| `trades` | ~3,500 (pairs) | 3 | ❌ Only intraday-paper |
| `decisions` | 34,841 | 34,841 | ✓ Correct |
| `orders` | ~7,000 | ? | ❓ Not queried |

### 4.3 Trade Journal Failure

**File**: `/home/jacobw/quantstack/l2_scalping/src/reporting/trade_journal.py`

**Evidence of failure**:
```python
# Log shows signals recorded:
"L2 Signal recorded: GM SHORT strength=0.857"
"L2 Signal recorded: INTC SHORT strength=0.857"

# But database shows 0 l2_scalping trades for Jan 27
```

**Hypothesis**: `trade_journal.py` is writing signals/decisions but NOT processing fills into trade records

---

## 5. L2 DATA STORAGE VERIFICATION

### 5.1 Status: ✓ PASSED

| Metric | Value | Verification |
|--------|-------|--------------|
| Total Parquet Files | 843 | ✓ PASS |
| Total Data Size | 10 MB | ✓ PASS |
| Symbols | INTC, NTLA, GM | ✓ PASS |
| Directory Structure | Hive partition (date=, symbol=) | ✓ PASS |
| File Format | Parquet with ts_utc, ts_epoch, date_et, symbol, mid | ✓ PASS |

### 5.2 Directory Structure

```
/home/jacobw/quantstack/data/l2_maximum/features/date=2026-01-27/
├── symbol=GM/     (281 parquet files)
├── symbol=INTC/   (281 parquet files)
└── symbol=NTLA/   (281 parquet files)
```

**Conclusion**: L2 data collection working correctly despite trade journaling failures.

---

## 6. SYSTEM HEALTH ISSUES

### 6.1 System Health Monitor Failures

```
2026-01-27 09:56:11 ET - SERVICE_STOP: system-health-monitor stopped (exit=1)
2026-01-27 09:58:11 ET - SERVICE_STOP: system-health-monitor stopped (exit=1)
2026-01-27 10:00:11 ET - SERVICE_STOP: system-health-monitor stopped (exit=1)
...
[Pattern repeated every 2 minutes throughout trading day]
```

**Impact**: Unknown - monitoring service did not stay running

**Exit Code 1**: Indicates crash or error condition

### 6.2 Audit Logging

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Audit entries | ~7,000+ | 0 | ❌ EMPTY |

**File**: `/home/jacobw/quantstack/logs/audit/audit_2026-01-27.jsonl`

**Content**: Only service start/stop events, no trade audit records

---

## 7. ROOT CAUSE ANALYSIS

### 7.1 L2 Scalping Trade Journal Failure

**Symptoms**:
- 6,964 fills executed
- 0 trades recorded to database
- Logs show fills with full details
- trade_journal.py exists but not writing trades

**Possible Causes**:
1. `trade_journal.py` not connected to PostgreSQL
2. Exception in fill processing being silently caught
3. Trade journal only writes on bracket order completion (brackets not working)
4. Configuration mismatch - writing to wrong database/table

**Evidence**:
```python
# L2 Scalping daily report shows:
"Total Signals: 28829"
"Trades Executed: 0"
"Completed Trades: 0"

# But logs show 6,964 fills
```

### 7.2 Intraday Paper Price Recording Error

**Symptoms**:
- Fills table has correct prices
- Trades table has signal prices (identical entry/exit)
- P&L calculated incorrectly (shows $0 when actual is -$229)

**Root Cause**: System using `signal_entry_price` instead of `fill_price`

**Code Location Hypothesis**:
```python
# WRONG (current behavior):
trade.entry_price = signal.price
trade.exit_price = signal.price  # Same signal used for both!

# CORRECT (should be):
trade.entry_price = fill.entry_price
trade.exit_price = fill.exit_price
```

### 7.3 Overnight Position Safeguard Failure

**Symptoms**:
- 5-layer protection system designed to prevent overnight positions
- All 5 layers failed
- -58 shares INTC SHORT held overnight

**Possible Causes**:
1. Bracket orders not placed (explains no auto-exit)
2. Exit monitoring not running (polling backup failed)
3. Emergency EOD script not targeting l2-scalping positions
4. Position held in wrong client/account (not monitored)

**Evidence from Logs**:
```python
# Order cancellations at shutdown, no fills:
"cancelOrder: Trade(...orderId=32852...), fills=[]"
"cancelOrder: Trade(...orderId=37076...), fills=[]"

# Final position log shows position still open:
"position=-58.0, avgCost=43.87234515"
```

---

## 8. IMPACT ASSESSMENT

### 8.1 Financial Impact

| Issue | Impact |
|-------|--------|
| Unreported L2 Scalping P&L | **UNKNOWN** - 6,964 fills not tracked |
| Intraday Paper misreporting | -$229 reported as $0 (+$229 error) |
| Overnight INTC position | Market risk held for 16+ hours |
| Total | **Material financial reporting failure** |

### 8.2 Operational Impact

| Issue | Severity |
|-------|----------|
| No L2 trade records | CRITICAL - Blind to actual trading |
| Incorrect P&L reporting | HIGH - Misleading performance data |
| Overnight position violation | CRITICAL - Risk management failure |
| Empty audit trail | HIGH - No compliance tracking |

### 8.3 System Confidence Impact

| Component | Confidence Level |
|-----------|------------------|
| L2 Scalping trade journaling | **0%** - Complete failure |
| P&L reporting accuracy | **Unknown** - Systemic error detected |
| Overnight safeguards | **Broken** - All 5 layers failed |
| Audit logging | **Non-functional** |

---

## 9. RECOMMENDED ACTIONS

### 9.1 IMMEDIATE (Today)

1. **Close the overnight position**:
   ```bash
   # Check current INTC position
   python3 /home/jacobw/quantstack/scripts/query_positions.py

   # Close -58 share INTC SHORT if still open
   ```

2. **Preserve evidence**:
   ```bash
   # Backup Jan 27 logs before they rotate
   cp /home/jacobw/quantstack/l2_scalping/logs/scalping_system.log \
      /home/jacobw/quantstack/logs/archive/scalping_system_2026-01-27.log
   ```

3. **Verify current account state**:
   ```bash
   psql -d trading -U jacobw -c "SELECT * FROM positions WHERE symbol='INTC';"
   ```

### 9.2 URGENT (This Week)

1. **Fix L2 Scalping trade_journal.py**:
   - Verify PostgreSQL connection
   - Add exception logging
   - Test with single fill
   - Validate trade records written

2. **Fix Intraday Paper price recording**:
   - Change from signal price to fill price
   - Recalculate historical P&L
   - Validate against fills table

3. **Fix Overnight Safeguards**:
   - Verify bracket order placement
   - Test emergency EOD script with open positions
   - Add position check at shutdown

4. **Fix Audit Logging**:
   - Enable audit records for fills
   - Verify audit log rotation
   - Add audit to trade_journal.py

### 9.3 MEDIUM TERM

1. **Add monitoring and alerts**:
   - Alert on fill vs. trade record mismatch
   - Alert on open positions at EOD
   - Alert on system-health-monitor failures

2. **Improve data validation**:
   - Cross-check fills vs. trades daily
   - Validate P&L calculations
   - Reconcile with IBKR statements

3. **Code review**:
   - Review all trade journaling code paths
   - Add unit tests for trade recording
   - Add integration tests for EOD flatten

---

## 10. INVESTIGATION CHECKLIST

Use this checklist to verify fixes:

- [ ] L2 Scalping: Single fill recorded to database
- [ ] L2 Scalping: Multiple fills paired into trade records
- [ ] L2 Scalping: P&L calculated correctly
- [ ] Intraday Paper: Entry/exit prices match fills
- [ ] Intraday Paper: P&L matches fills table
- [ ] Emergency EOD: Closes all positions
- [ ] Audit Log: Records fill events
- [ ] System Health Monitor: Stays running
- [ ] No overnight positions held
- [ ] Trade reconciliation matches IBKR statement

---

## 11. DATA RECOVERY OPTIONS

### 11.1 Reconstruct L2 Scalping Trades from Logs

The log file contains all fill details:
```
/home/jacobw/quantstack/l2_scalping/logs/scalping_system.log (425 MB)
```

**Recovery script approach**:
```python
# Parse execDetails lines from log
# Extract: timestamp, symbol, side, shares, price, orderId
# Pair fills into trades (entry + exit)
# Write recovered trades to PostgreSQL
# Compare recovered P&L vs. IBKR statement
```

### 11.2 Correct Intraday Paper Trades

**Current state**:
```sql
UPDATE trades
SET entry_price = (SELECT price FROM fills WHERE fills.order_id = trades.entry_order_id),
    exit_price = (SELECT price FROM fills WHERE fills.order_id = trades.exit_order_id)
WHERE DATE(entry_time) = '2026-01-27'
AND system = 'intraday-paper';
```

Then recalculate P&L from corrected prices.

---

## 12. PREVENTION MEASURES

### 12.1 Add Daily Validation Checks

```bash
#!/bin/bash
# daily_reconciliation.sh

# 1. Check for fills without trades
FILLS_WITHOUT_TRADES=$(psql -t -c "SELECT COUNT(*) FROM fills f
  LEFT JOIN trades t ON f.order_id = t.entry_order_id OR f.order_id = t.exit_order_id
  WHERE t.trade_id IS NULL AND DATE(f.timestamp) = CURRENT_DATE;")

if [ "$FILLS_WITHOUT_TRADES" -gt "0" ]; then
  echo "ALERT: $FILLS_WITHOUT_TRADES fills not matched to trades!"
  # Send alert
fi

# 2. Check for open positions at EOD
OPEN_POSITIONS=$(psql -t -c "SELECT COUNT(*) FROM positions WHERE qty != 0;")

if [ "$OPEN_POSITIONS" -gt "0" ]; then
  echo "ALERT: $OPEN_POSITIONS open positions at EOD!"
  # Send alert
fi

# 3. Check P&L matches fills
# ... (add logic)
```

### 12.2 Improve Logging

```python
# Add to trade_journal.py
logger.info(f"Recording trade: {symbol} {direction} entry={entry_price} exit={exit_price} pnl={pnl}")

# Add exception handling
try:
    db.write_trade(trade)
    logger.info(f"Trade {trade_id} written successfully")
except Exception as e:
    logger.error(f"FAILED to write trade {trade_id}: {e}")
    # Send alert
    raise
```

---

## Appendix A: File Locations

| File | Purpose | Status |
|------|---------|--------|
| `/home/jacobw/quantstack/l2_scalping/logs/scalping_system.log` | L2 Scalping execution log | ✓ Contains 6,964 fills |
| `/home/jacobw/quantstack/l2_scalping/logs/daily_report_2026-01-27.txt` | Daily summary | ⚠️ Shows 0 trades (WRONG) |
| `/home/jacobw/quantstack/l2_scalping/src/reporting/trade_journal.py` | Trade journaling code | ❌ Not working |
| `/home/jacobw/quantstack/logs/audit/audit_2026-01-27.jsonl` | Audit log | ❌ Empty |
| `/home/jacobw/quantstack/data/l2_maximum/features/date=2026-01-27/` | L2 data storage | ✓ Working |
| `/home/jacobw/intraday_stack/logs/paper_trade.log` | Intraday paper log | ✓ Contains fills |

---

## Appendix B: SQL Queries for Verification

```sql
-- 1. Count fills by date
SELECT DATE(timestamp) as date, COUNT(*) as fill_count
FROM fills
GROUP BY DATE(timestamp)
ORDER BY date DESC;

-- 2. Count trades by date
SELECT DATE(entry_time) as date, COUNT(*) as trade_count, SUM(pnl) as total_pnl
FROM trades
GROUP BY DATE(entry_time)
ORDER BY date DESC;

-- 3. Find fills without matching trades
SELECT f.*
FROM fills f
LEFT JOIN trades t ON f.order_id = t.entry_order_id OR f.order_id = t.exit_order_id
WHERE t.trade_id IS NULL
ORDER BY f.timestamp DESC;

-- 4. Check for open positions
SELECT symbol, SUM(qty) as total_qty
FROM fills
GROUP BY symbol
HAVING SUM(qty) != 0;

-- 5. Reconcile fills vs trades for a date
SELECT
  DATE(f.timestamp) as date,
  COUNT(DISTINCT f.event_id) as fills,
  COUNT(DISTINCT t.trade_id) as trades
FROM fills f
LEFT JOIN trades t ON (f.order_id = t.entry_order_id OR f.order_id = t.exit_order_id)
GROUP BY DATE(f.timestamp)
ORDER BY date DESC;
```

---

## Appendix C: Contact & Escalation

**Report Generated**: 2026-01-28
**Generated By**: Automated Analysis
**Severity**: CRITICAL

**Next Review**: After fixes implemented
**Expected Resolution**: 2026-01-30

---

**END OF REPORT**
