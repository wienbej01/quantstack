# Trading Report: January 22, 2026

**Report Generated**: 2026-01-23 07:24 Manila (Jan 22, 16:24 ET - After Market Close)  
**Trading Date**: January 22, 2026  
**Market Session**: 09:30 - 16:00 ET

---

## Executive Summary

Both trading systems operated successfully throughout the full trading session with comprehensive L2 data collection. The L2 scalping system executed 3,150 bracket orders with active overnight protection. The intraday paper system processed 38,515 decisions but has 2 positions that remained open overnight due to emergency EOD script failure.

**Key Metrics**:
- **L2 Data Collected**: 130,121 parquet files (3.0 GB)
- **L2 Scalping Orders**: 3,150 bracket orders placed
- **Intraday Paper Decisions**: 38,515 total decisions
- **Trading Duration**: 09:30 - 17:01 ET (7h 31m)
- **Overnight Protection**: ✅ Entry curfew active (10,784 blocks after 15:49 ET)
- **Emergency EOD**: ❌ Failed (PostgreSQL syntax error)

---

## System Performance

### Service Uptime
| Service | Start Time | End Time | Duration | Status |
|---------|------------|----------|----------|--------|
| l2-scalping | 09:26 ET | 17:01 ET | 7h 35m | ✅ Normal shutdown |
| intraday-paper | 09:28 ET | 17:02 ET | 7h 34m | ✅ Normal shutdown |
| emergency-eod-close | 15:55 ET | - | - | ❌ Failed (syntax error) |

### SIP Universe Selection
**Generated**: 09:13 ET (09:10 timer)  
**Universe Size**: 1,796 symbols screened  
**Selected**: 7 symbols (score ≥ 0.7)

| Symbol | Score | Exchange | Price | Volume | Dollar Volume |
|--------|-------|----------|-------|--------|---------------|
| UNG | 0.855 | ARCA | $14.20 | 5.2M | $72.4M |
| INTC | 0.808 | NYSE | $54.16 | 5.5M | $299.2M |
| GLSI | 0.749 | NYSE | $27.71 | 1.6M | $51.5M |
| CORT | 0.736 | NYSE | $44.21 | 1.2M | $55.5M |
| JANX | 0.725 | - | $13.85 | 833K | $12.2M |
| ABT | 0.716 | - | $112.28 | 520K | $59.1M |
| ASTS | 0.712 | - | $110.65 | 694K | $75.9M |

**Traded Symbols**: INTC, GLSI, CORT (NYSE-only, UNG filtered as ARCA ETF)

---

## L2 Scalping System

### Trading Activity
- **Bracket Orders Placed**: 3,150
- **Trade Notifications Sent**: 247 (filled entries)
- **Total Trading Events**: 33,248 (entries, exits, bracket updates)
- **Symbols Traded**: INTC, GLSI, CORT

### Overnight Protection Performance
✅ **Entry Curfew Active**: 10,784 entry attempts blocked after 15:49 ET
- Curfew threshold: 660 seconds (11 minutes) before market close
- First block: 15:49:02 ET (657s remaining)
- Protection working as designed

✅ **Bracket Orders**: All entries protected with stop-loss + profit target
- Stop-loss: ~10 bps from entry
- Profit target: ~15 bps from entry
- 3,150 bracket orders placed throughout session

❌ **Force Exit**: No force exits triggered (max hold time not exceeded)

### L2 Data Collection
**Total Files**: 130,121 parquet files  
**Total Size**: 3.0 GB  
**Collection Period**: 09:30:09 - 17:01:11 ET (7h 31m)

| Symbol | Files | Size | Avg File Size |
|--------|-------|------|---------------|
| INTC | 43,374 | 1,015 MB | 24 KB |
| CORT | 43,373 | 1,015 MB | 24 KB |
| GLSI | 43,374 | 1,015 MB | 24 KB |

**Data Quality**: ✅ Consistent file counts and sizes across all symbols  
**Storage Path**: `/home/jacobw/quantstack/data/l2_maximum/features/date=2026-01-22/`

---

## Intraday Paper Trading System

### Decision Processing
**Total Decisions**: 38,515 decisions across 3 symbols

| Symbol | Decisions | % of Total |
|--------|-----------|------------|
| INTC | 13,988 | 36.3% |
| CORT | 12,703 | 33.0% |
| GLSI | 11,824 | 30.7% |

**Decision Rate**: ~85 decisions/minute (1.4 decisions/second)

### Trade Execution
**Completed Trades**: 1 trade (UNG - closed via SYNC)
- Symbol: UNG (ARCA ETF)
- Direction: Short
- Entry: 14:35:17 ET
- Exit: 14:35:18 ET (1 second hold)
- Exit Reason: SYNC (position sync with IBKR)
- P&L: $0.00

### ⚠️ Open Positions (Overnight Risk)
**2 positions remained open** due to emergency EOD script failure:

| Symbol | Direction | Entry Time | Entry Price | Qty | Status |
|--------|-----------|------------|-------------|-----|--------|
| ASTS | Short | 09:35:11 ET | $105.395 | 100 | OPEN |
| GLSI | Long | 09:35:14 ET | $22.30 | 100 | OPEN |

**Risk Exposure**:
- ASTS: Short 100 shares @ $105.395 = -$10,539.50 exposure
- GLSI: Long 100 shares @ $22.30 = +$2,230.00 exposure
- Total notional: $12,769.50

**Entry Time Analysis**: Both positions entered at 09:35 ET (5 minutes after market open)
- These are early session entries, not late-day positions
- Held for entire trading session (6h 25m)
- Should have been closed by normal exit logic or emergency EOD

---

## Issues Identified

### 🔴 Critical: Emergency EOD Script Failure
**Service**: emergency-eod-close.service  
**Time**: 15:55 ET  
**Error**: PostgreSQL syntax error - using SQLite syntax (`?`) instead of PostgreSQL (`%s`)

```
psycopg2.errors.SyntaxError: syntax error at or near ","
LINE 3: exit_time = ?,
```

**Impact**: 2 positions remained open overnight  
**Root Cause**: Script not updated for PostgreSQL migration (still using SQLite placeholders)

**Action Required**: 
1. Fix emergency_eod_close.py to use PostgreSQL syntax
2. Manually close open positions when market opens
3. Test emergency EOD script before next trading session

### 🟡 Warning: Intraday Paper Exit Logic
**Observation**: Positions entered at 09:35 ET remained open until EOD
- Normal exit logic did not trigger for 6h 25m
- Positions should have hit stop-loss, profit target, or time-based exit
- Suggests potential issue with exit signal generation or order execution

**Action Required**: Review intraday paper exit logic and order management

---

## Data Storage Summary

### L2 Data
- **Location**: `/home/jacobw/quantstack/data/l2_maximum/features/date=2026-01-22/`
- **Format**: Parquet files (partitioned by symbol)
- **Size**: 3.0 GB (130,121 files)
- **Retention**: Available for analysis and backtesting

### Trading Data (PostgreSQL)
- **Database**: `trading` (user: jacobw)
- **Decisions**: 38,515 records
- **Trades**: 3 records (1 closed, 2 open)
- **Orders**: Not queried
- **Fills**: Not queried

### SIP Universe
- **Location**: `/home/jacobw/intraday_stack/data/daily_sip/date=2026-01-22/sip_universe.json`
- **Size**: 1,796 symbols screened → 7 selected → 3 traded

---

## Recommendations

### Immediate Actions (Before Next Session)
1. **Fix emergency EOD script** - Update PostgreSQL syntax
2. **Close open positions** - Manually close ASTS and GLSI when market opens
3. **Test emergency EOD** - Run test with PostgreSQL database
4. **Review exit logic** - Investigate why positions held for 6+ hours

### System Improvements
1. **Add position monitoring** - Alert on positions open > 1 hour
2. **Pre-flight checks** - Verify emergency EOD script in preflight-check.service
3. **Exit logic audit** - Review intraday paper exit signal generation
4. **Database migration** - Complete PostgreSQL migration for all scripts

### Data Quality
✅ L2 data collection is excellent - consistent, complete, and well-structured  
✅ Decision processing is active and balanced across symbols  
❌ Trade execution needs review - very low trade count vs decision count

---

## System Health: GOOD (with caveats)

**Strengths**:
- ✅ Full session uptime for both trading systems
- ✅ Comprehensive L2 data collection (3.0 GB)
- ✅ Entry curfew working perfectly (10,784 blocks)
- ✅ Bracket orders on all L2 scalping entries
- ✅ High decision processing rate (38,515 decisions)

**Weaknesses**:
- ❌ Emergency EOD script failed (PostgreSQL syntax)
- ❌ 2 positions held overnight (risk exposure)
- ⚠️ Low trade execution rate (1 completed trade)
- ⚠️ Positions held for 6+ hours without exit

**Overall Assessment**: Systems operated reliably with excellent data collection, but overnight position risk due to emergency EOD failure requires immediate attention.

---

**Next Session**: January 23, 2026  
**Action Items**: Fix emergency EOD script, close open positions, review exit logic
