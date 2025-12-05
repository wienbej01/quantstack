# System Audit Report - December 5, 2025

## Executive Summary
**CRITICAL ISSUES FOUND:** The backtest system has fundamental gaps in trading logic implementation.

---

## Issues Identified

### 1. ❌ Stop Loss NOT Implemented
**Location:** `qx-backtest/src/qx_backtest/`

**Problem:**
- `backtest.py` sets `order_obj.stop_loss` and `order_obj.take_profit` on Order objects
- But `Order` class has NO `stop_loss` or `take_profit` attributes
- Engine NEVER checks these values
- Positions run without stop protection

**Evidence:**
```python
# In backtest.py line 480:
order_obj.stop_loss = stop_loss_price  # ← Sets attribute that doesn't exist
order_obj.take_profit = take_profit_price  # ← Sets attribute that doesn't exist

# In order.py: Order class has NO stop_loss or take_profit fields
# In engine.py: NO code checks for stop_loss or take_profit
# In portfolio.py: NO position monitoring for stops/targets
```

**Impact:**
- All trades run to timeout or EOD close
- No stop loss protection
- No take profit exits
- Explains 0% win rate - trades never hit targets

---

### 2. ❌ R-Multiple Always Zero
**Location:** Trades DataFrame

**Problem:**
- `r_multiple` column always shows 0.0
- No calculation of actual R-multiple from entry/exit
- Cannot measure risk-adjusted performance

**Evidence:**
```
r_multiple    0.0  # Always zero in all trades
```

**Impact:**
- Cannot evaluate risk/reward
- Cannot compare to expected_r from signals
- Performance metrics meaningless

---

### 3. ❌ Stop Distance Not Recorded
**Location:** Fills/Trades output

**Problem:**
- `stop_dist_ps` always 0.0 in fills
- Risk parameters from orders not propagated to fills
- Cannot analyze if stops were appropriate

**Evidence:**
```
stop_dist_ps    0.0  # Always zero
```

**Impact:**
- Cannot diagnose stop placement issues
- Cannot validate risk management
- Cannot optimize stop width

---

### 4. ❌ Slippage Not Applied
**Location:** Fills DataFrame

**Problem:**
- `slippage_est` always 0.0
- DefaultFiller has slippage_bps=5 configured
- But slippage not recorded in fill output

**Evidence:**
```
slippage_est    0.0  # Always zero
fees            0.0  # Always zero
```

**Impact:**
- PnL calculations may be incorrect
- Backtest results overly optimistic
- Real trading will underperform

---

### 5. ❌ No Position Monitoring
**Location:** `qx-backtest/src/qx_backtest/engine.py`

**Problem:**
- Engine processes orders bar-by-bar
- But NEVER checks existing positions against stops/targets
- Positions only exit when new order submitted or EOD

**What's Missing:**
```python
# Should exist but doesn't:
def check_position_exits(self, bar_data):
    for symbol, position in self.positions.items():
        if position.stop_loss and bar_data['low'] <= position.stop_loss:
            # Exit at stop
        if position.take_profit and bar_data['high'] >= position.take_profit:
            # Exit at target
```

**Impact:**
- Stops and targets never trigger
- Positions run indefinitely
- Risk management completely broken

---

### 6. ⚠️ Timeout Logic Unclear
**Location:** Policy lifecycle management

**Problem:**
- Policy has timeout settings (early_cut, dead_trade, max_hold)
- But unclear how these are enforced
- May be policy-level, not engine-level

**Current Understanding:**
- Policy generates exit orders based on time
- But this requires policy to track open positions
- Not clear if this is working correctly

---

### 7. ⚠️ EOD Flat Works (Partially)
**Location:** `backtest.py` line 405

**What Works:**
```python
# Force flat at configured cutoff time
if position and ts_et.time() >= flat_time:
    # Submit market order to close
```

**Issue:**
- Only checks at 15:59:59
- Doesn't respect max_hold_minutes
- Doesn't check stops/targets during the day

---

## Root Cause Analysis

### Why 0% Win Rate
1. **No take profit exits** - Winners never close at target
2. **No stop loss exits** - Losers run until timeout/EOD
3. **Timeout kills trades** - Policy exits at 20 min regardless of PnL
4. **Commission dominates** - $0.70 per trade on $18 stocks = 3.9%

### Why All Trades Look Similar
- All exit via timeout or EOD close
- No variation in exit mechanism
- No risk management differentiation

### Why Metrics Are Wrong
- R-multiple not calculated
- Stop distance not tracked
- Slippage not applied
- Cannot measure actual performance

---

## What Needs to Be Fixed

### Priority 1: Implement Stop/Target Monitoring (CRITICAL)
**File:** `qx-backtest/src/qx_backtest/engine.py`

**Required Changes:**
1. Add `stop_loss` and `take_profit` to Order class
2. Transfer these to Position when order fills
3. Check positions against stops/targets every bar
4. Generate exit orders when triggered
5. Record exit_reason in fills

**Estimated Effort:** 4-6 hours

---

### Priority 2: Calculate R-Multiple (HIGH)
**File:** `extensions/intraday_ml/backtest.py`

**Required Changes:**
1. Track entry price and stop distance per position
2. Calculate R-multiple on exit: (exit_price - entry_price) / stop_distance
3. Add to trades DataFrame
4. Validate against expected_r from signals

**Estimated Effort:** 2 hours

---

### Priority 3: Record Risk Metrics (HIGH)
**File:** `qx-backtest/src/qx_backtest/fill.py`

**Required Changes:**
1. Add stop_dist_ps to Fill dataclass
2. Pass from Order to Fill
3. Record slippage_est from filler calculation
4. Add fees breakdown

**Estimated Effort:** 2 hours

---

### Priority 4: Add Exit Reason Tracking (MEDIUM)
**File:** `qx-backtest/src/qx_backtest/engine.py`

**Required Changes:**
1. Add exit_reason to Fill/Trade
2. Track: stop_hit, target_hit, timeout, eod_close, manual
3. Report in trade analysis

**Estimated Effort:** 1 hour

---

### Priority 5: Validate Slippage Application (MEDIUM)
**File:** `qx-backtest/src/qx_backtest/fill.py`

**Required Changes:**
1. Verify DefaultFiller applies slippage correctly
2. Record actual slippage in Fill
3. Include in PnL calculation

**Estimated Effort:** 1 hour

---

## Gradient of Certainty Issue

**Your observation:** "gradient reducing certainty for success over time"

**Possible causes:**
1. **No stops** - Losses compound as positions run
2. **No targets** - Winners turn into losers
3. **Time decay** - Longer hold = more commission impact
4. **Market mean reversion** - Initial move reverses

**Cannot validate without:**
- Exit reason tracking
- Time-series PnL analysis
- Stop/target implementation

---

## Max Holding Time = 240 Minutes

**Current State:**
- Policy has `max_hold_minutes` setting
- But unclear how enforced
- No evidence in fills data

**Required:**
1. Policy must track position open time
2. Generate exit order at 240 minutes
3. Record exit_reason = "max_hold_timeout"
4. Respect EOD close (15:59:59 ET)

**Validation needed:**
- Check if policy lifecycle logic works
- Verify timeout orders are generated
- Confirm they execute correctly

---

## Market-Based Stop/Target Levels

**Current State:**
- Orders have `stop_loss_pct` and `take_profit_pct`
- Calculated from ATR in policy
- But NEVER USED by engine

**Required:**
1. Stop must be ATR-based (currently 1.0 ATR)
2. Target must be R-multiple based (currently 2.0 R)
3. Minimum distance validation needed
4. Engine must monitor and execute

**Example:**
```
Entry: $18.00
ATR: $0.108
Stop: $18.00 - $0.108 = $17.892 (0.6% away)
Target: $18.00 + $0.216 = $18.216 (1.2% away)
```

**Issue:** 0.6% stop is too tight for market noise

---

## Recommendations

### Immediate Actions (Today)
1. **DO NOT run more backtests** - Results are invalid
2. **Fix stop/target monitoring** - Core functionality missing
3. **Add exit reason tracking** - Essential for diagnosis
4. **Validate slippage/commission** - Ensure costs are correct

### Short-term (This Week)
1. Implement Priority 1-3 fixes
2. Re-run single config test
3. Validate stops and targets trigger correctly
4. Analyze exit reasons distribution

### Long-term (Next Week)
1. Optimize stop width based on actual exits
2. Test different hold times
3. Validate gradient hypothesis with proper data
4. Full parameter sweep with working system

---

## Confidence Assessment

**Before audit:** 40% (thought stops were too tight)  
**After audit:** 5% (stops don't exist at all)

**System viability:** Cannot assess until core functionality implemented

**Time to working system:** 8-12 hours of development

---

## Bottom Line

**The backtest engine is fundamentally broken:**
- No stop loss monitoring
- No take profit monitoring  
- No position management
- No exit reason tracking
- No risk metrics calculation

**All previous analysis is invalid** because trades never hit stops or targets.

**Cannot proceed with optimization** until core trading logic is implemented.

**Estimated timeline:**
- Fix core issues: 8-12 hours
- Validate fixes: 2-4 hours
- Re-run analysis: 2-4 hours
- **Total: 12-20 hours to working system**

---

## Next Steps

1. **STOP all backtesting** - Results are meaningless
2. **Implement stop/target monitoring** - Priority 1
3. **Add exit reason tracking** - Priority 4
4. **Validate with single trade** - Manual verification
5. **Re-run test suite** - Ensure nothing breaks
6. **Then and only then** - Resume optimization

**This is a fundamental system issue, not a parameter tuning problem.**
