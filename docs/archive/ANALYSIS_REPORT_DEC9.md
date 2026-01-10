# System Analysis Report - December 9, 2025

## Executive Summary

The current rolling intraday ML trading system has been analyzed against 6 key requirements. The system has **3 critical gaps** that must be addressed before production deployment.

---

## Requirements Status

| # | Requirement | Status | Priority |
|---|-------------|--------|----------|
| 1 | Fix data leakage | ✅ FIXED (code only) | 🔴 CRITICAL |
| 2 | Full trades list | ⚠️ PARTIAL | 🟡 IMPORTANT |
| 3 | Train on 10m data | ❌ NOT IMPLEMENTED | 🔴 CRITICAL |
| 4 | Intraday position entry | ✅ IMPLEMENTED | ✅ COMPLETE |
| 5 | Entry on 10m close, execute on 1m | ❌ NOT IMPLEMENTED | 🔴 CRITICAL |
| 6 | Position sizing (1% risk) | ✅ IMPLEMENTED | ✅ COMPLETE |

---

## Critical Findings

### 🔴 CRITICAL #1: Data Leakage Fixed in Code, Not in Data
**Issue**: Label leakage fix implemented Dec 8, but features not rebuilt.

**Impact**: All previous backtest results are invalid.

**Action Required**: 
```bash
python scripts/build_intraday_features_rolling.py
```

**Estimated Time**: 4-6 hours (rebuild time)

---

### 🔴 CRITICAL #2: Training on 1-Minute Data Instead of 10-Minute
**Issue**: System loads 1m bars directly, no resampling to 10m.

**Impact**: 
- Wrong granularity for decision-making
- Features represent 1-minute patterns, not 10-minute
- 10x more bars than intended (390 vs 39 per day)

**Action Required**: Add 10m resampling before feature engineering.

**Estimated Time**: 2-3 hours

---

### 🔴 CRITICAL #3: No Signal-to-Execution Delay
**Issue**: Decision and execution happen on same bar.

**Impact**:
- No realistic slippage modeling
- Entry prices from 10m bars (should be 1m)
- Violates requirement #5

**Action Required**: Implement two-stage architecture:
1. Generate signals on 10m bar close
2. Execute on next 1m bar close

**Estimated Time**: 4-6 hours

---

### 🟡 IMPORTANT: No Stop Loss / Take Profit Logic
**Issue**: Trades exit after fixed 5-bar time horizon only.

**Impact**:
- No actual risk management
- Can't measure stop hit rate
- Missing stop_loss and take_profit in trades output

**Action Required**: Implement intrabar stop/target monitoring.

**Estimated Time**: 6-8 hours

---

## What's Working

### ✅ Position Sizing (1% Risk)
Current implementation correctly calculates shares based on 1% equity risk:

```python
per_trade_risk = equity * 0.01  # $100 on $10k equity
stop_distance = 0.015 * price   # 1.5% stop
shares = per_trade_risk / stop_distance
```

**Example**: $10k equity, $50 stock, 1.5% stop → 133 shares

---

### ✅ Intraday Position Entry
System processes every bar during market hours (09:30-16:00), allowing entries at any time.

No fixed entry times or restrictions.

---

### ✅ Data Leakage Fix (Code)
Fix implemented in `build_intraday_features_rolling.py`:
- Filter to target date BEFORE computing forward returns
- Drop rows without same-day exit
- Prevents cross-day label leakage

**Status**: Code fixed, data not rebuilt.

---

## Implementation Roadmap

### Phase 1: 10-Minute Data Pipeline (2-3 hours)
**Goal**: Train models on 10-minute bars

**Tasks**:
1. Add 10m resampling to feature builder
2. Update feature windows for 10m granularity
3. Rebuild features from scratch
4. Validate no leakage

**Deliverable**: `run/intraday_features_rolling/features.parquet` (10m bars)

---

### Phase 2: Signal-to-Execution Delay (4-6 hours)
**Goal**: Generate signals on 10m close, execute on next 1m close

**Tasks**:
1. Load 1m bars for execution pricing
2. Implement 1-bar delay logic
3. Update backtest to use 1m entry prices
4. Track signal_timestamp vs execution_timestamp

**Deliverable**: Realistic execution with slippage

---

### Phase 3: Stop Loss / Take Profit (6-8 hours)
**Goal**: Exit trades when stop or target hit

**Tasks**:
1. Calculate ATR-based stops (1.5x ATR)
2. Set 2R take profit targets
3. Monitor every 1m bar for stop/target hits
4. Track exit_reason (stop_hit, target_hit, time_exit)

**Deliverable**: Proper risk management

---

### Phase 4: Enhanced Reporting (2-3 hours)
**Goal**: Complete trades list with all required fields

**Tasks**:
1. Add stop_loss and take_profit columns
2. Implement fee model ($0.0035/share, min $0.35)
3. Implement spread model (5 bps)
4. Calculate R-multiples
5. Generate comprehensive trade report

**Deliverable**: Full trades.csv with all fields

---

## Total Effort Estimate

| Phase | Hours | Priority |
|-------|-------|----------|
| Phase 1: 10m Data | 2-3 | 🔴 CRITICAL |
| Phase 2: Execution Delay | 4-6 | 🔴 CRITICAL |
| Phase 3: Stops/Targets | 6-8 | 🔴 CRITICAL |
| Phase 4: Reporting | 2-3 | 🟡 IMPORTANT |
| **TOTAL** | **14-20 hours** | |

**Recommended Timeline**: 4 days (4-5 hours per day)

---

## Risk Assessment

### High Risk Items
1. **10m resampling may reduce signal count** - Fewer bars = fewer opportunities
2. **Execution delay adds slippage** - Entry prices worse than signal prices
3. **Stops may hit frequently** - Could reduce win rate significantly

### Mitigation Strategies
1. Test on small dataset first (1 symbol, 1 week)
2. Compare 10m vs 1m performance before full rebuild
3. Adjust stop distance if hit rate > 70%

---

## Design Decisions Required

Before implementation, confirm:

### Decision 1: Exit Logic
**Options**:
- A) Stop/target only (no time exit)
- B) Stop/target + 4-hour max hold
- C) Stop/target + EOD flatten

**Recommendation**: Option B (stop/target + 4-hour max)

### Decision 2: Stop Calculation
**Options**:
- A) Fixed 1.5% stop
- B) ATR-based (1.5x ATR)
- C) Volatility-adjusted

**Recommendation**: Option B (ATR-based)

### Decision 3: Take Profit
**Options**:
- A) Fixed 2R target
- B) Fixed 3% target
- C) Trailing stop after 1R

**Recommendation**: Option A (2R target)

---

## Success Metrics

### Phase 1 Complete When:
- ✅ All timestamps are 10-minute aligned
- ✅ No cross-day exits
- ✅ All exits before 16:00
- ✅ Feature distributions reasonable

### Phase 2 Complete When:
- ✅ Entry timestamp > signal timestamp
- ✅ Entry prices from 1m bars
- ✅ Execution delay averages 1 minute

### Phase 3 Complete When:
- ✅ Trades exit when stop/target hit
- ✅ Exit reasons tracked correctly
- ✅ Stop hit rate < 60%

### Phase 4 Complete When:
- ✅ All required fields in trades.csv
- ✅ Net P&L = Gross P&L - Fees - Spread
- ✅ Trade report generates successfully

---

## Expected Performance Changes

### Current System (1m, broken):
- Bars per day: ~390
- Signals per day: Unknown (leakage)
- Win rate: Invalid (leakage)

### After Fix (10m, proper):
- Bars per day: ~39 (10x reduction)
- Signals per day: 5-15 (estimated)
- Win rate: 55-65% (with stops/targets)
- Avg R: 0.5-1.0R
- Trades per month: 100-300

---

## Files to Modify

### Primary Changes
1. `scripts/build_intraday_features_rolling.py` - Add 10m resampling
2. `scripts/rolling_train_and_backtest.py` - Two-stage execution + stops

### New Files
3. `scripts/validate_10m_features.py` - Validation script
4. `scripts/load_execution_prices.py` - 1m price loader
5. `scripts/generate_trade_report.py` - Enhanced reporting

---

## Next Steps

### Immediate (Today)
1. ✅ Review this analysis report
2. ⏳ Approve design decisions
3. ⏳ Begin Phase 1 implementation

### This Week
4. ⏳ Complete Phase 1 (10m data)
5. ⏳ Complete Phase 2 (execution delay)
6. ⏳ Begin Phase 3 (stops/targets)

### Next Week
7. ⏳ Complete Phase 3
8. ⏳ Complete Phase 4 (reporting)
9. ⏳ Full system validation
10. ⏳ Production deployment

---

## Documentation Delivered

1. **SYSTEM_ANALYSIS_DEC9.md** - Detailed technical analysis
2. **IMPLEMENTATION_PLAN_DEC9.md** - Step-by-step implementation guide
3. **ANALYSIS_REPORT_DEC9.md** - This executive summary

---

## Questions for Review

1. **Approve 10m resampling approach?** (Phase 1)
2. **Approve signal-to-execution delay architecture?** (Phase 2)
3. **Approve ATR-based stops with 2R targets?** (Phase 3)
4. **Approve 4-hour max hold time?** (Phase 3)
5. **Any additional fields needed in trades output?** (Phase 4)

---

**Report Status**: Complete
**Date**: December 9, 2025, 10:04 SGT
**Analyst**: System Analysis
**Recommendation**: Proceed with Phase 1 implementation after design approval
