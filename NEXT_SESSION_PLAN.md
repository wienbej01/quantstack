# Next Session Plan - Position Sizing Fix

**Date**: December 13, 2025  
**Estimated Time**: 2-3 hours  
**Priority**: HIGH - Blocking production deployment

## Situation Summary

✅ **Model rebuilt successfully** - 0.767 AUC (+0.177 improvement)  
⚠️ **Position sizing bug** - Unrealistic PnL values preventing deployment  
🎯 **Goal** - Fix position sizing for production readiness

## Issue Details

**Problem**: Position sizing calculation errors  
**Symptoms**: 
- Share counts: 100 to 9,999,889,755 (should be 100-10,000)
- PnL values: $64+ quintillion (should be -$1000 to +$1000)
- 22,476 extreme trades (59.6% of total)

**Location**: `scripts/rolling_train_fixed.py` - position sizing logic

## Action Plan

### Step 1: Debug Position Sizing (60 minutes)
```bash
# Create debug script to isolate the issue
python scripts/debug_position_sizing.py

# Check these calculation areas:
# - Risk per trade = equity * risk_fraction
# - Stop distance calculation
# - Shares = risk / stop_distance
# - Entry price validation
```

### Step 2: Implement Fix (60 minutes)
```bash
# Fix the calculation logic
# Add position size caps (max 10,000 shares)
# Add sanity checks for extreme values
# Validate entry prices are reasonable

# Test fix on small dataset
python scripts/test_position_sizing_fix.py
```

### Step 3: Validate System (30 minutes)
```bash
# Run full validation
python scripts/validate_fixed_features.py
python scripts/monitor_enhanced_pipeline.py

# Check metrics are realistic:
# - Position sizes: 100-10,000 shares
# - PnL per trade: -$1000 to +$1000
# - Win rate >50% on all trades
```

### Step 4: Generate Final Report (30 minutes)
```bash
# Generate comprehensive performance report
python scripts/generate_trade_report.py

# Review final metrics
cat run/rolling_results_fixed/trades.csv
```

## Expected Outcomes

### Before Fix
- AUC: 0.767 ✅
- Win rate: 72.1% (filtered trades only)
- Position sizes: 100 to 9.9B shares ❌
- PnL: Unrealistic values ❌

### After Fix
- AUC: 0.767 ✅ (unchanged)
- Win rate: >50% (all trades) ✅
- Position sizes: 100-10,000 shares ✅
- PnL: -$1000 to +$1000 per trade ✅

## Key Files to Work With

### Debug/Fix
- `scripts/rolling_train_fixed.py` - Contains position sizing bug
- `scripts/debug_position_sizing.py` - Create this to isolate issue
- `scripts/test_position_sizing_fix.py` - Create this to test fix

### Validation
- `scripts/validate_fixed_features.py` - Data quality checks
- `scripts/monitor_enhanced_pipeline.py` - Performance monitoring
- `run/rolling_results_fixed/trades.csv` - Output to validate

### Reference
- `ROOT_CAUSE_ANALYSIS_DEC12.md` - Complete technical analysis
- `SYSTEM_STATUS_REPORT_DEC13.md` - Current status
- `PROJECT_STATUS.md` - Project overview

## Success Criteria

- [ ] Position sizes in reasonable range (100-10,000 shares)
- [ ] PnL values realistic (-$1000 to +$1000 per trade)
- [ ] Win rate >50% on all trades (not just filtered)
- [ ] No extreme trades (>$1000 PnL)
- [ ] System validation passes all checks

## Confidence Level

**HIGH** - This is an isolated implementation bug in position sizing calculation. The model quality is proven excellent (0.767 AUC), and all architectural issues have been resolved. The fix should be straightforward once the calculation error is identified.

## Backup Plan

If position sizing fix takes longer than expected:
1. Implement position size caps as temporary fix
2. Filter extreme trades for analysis
3. Focus on model performance validation
4. Schedule follow-up session for complete fix

---
**Ready to start**: Position sizing debug and fix  
**Expected completion**: 2-3 hours  
**Next milestone**: Production-ready ML trading system
