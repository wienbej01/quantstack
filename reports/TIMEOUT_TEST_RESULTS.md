# Timeout Test Results
**Date:** December 5, 2025  
**Test:** Disabled early_cut and dead_trade timeouts

---

## Hypothesis
**Original:** 94% of trades exit at 20-minute timeout, preventing trades from reaching stops/targets.  
**Expected:** Removing timeout should allow trades to develop, improving win rate to 30-40%.

---

## Results

### With Timeout (Original)
- **Trades:** 343 completed
- **Win Rate:** 0.3% (1 win)
- **Avg PnL:** -$0.70
- **Avg Duration:** 23.8 minutes
- **Duration Pattern:** 94% exit at exactly 20 minutes

### Without Timeout (Test)
- **Trades:** 84 completed
- **Win Rate:** 0.0% (0 wins)
- **Avg PnL:** -$0.70
- **Avg Duration:** 169.3 minutes
- **Duration Pattern:** 88% exit at 10-20 minutes, 12% > 60 minutes

---

## Key Findings

### 1. Timeout Was NOT the Root Cause
- Removing timeout did NOT improve win rate
- Still 0% wins despite longer hold times
- PnL per trade unchanged (-$0.70)

### 2. New Exit Pattern Emerged
- **74 trades (88%)** exit at 10-20 minutes
- **10 trades (12%)** run > 60 minutes
- Average duration increased from 24 min to 169 min
- But NO improvement in profitability

### 3. Fewer Total Trades
- Original: 343 trades over 22 days
- No-timeout: 84 trades over same period
- **75% reduction in trade count**
- Suggests different order generation or filtering

---

## What's Actually Happening?

### Theory 1: Stops Hit Immediately (Most Likely)
- Trades still lose -$0.70 on average
- Exit at 10-20 minutes = stop loss triggered
- Stop distance ($0.108) is too tight for entry quality
- **Adverse selection:** Entering at worst possible time

### Theory 2: Commission Dominates
- $0.70 per trade = 2 × $0.35 commission
- On $18 stocks, need 3.9% move to break even
- Stop at $0.108 = only 0.6% room
- **Commission > Edge**

### Theory 3: Direction Prediction Fails
- ML models have high AUC in training
- But predictions don't work in live execution
- Possible overfitting or data leakage
- **Model ≠ Reality**

---

## Next Diagnostic Steps

### Priority 1: Analyze Exit Reasons (30 min)
Need to add exit reason tracking to backtest:
- Stop hit
- Target hit  
- Timeout
- End of day

**Action:** Modify backtest to record exit_reason in trades DataFrame

### Priority 2: Check Actual Stop Hits (30 min)
Compare entry price vs exit price vs stop price:
```python
for trade in trades:
    stop_distance = trade['risk_distance']
    actual_move = abs(trade['exit_price'] - trade['entry_price'])
    print(f"Stop: ${stop_distance:.3f} | Move: ${actual_move:.3f}")
```

### Priority 3: Test 3x Wider Stops (30 min)
```json
{
  "risk": {
    "stop_atr_multiple": 3.0,  // Was 1.0
    "tp_r_multiple": 2.0
  }
}
```

### Priority 4: Single Symbol Deep Dive (1 hour)
- Filter to just AES (most traded symbol)
- Plot every entry/exit on price chart
- Visualize stop/target levels
- Understand failure mode visually

---

## Revised Hypothesis

**The problem is NOT timeouts.**

**The problem is likely:**
1. **Stops too tight** (1.0 ATR = $0.108 on $18 stock = 0.6%)
2. **Adverse entry timing** (entering right before reversal)
3. **Commission too high** ($0.70 on $18 stock = 3.9% breakeven)

**Combined effect:** Every trade hits stop immediately, losing commission + small adverse move.

---

## Recommended Path Forward

### Option A: Widen Stops (RECOMMENDED)
Test stop_atr_multiple: [2.0, 3.0, 5.0]
- Should reduce stop-hit frequency
- Allow trades more room to develop
- May improve win rate to 20-30%

### Option B: Filter Entry Quality
Add entry filters:
- Require price > VWAP for longs
- Require volume > 2x average
- Avoid first/last 30 minutes
- May reduce adverse selection

### Option C: Reduce Commission Impact
- Increase position size to 10 shares
- Commission becomes 0.39% instead of 3.9%
- But increases risk per trade

### Option D: Pivot Strategy
- Use ML for filtering only, not timing
- Enter on technical signals (VWAP cross, breakout)
- Simpler risk management
- Different time horizon (4-hour holds)

---

## Timeline

**Phase 1: Diagnostics (2 hours)**
1. Add exit reason tracking
2. Analyze stop hits vs timeouts
3. Single symbol visualization

**Phase 2: Test Wider Stops (2 hours)**
1. Run 3x stop width test
2. Compare win rates and Sharpe
3. Find optimal stop width

**Phase 3: Decision Point (End of Day)**
- If wider stops work → optimize and sweep
- If wider stops fail → pivot to Option B or D
- If nothing works → fundamental strategy flaw

---

## Confidence Levels

**Before timeout test:** 75% (thought timeout was killing trades)  
**After timeout test:** 40% (timeout wasn't the issue)

**Current best guess:**
- 60% chance stops are too tight
- 30% chance adverse entry timing
- 10% chance fundamental strategy flaw

**Next test will determine path forward.**
