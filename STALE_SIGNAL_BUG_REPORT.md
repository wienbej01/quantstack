# Critical Bug Report: Stale Signals & Wrong Price Recording

**Date**: 2026-01-23  
**Severity**: CRITICAL  
**Impact**: Trades executed with 24-hour old signals, wrong prices recorded in database

---

## Issue 1: Stale Signal Carryover (CRITICAL)

### The Problem
System used a **24-hour old signal** to execute a trade:
- Signal generated: Jan 21 at 14:28 ET
- Trade executed: Jan 22 at 09:35 ET (next morning, 19 hours later)
- Signal price: $13.67 (yesterday's price)
- Actual market price: $14.20 (today's price)
- **Price gap: $0.53 per share** (3.9% overnight move)

### Evidence
```
signal_id: UNG_2026-01-21 14:28:00-05:00
entry_time: 2026-01-22T14:35:17 (09:35 ET)
```

### Root Cause
**The system does NOT start fresh each day** - it's carrying over signals from previous sessions.

Expected behavior:
- System starts at 09:28 ET
- Generates fresh signals
- Trades on current market data

Actual behavior:
- System starts at 09:28 ET
- **Loads old signals from database/cache**
- Trades on stale 24-hour old data

### Impact
1. **Wrong bracket orders**: Stop/target calculated from $13.67, not $14.20
2. **Immediate stop-out**: Stop @ $13.73 triggered instantly (market @ $14.20)
3. **Zero profit**: Trade closed at entry price due to bad stop placement
4. **Data corruption**: Database shows wrong entry price

---

## Issue 2: Database Records Signal Price, Not Fill Price

### The Problem
Database `entry_price` field stores **signal price** instead of **actual fill price**:

| Field | Should Be | Actually Is |
|-------|-----------|-------------|
| entry_price | $14.20 (fill) | $13.67 (signal) |
| exit_price | $14.20 (fill) | $13.67 (fallback) |

### Evidence
```
Database: entry_price = 13.67
Actual fill: price = 14.20 on IEX
Difference: $0.53 per share ($53 on 100 shares)
```

### Root Cause
`open_trade()` is called **before** the fill comes back:
```python
# 1. Trade opened with signal price
event_store.open_trade(..., entry_price=13.67, signal_price=13.67)

# 2. Order sent to market
place_order(SELL 100 UNG market)

# 3. Fill comes back later
Fill: SELL 100@14.20

# 4. Fill price never updates database
```

### Impact
1. **Wrong P&L calculations**: Based on signal price, not actual fills
2. **Wrong slippage tracking**: Can't measure real execution quality
3. **Audit trail broken**: Can't reconstruct actual trades
4. **Analysis impossible**: Historical data is wrong

---

## Fixes Implemented

### Fix 1: Add Signal Price Tracking ✅

**Database Schema**:
```sql
ALTER TABLE trades 
ADD COLUMN signal_entry_price real,
ADD COLUMN signal_exit_price real;
```

Now we track:
- `signal_entry_price`: Original signal price
- `entry_price`: Actual fill price
- `signal_exit_price`: Exit signal price  
- `exit_price`: Actual exit fill price

### Fix 2: Update EventStore ✅

**Modified**: `/home/jacobw/intraday_stack/src/journal/event_store.py`

```python
def open_trade(..., entry_price: float, signal_price: float):
    """
    Args:
        entry_price: Actual fill price (or best estimate)
        signal_price: Original signal price
    """
    # Store both prices
    INSERT INTO trades (..., entry_price, signal_entry_price)
    VALUES (..., entry_price, signal_price)
```

### Fix 3: Stale Signal Investigation ⏳

**Status**: ROOT CAUSE IDENTIFIED, FIX PENDING

**Evidence from logs**:
```
LINE 1: ...5:10.832519','UNG','reversal','short',0.741832928,np.float64...
```

System is trying to insert signals with old timestamps into database.

**Next Steps**:
1. Find where signals are persisted between sessions
2. Add signal expiration logic (max age: 5 minutes)
3. Clear signal cache on system startup
4. Add logging to track signal age

---

## Immediate Actions Required

### Before Next Trading Session

1. **✅ Database schema updated** - signal price columns added
2. **✅ EventStore updated** - records both prices
3. **⏳ Find signal persistence** - where are old signals stored?
4. **⏳ Add signal expiration** - reject signals > 5 minutes old
5. **⏳ Clear on startup** - flush all signals when system starts

### Testing Plan

1. Verify no signals from previous day are used
2. Confirm entry_price = actual fill price
3. Check signal_entry_price = original signal price
4. Validate P&L calculations use fill prices

---

## Questions to Answer

1. **Where are signals stored between sessions?**
   - Database table?
   - File cache?
   - In-memory state that persists?

2. **Why doesn't system start fresh?**
   - Is there a "resume" feature?
   - Are signals intentionally persisted?
   - Is this a bug or design?

3. **How to prevent stale signals?**
   - Add max_age check (5 minutes)?
   - Clear cache on startup?
   - Generate fresh signals only?

---

## Impact Assessment

### UNG Trade (Jan 22)
- **Intended**: Short @ $14.20 with stop @ $14.34
- **Actual**: Short @ $14.20 with stop @ $13.73 (wrong direction!)
- **Result**: Immediate stop-out, $0 P&L
- **Should have been**: Profitable short if stop was correct

### System-Wide Risk
- **All trades** may be using stale signals
- **All bracket orders** may be calculated wrong
- **All P&L** may be recorded incorrectly
- **Cannot trust** any historical data until fixed

---

## Status

**Issue 1 (Stale Signals)**: 🔴 CRITICAL - Identified but not fixed  
**Issue 2 (Wrong Prices)**: 🟡 PARTIAL - Schema fixed, need to update callers  

**Next**: Find signal persistence mechanism and add expiration logic

---

**Files Modified**:
1. `/database/trading/trades` - Added signal_entry_price, signal_exit_price columns
2. `/home/jacobw/intraday_stack/src/journal/event_store.py` - Updated to record signal prices

**Files Pending**:
1. Signal generation/loading code (location TBD)
2. Paper trading signal handling
3. L2 scalping signal handling
