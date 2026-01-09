# Trading System Performance Report
**Date**: 2026-01-10 02:53 UTC+8  
**Report Period**: 2026-01-09 (Trading Day)

---

## Executive Summary

| Metric | Status | Value |
|--------|--------|-------|
| **Services Running** | ⚠️ Partial | 3/5 active |
| **Trades Executed** | ⚠️ Low | 21 total (5 closed, 16 open) |
| **P&L** | ⚠️ Neutral | $0.00 |
| **Win Rate** | ❌ Poor | 0.0% |
| **L2 Collection** | ✅ Good | 57,285 records, 2 symbols |
| **SIP Universe** | ✅ Good | 4 symbols from 1,796 tested |

---

## 1. SERVICE STATUS

### Active Services ✅
- **l2-collector**: Running (20h+ uptime)
- **l2-scalping**: Running (10h+ uptime)
- **l2-watchdog**: Running (monitoring)

### Failed Services ❌
- **intraday-paper**: FAILED (preflight issue)
- **system-health-monitor**: INACTIVE (not scheduled)

### Error Summary (Last 60 minutes)
- l2-collector: 0 errors
- l2-scalping: 3 errors (async reconnect attempts)
- intraday-paper: 0 errors (not running)
- l2-watchdog: 0 errors
- system-health-monitor: 0 errors

---

## 2. TRADE JOURNAL ANALYSIS

### Trade Statistics
| Metric | Value |
|--------|-------|
| Total Trades | 21 |
| Closed Trades | 5 |
| Open Trades | 16 |
| Winning Trades | 0 |
| Losing Trades | 5 |
| Win Rate | 0.0% |
| **Total P&L** | **$0.00** |

### Trades by System
- **intraday-paper**: 0 trades (service failed)
- **l2-scalping**: 0 trades (no signals generated)
- **unknown**: 21 trades (legacy/manual trades from previous sessions)

### Analysis
- **No new trades today** - intraday-paper failed at startup, l2-scalping generated no signals
- **21 open positions** - Likely from previous trading sessions, not today
- **Zero P&L** - All closed trades broke even (entry/exit at same price)
- **System Issue**: Trade system tracking not properly attributing trades to systems

---

## 3. L2 DATA COLLECTION

### Collection Performance
| Metric | Value |
|--------|-------|
| Symbols Collected | 2 |
| Estimated Records | 57,285 |
| Collection Rate | ~1,200 records/hour |
| Active Symbols | SMR, VST |

### Data Quality
- ✅ Consistent collection (2 symbols rotating)
- ✅ High record volume (57k+ snapshots)
- ✅ 32 features per record (OBI, depth, spread, deltas)
- ⚠️ Limited symbol coverage (only 2 of 4 SIP symbols)

### Issues
- L2 collection limited to 3 concurrent symbols max (IBKR account limit)
- Currently rotating SMR, VST (missing UNG, INSM)
- Rotation strategy needs optimization

---

## 4. SIP UNIVERSE GENERATION

### SIP Performance
| Metric | Value |
|--------|-------|
| Universe Tested | 1,796 symbols |
| Symbols Qualified | 4 |
| Qualification Rate | 0.22% |
| Score Floor | 0.70 |

### Qualified Symbols
1. **SMR** - Score: 0.811 (highest)
2. **UNG** - Score: 0.722
3. **VST** - Score: 0.720
4. **INSM** - Score: 0.704

### Analysis
- ✅ SIP generation working correctly
- ✅ Full 1,796 symbol universe tested (no hardcoding)
- ⚠️ Very strict score_floor=0.70 (only 0.22% qualified)
- ⚠️ Limited trading opportunities (4 symbols)

---

## 5. LOG ANALYSIS

### Orchestrator Logs
```
Total Lines:    16,242
Errors:         645 (3.97%)
Warnings:       1,044 (6.42%)
Infos:          13,479 (82.95%)
```

**Error Breakdown**:
- Async event loop reconnection attempts
- IBKR connection timeouts
- SIP generation retries

### Paper Trading Logs
```
Total Lines:    84
Errors:         4 (4.76%)
Warnings:       0 (0.00%)
Infos:          8 (9.52%)
```

**Status**: Service just started, minimal activity

---

## 6. SYSTEM ISSUES & ROOT CAUSES

### Critical Issues

#### 1. Intraday-Paper Service Failed ❌
- **Status**: FAILED (exit code 1)
- **Cause**: Preflight check timeout on IBKR connection
- **Impact**: No paper trading executed today
- **Fix**: Restart service, check IBKR Gateway connectivity

#### 2. L2-Scalping No Trades ❌
- **Status**: Running but no signals
- **Cause**: Likely no qualifying L2 signals from 4 SIP symbols
- **Impact**: Zero trading activity from L2 system
- **Fix**: Review signal generation thresholds

#### 3. System Health Monitor Inactive ⚠️
- **Status**: Not scheduled (timer not active)
- **Cause**: Timer may not be enabled
- **Impact**: No automated health checks running
- **Fix**: Enable system-health-monitor.timer

### Performance Issues

#### 1. Very Low SIP Qualification Rate (0.22%)
- Only 4 symbols from 1,796 tested
- score_floor=0.70 is extremely strict
- Limits trading opportunities significantly

#### 2. L2 Collection Limited to 2 Symbols
- IBKR account limit: 3 concurrent L2 subscriptions
- Currently rotating SMR, VST
- Missing UNG, INSM from SIP universe

#### 3. Trade Attribution Broken
- 21 trades marked as "unknown" system
- Should be attributed to intraday-paper or l2-scalping
- Prevents accurate per-system performance tracking

---

## 7. PERFORMANCE METRICS

### Uptime
| Service | Uptime | Status |
|---------|--------|--------|
| l2-collector | 20+ hours | ✅ Excellent |
| l2-scalping | 10+ hours | ✅ Good |
| l2-watchdog | Running | ✅ Good |
| intraday-paper | Failed | ❌ Critical |
| system-health-monitor | Inactive | ⚠️ Warning |

### Data Pipeline
| Stage | Status | Volume |
|-------|--------|--------|
| SIP Generation | ✅ Working | 1,796 symbols tested |
| SIP Qualification | ✅ Working | 4 symbols qualified |
| L2 Collection | ✅ Working | 57,285 records |
| Paper Trading | ❌ Failed | 0 trades |
| L2 Scalping | ⚠️ Running | 0 trades |

### Trading Activity
| Metric | Value | Status |
|--------|-------|--------|
| Trades Executed | 0 | ❌ None today |
| Trades Open | 16 | ⚠️ Legacy positions |
| Win Rate | 0.0% | ❌ No wins |
| P&L | $0.00 | ⚠️ Neutral |

---

## 8. RECOMMENDATIONS

### Immediate Actions (Critical)
1. **Restart intraday-paper service**
   ```bash
   sudo systemctl restart intraday-paper
   ```

2. **Enable system-health-monitor timer**
   ```bash
   sudo systemctl enable --now system-health-monitor.timer
   ```

3. **Verify IBKR Gateway connectivity**
   - Check Gateway GUI shows "API client connected"
   - Verify port 7497 is listening

### Short-term Fixes (High Priority)
1. **Investigate L2-scalping signal generation**
   - Review why no signals generated from 4 SIP symbols
   - Check signal thresholds and context filters

2. **Fix trade attribution**
   - Ensure trades are properly tagged with system name
   - Update event_store to track system correctly

3. **Optimize L2 symbol rotation**
   - Implement smarter rotation to cover all 4 SIP symbols
   - Consider dynamic rotation based on volatility

### Medium-term Improvements
1. **Relax SIP score_floor**
   - Current 0.70 too strict (only 0.22% qualification)
   - Consider 0.50-0.60 for more trading opportunities

2. **Expand L2 collection**
   - Request higher concurrent L2 limit from IBKR
   - Or implement sequential collection with faster rotation

3. **Enhance monitoring**
   - Add real-time dashboard for service status
   - Implement automated alerts for service failures

---

## 9. NEXT STEPS

### For Next Trading Session (2026-01-10)
1. Verify all services start correctly at 20:00 Manila
2. Monitor preflight-check at 20:00 for any issues
3. Confirm intraday-paper connects successfully
4. Track L2-scalping signal generation
5. Monitor trade execution and P&L

### For System Optimization
1. Review and adjust SIP score_floor
2. Implement better trade attribution
3. Optimize L2 symbol rotation
4. Add comprehensive monitoring dashboard

---

## Summary

**Current Status**: ⚠️ Partially Operational
- Data collection working (L2, SIP)
- Trading execution failed (intraday-paper)
- L2 scalping running but no signals
- Zero trading activity today

**Key Metrics**:
- 3/5 services active
- 0 trades executed today
- 57,285 L2 records collected
- 4 SIP symbols qualified from 1,796 tested

**Action Required**: Restart failed services and investigate signal generation issues before next trading session.

