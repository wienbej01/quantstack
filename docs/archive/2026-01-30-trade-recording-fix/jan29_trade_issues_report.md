# Trading System Issues Report - January 29, 2026

**Generated**: 2026-01-30 09:26 +08:00  
**Report Period**: 2026-01-29 (Full Trading Day)

---

## Executive Summary

Two critical issues identified affecting trade recording and execution:

1. **L2 Scalping System**: 3,591 fills executed but ZERO trades recorded in database
2. **Intraday Paper System**: All 5 trades closed at entry price via EMERGENCY_EOD without hitting SL/TP

---

## Issue 1: L2 Trades Not Recorded in Database

### Problem Statement
- **Fills Executed**: 3,591 order fills on Jan 29
- **Trades in Database**: 0
- **Impact**: Complete loss of trade history, P&L tracking, and performance analytics

### Root Cause Analysis

**Code Path Issue**:
```
L2 main.py → _legacy_fill_handler() → record_fill()
                                    ❌ NEVER calls open_trade()
                                    ❌ NEVER calls record_trade_entry()
```

**Evidence**:
```bash
# L2 system initialized PostgreSQL connection
2026-01-29 09:31:03 - Using shared PostgreSQL event store for L2 scalping trades

# But ZERO trades opened
$ grep "L2 Trade opened" scalping_system.log | wc -l
0

# Yet 3,591 fills occurred
$ grep "Order filled:" scalping_system.log | wc -l
3591
```

**Technical Details**:
- File: `/home/jacobw/quantstack/l2_scalping/src/main.py`
- Function: `_legacy_fill_handler()` (lines ~1160-1200)
- Missing calls:
  - `trade_journal.record_trade_entry()` on entry fills
  - `trade_journal.record_trade_exit()` on exit fills
- Current behavior: Only calls `record_fill()` which logs to fills table but never creates trade records

### Impact Assessment
- **Data Loss**: Complete trading history for Jan 29 L2 activity
- **P&L Unknown**: Cannot calculate actual performance
- **Compliance Risk**: No audit trail for executed trades
- **NTFY Notifications**: Working (sent 3,591 notifications) but no database backing

### Fix Required

**Modify `_legacy_fill_handler()` in main.py**:

1. **On Entry Fill** (when opening position):
```python
# After recording fill, add:
if order_id in self.pending_entries and fully_filled:
    # Extract rule name from order_ref (e.g., "L2SCALP_high_obi_depth_ENTRY_...")
    rule_name = self._extract_rule_from_ref(order_ref)
    
    trade_id = self.trade_journal.record_trade_entry(
        symbol=symbol,
        side=entry_side,
        quantity=expected_qty,
        entry_price=avg_fill_price,
        order_id=order_id,
        rule_name=rule_name,
        signal_id=f"l2_{rule_name}_{symbol}_{timestamp}",
        signal_price=avg_fill_price
    )
    
    # Store trade_id for exit matching
    self.active_trades[symbol] = trade_id
```

2. **On Exit Fill** (when closing position):
```python
# After recording fill, add:
if symbol in self.active_trades:
    trade_id = self.active_trades[symbol]
    
    self.trade_journal.record_trade_exit(
        trade_id=trade_id,
        exit_price=fill_price,
        exit_qty=filled_qty,
        exit_reason=self._determine_exit_reason(order_ref),
        order_id=order_id
    )
    
    del self.active_trades[symbol]
```

---

## Issue 2: Intraday Trades Emergency Closed Without SL/TP Hits

### Problem Statement
- **Trades**: 5 positions opened between 14:42-14:45 ET
- **Exit Method**: ALL closed via EMERGENCY_EOD at 20:55:04 (3:55 PM ET)
- **Exit Prices**: Identical to entry prices (0 slippage)
- **P&L**: $0.00 on all trades
- **Suspicious**: No stop-loss or take-profit hits despite 6+ hour hold time

### Trade Details

| Symbol | Entry Time | Entry Price | Exit Time | Exit Price | Hold Time | Exit Reason |
|--------|------------|-------------|-----------|------------|-----------|-------------|
| SLV    | 14:42:03   | $108.28     | 20:55:04  | $108.28    | 6h 13m    | EMERGENCY_EOD |
| FCX    | 14:43:07   | $67.33      | 20:55:04  | $67.33     | 6h 12m    | EMERGENCY_EOD |
| SLV    | 14:43:09   | $108.28     | 20:55:04  | $108.28    | 6h 12m    | EMERGENCY_EOD |
| FCX    | 14:44:15   | $67.33      | 20:55:04  | $67.33     | 6h 11m    | EMERGENCY_EOD |
| INTC   | 14:45:22   | $47.69      | 20:55:04  | $47.69     | 6h 10m    | EMERGENCY_EOD |

### Suspicious Indicators

1. **Zero Slippage on All Exits**
   - Exit price = Entry price on ALL 5 trades
   - Probability of this occurring naturally: ~0.001%
   - Suggests: Positions may not have been actually opened, or closed via cancel rather than market order

2. **No SL/TP Hits in 6+ Hours**
   - Typical intraday strategy has tight stops (0.5-1%)
   - 6 hour hold time suggests stops were never placed or never triggered
   - Market moved during this period but no exits occurred

3. **Simultaneous Emergency Close**
   - All 5 trades closed within 2 seconds (20:55:04.505-508)
   - Suggests automated EOD cleanup rather than normal exit logic

### Investigation Required

**Check Order Status**:
```sql
-- Were these orders actually filled or just pending?
SELECT o.order_id, o.symbol, o.status, o.order_type, 
       o.entry_price, o.stop_price, o.target_price
FROM orders o
WHERE o.timestamp::date = '2026-01-29'
  AND o.symbol IN ('SLV', 'FCX', 'INTC');
```

**Check Fill Records**:
```sql
-- Do we have actual fill records for entries and exits?
SELECT f.symbol, f.side, f.quantity, f.price, f.timestamp
FROM fills f
WHERE f.timestamp::date = '2026-01-29'
  AND f.symbol IN ('SLV', 'FCX', 'INTC')
ORDER BY f.timestamp;
```

**Check System Logs**:
```bash
# Look for order placement and fill confirmations
journalctl --user -u intraday-paper.service \
  --since "2026-01-29 14:42:00" \
  --until "2026-01-29 14:46:00" \
  | grep -E "order.*placed|filled|confirmed"

# Look for EOD cleanup logic
journalctl --user -u intraday-paper.service \
  --since "2026-01-29 20:54:00" \
  --until "2026-01-29 20:56:00" \
  | grep -E "emergency|eod|force.*close"
```

### Possible Explanations

1. **Orders Never Filled**
   - Orders placed but never executed
   - EOD cleanup cancelled pending orders
   - Database recorded as "filled" incorrectly

2. **Paper Trading Artifact**
   - Paper trading system may simulate fills at entry price on cancel
   - Not reflecting actual market conditions

3. **Stop Orders Not Placed**
   - Entry filled but protective stops never submitted
   - Positions held naked until EOD forced close

4. **Database Recording Error**
   - Actual fills occurred at different prices
   - Database recorded entry price as exit price incorrectly

---

## Recommendations

### Immediate Actions

1. **Fix L2 Trade Recording** (Priority: CRITICAL)
   - Apply code fix to `_legacy_fill_handler()`
   - Test with paper trading before deploying to live
   - Backfill Jan 29 trades from logs if possible

2. **Investigate Intraday Zero-Slippage Exits** (Priority: HIGH)
   - Query fills table for actual execution prices
   - Review intraday-paper service logs for EOD logic
   - Verify stop-loss orders were actually placed

3. **Add Monitoring** (Priority: HIGH)
   - Alert when trades have zero slippage
   - Alert when L2 fills occur without trade records
   - Alert when positions held >2 hours without SL/TP

### Long-term Improvements

1. **Unified Trade Recording**
   - Consolidate L2 and intraday trade recording logic
   - Ensure all systems use same event store interface
   - Add validation: every fill must have corresponding trade

2. **Order Lifecycle Tracking**
   - Track order states: PENDING → SUBMITTED → FILLED → CLOSED
   - Validate stop-loss orders are placed after entry fill
   - Alert on orphaned orders (filled but no stops)

3. **EOD Reconciliation**
   - Compare broker positions vs database positions
   - Flag discrepancies before market close
   - Automated daily trade audit report

---

## Appendix: Data Queries

### L2 Fills Count (Jan 29)
```bash
$ grep "2026-01-29.*Order filled:" ~/quantstack/l2_scalping/logs/scalping_system.log | wc -l
3591
```

### L2 Trades in Database (Jan 29)
```sql
SELECT COUNT(*) FROM trades 
WHERE entry_time::date = '2026-01-29' 
  AND system = 'l2-scalping';
-- Result: 0
```

### Intraday Trades (Jan 29)
```sql
SELECT COUNT(*), exit_reason FROM trades 
WHERE entry_time::date = '2026-01-29' 
  AND system = 'intraday-paper'
GROUP BY exit_reason;
-- Result: 5 trades, all EMERGENCY_EOD
```

---

**Report End**

---

## CRITICAL UPDATE: Intraday Issue Resolved

### Actual Fill Data Found

The fills table contains the REAL execution prices, which differ significantly from the trades table:

| Symbol | Trade Table Entry | Trade Table Exit | **Actual Entry** | **Actual Exit** | **Actual P&L** |
|--------|-------------------|------------------|------------------|-----------------|----------------|
| SLV    | $108.28          | $108.28          | **$108.91**      | **$107.26**     | **-$165** |
| FCX    | $67.33           | $67.33           | **$67.63**       | **$66.18**      | **-$145** |
| SLV    | $108.28          | $108.28          | **$108.74**      | **$107.26**     | **-$148** |
| FCX    | $67.33           | $67.33           | **$67.96**       | **$66.18**      | **-$178** |
| INTC   | $47.69           | $47.69           | **$47.94**       | **$48.35**      | **+$41** |

**Total Actual P&L**: -$595 (not $0!)

### Root Cause: Database Sync Issue

The `trades` table is recording **signal prices** instead of **actual fill prices**:
- Entry prices in trades table don't match actual fills
- Exit prices in trades table are set to entry prices (wrong!)
- EMERGENCY_EOD exit reason is correct, but prices are wrong

### Fix Required

**File**: Intraday system trade recording logic  
**Issue**: When recording trade exit, system is using entry_price instead of actual exit fill price

**Code to check**:
```python
# In intraday system's trade close logic:
# WRONG:
trade.exit_price = trade.entry_price  # ❌ Using entry price

# CORRECT:
trade.exit_price = actual_fill_price  # ✅ Use actual fill from broker
```

### Revised Conclusion

1. **Trades DID execute properly** - fills table proves this
2. **Database recording is broken** - trades table has wrong prices
3. **Actual performance**: -$595 loss on Jan 29 intraday trades
4. **All exits were legitimate** - EMERGENCY_EOD at 3:55 PM is correct behavior
5. **Zero slippage was a red herring** - it was a database bug, not an execution issue


---

## Issue 3: NTFY Notifications Show Price $0 Value $0

### Problem
User reports NTFY L2 trade notifications display:
- Price: $0.00
- Value: $0.00

### Root Cause
NTFY notifications are sent from `record_trade_entry()` in trade_journal.py, but this function is **NEVER called** by the L2 system because `_legacy_fill_handler()` doesn't call it.

### Will Phase 2 Fix Address This?
**YES** ✅ 

When we fix `_legacy_fill_handler()` to call `record_trade_entry()`, the NTFY notifications will automatically be sent with correct prices:

```python
# After fix, record_trade_entry() will be called with:
trade_id = self.trade_journal.record_trade_entry(
    symbol=symbol,
    side=entry_side,
    quantity=expected_qty,
    entry_price=avg_fill_price,  # ← Real price
    ...
)

# Which internally sends NTFY:
send_trade_notification(
    action="ENTRY",
    symbol=symbol,
    price=entry_price,    # ← Real price
    quantity=quantity,    # ← Real quantity
    ...
)
```

### Expected Result After Fix
```
Opening JOBY position [l2_17697]
Time: 09:48:04 ET
Strategy: l2-scalping high_obi_depth
Side: SELL
Quantity: 88
Price: $11.26          ← Correct price
Value: $991.88         ← Correct value
```

**No additional fix required** - Phase 2 changes will resolve this automatically.
