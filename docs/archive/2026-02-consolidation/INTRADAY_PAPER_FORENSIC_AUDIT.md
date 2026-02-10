# Intraday-Paper Forensic Audit Report

**Date**: 2026-01-24  
**System**: Intraday Paper Trading  
**Audit Scope**: End-to-end validation from signal generation to order placement

---

## Executive Summary

**Status**: ✗ **SYSTEM NOT TRADING - 2 CRITICAL ISSUES FOUND**

1. ✓ **Timestamp parsing bug** - FIXED (dateutil.parser.parse implemented)
2. ✗ **Signal age validation bug** - FIXED (overly aggressive 5-minute limit)

### Root Cause

The system generated 6 tradeable candidates on Jan 23 but **rejected 100% of them as "stale"** due to an overly aggressive 5-minute age limit. Signals that were 35 minutes old (but from the same trading day) were incorrectly rejected.

---

## Issue #1: Timestamp Parsing Bug ✓ RESOLVED

### Problem
- `datetime.fromisoformat()` cannot parse timezone-aware strings like "2026-01-22 14:26:00-05:00"
- Error: "value must be an integer, received <class 'str'> for year"

### Fix Applied
```python
from dateutil import parser as dateutil_parser
signal_time = dateutil_parser.parse(rc.timestamp)
```

### Verification
✓ Tested with 4 timestamp formats - all parse successfully  
✓ Code change confirmed in `/home/jacobw/intraday_stack/scripts/paper_trade.py` line 651

---

## Issue #2: Signal Age Validation Bug ✗ CRITICAL - NOW FIXED

### Problem
Original logic rejected signals older than 300 seconds (5 minutes):

```python
max_signal_age = 300  # 5 minutes
if signal_age_seconds > max_signal_age:
    logger.warning(f"STALE SIGNAL REJECTED...")
    return
```

### Evidence from Jan 23 Logs
```
2026-01-23 15:25:19 - WARNING - STALE SIGNAL REJECTED: PLUG age=2120s (max=300s) timestamp=2026-01-23 14:50:00-05:00
2026-01-23 15:25:19 - WARNING - STALE SIGNAL REJECTED: INTC age=440s (max=300s) timestamp=2026-01-23 15:18:00-05:00
2026-01-23 15:25:19 - WARNING - STALE SIGNAL REJECTED: SLV age=1040s (max=300s) timestamp=2026-01-23 15:08:00-05:00
```

**Result**: 6 tradeable candidates generated, 0 orders placed (100% rejection rate)

### Root Cause Analysis

The 5-minute limit was intended to prevent **overnight signals from executing at market open** at stale prices. However, it also rejected valid intraday signals that were simply generated from older bars.

Example:
- Signal generated from 14:50 bar
- Evaluated at 15:25 (35 minutes later)
- Same trading day, valid price context
- **Incorrectly rejected**

### Fix Implemented

New logic:
1. **Reject signals from different trading day** (prevents overnight stale signals)
2. **During first 30 minutes of trading (09:30-10:00 ET)**: Reject signals older than 10 minutes
3. **After 10:00 ET**: Accept all signals from same trading day (no age limit)

```python
# Reject signals from different trading day
if signal_et.date() != now_et.date():
    logger.warning(f"STALE SIGNAL REJECTED: {rc.symbol} from different day")
    return

# During first 30 minutes, reject signals older than 10 minutes
market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
in_first_30min = market_open <= now_et < market_open + timedelta(minutes=30)

if in_first_30min and signal_age_seconds > 600:
    logger.warning(f"STALE SIGNAL REJECTED: {rc.symbol} age={signal_age_seconds:.0f}s (max=600s during market open)")
    return

# After first 30 minutes, accept all same-day signals
```

### Validation

| Scenario | Signal Age | Old Logic | New Logic | Correct |
|----------|-----------|-----------|-----------|---------|
| Mid-day, 5 min old | 300s | ✓ Accept | ✓ Accept | ✓ |
| Mid-day, 35 min old | 2100s | ✗ Reject | ✓ Accept | ✓ |
| Mid-day, 2 hours old | 7200s | ✗ Reject | ✓ Accept | ✓ |
| Market open, 5 min old | 300s | ✓ Accept | ✓ Accept | ✓ |
| Market open, 15 min old | 900s | ✗ Reject | ✗ Reject | ✓ |
| Prior day signal | 86400s | ✗ Reject | ✗ Reject | ✓ |

---

## Other Findings

### ✓ IBKR Connection
- Connected successfully on Jan 23
- Client ID 111 confirmed
- Portfolio updates received throughout the day
- No connection issues

### ✓ Signal Generation
- `CandidateGenerator` produced 6 candidates
- Signals generated from live 1-minute bars
- Universe: PLUG, INTC, SLV, UNG, NVDA, FTNT

### ✓ Journal Database
- Database exists at `/home/jacobw/intraday_stack/data/journal/events.db`
- Tables: decisions, orders, fills, risk_events, trades
- No corruption detected

### ✓ Configuration
- Config file exists: `/home/jacobw/intraday_stack/configs/paper_trading.yaml`
- IBKR parameters correct (host: 127.0.0.1, port: 7494, client_id: 111)

### ✓ Script Syntax
- `paper_trade.py` compiles successfully
- No syntax errors
- All imports available

---

## Impact Assessment

### Jan 23, 2026 Trading Day
- **Orders placed**: 0
- **Reason**: 100% signal rejection due to overly aggressive age limit
- **Missed opportunities**: 6 tradeable candidates rejected

### With Fixes Applied
- **Timestamp parsing**: Will handle all signal formats
- **Signal age validation**: Will accept valid same-day signals
- **Expected behavior**: Signals from same trading day will execute

---

## Recommendations

### Immediate Actions
1. ✓ **Deploy timestamp parsing fix** - Already applied
2. ✓ **Deploy signal age validation fix** - Already applied
3. **Test with dry-run mode** - Verify fixes before live trading
4. **Monitor first trading day** - Confirm signals are accepted

### Monitoring
- Watch for "STALE SIGNAL REJECTED" warnings
- Verify signals from same day are accepted
- Confirm orders are placed for valid candidates

### Future Improvements
1. **Add signal generation timestamp logging** - Track when candidates are created
2. **Add bar age metrics** - Monitor how old bars are when processed
3. **Consider dynamic age limits** - Adjust based on market volatility
4. **Add signal freshness dashboard** - Real-time monitoring of signal ages

---

## Files Modified

1. `/home/jacobw/intraday_stack/scripts/paper_trade.py`
   - Line 651: Timestamp parsing fix (dateutil.parser.parse)
   - Lines 645-685: Signal age validation logic rewrite

---

## Testing Checklist

- [x] Timestamp parsing handles all formats
- [x] Same-day signals accepted after 10:00 ET
- [x] Prior-day signals rejected
- [x] Market open signals (>10 min old) rejected
- [x] Market open signals (<10 min old) accepted
- [ ] Live dry-run test (pending next trading day)
- [ ] Live trading test (pending verification)

---

## Conclusion

**Both critical issues have been resolved:**

1. ✓ Timestamp parsing now handles all signal formats
2. ✓ Signal age validation now accepts valid same-day signals

The system is ready for testing. Recommend running in dry-run mode for one trading day to verify fixes before enabling live trading.

**Next Steps**: Monitor logs on next trading day to confirm signals are accepted and orders are placed.
