# Root Cause Analysis: 0.3% Win Rate
**Date:** December 5, 2025  
**Status:** ✅ Root cause identified

---

## The Problem
- **Win Rate:** 0.3% (1 win out of 343 trades)
- **Avg PnL:** -$0.70 per trade
- **Total Loss:** -$241.69 over 22 days

---

## Root Cause: Early Cut Timeout

### Key Finding
**94% of trades (322/343) exit at exactly 20 minutes** - this is NOT the stop loss, it's the **"early cut" timeout**.

### The Timeout Logic
From policy config:
```json
{
  "timeouts": {
    "early_cut_minutes": 20,
    "early_cut_min_r": 0.5,
    "dead_trade_minutes": 30,
    "dead_trade_max_r": 0.2,
    "max_hold_minutes": 60
  }
}
```

**Early Cut Rule:** If trade is < 0.5R profit after 20 minutes → EXIT

### Why This Kills Performance

**Actual Numbers:**
- Average stop distance: **$0.108**
- Average absolute move: **$0.104** 
- 0.5R threshold = **$0.054** profit needed

**The Math:**
- To avoid early cut, price must move **$0.054** in your favor within 20 minutes
- But average move is only **$0.104** total (in either direction)
- Most trades are still developing at 20 minutes
- Timeout forces exit before trade can work

---

## Evidence

### Duration Distribution
```
Trades < 10 min:    0
Trades 10-20 min:   0
Trades 20-30 min:   322  ← 94% exit at timeout
Trades > 30 min:    21
```

### Sample Trades (All Exit at 20 Minutes)
```
AES SHORT: Entry $17.75 → Exit $17.81 | Move: $0.05 | PnL: -$0.75 | 20 min
AES SHORT: Entry $18.24 → Exit $18.41 | Move: $0.16 | PnL: -$0.86 | 20 min
AES SHORT: Entry $18.46 → Exit $18.43 | Move: $0.04 | PnL: -$0.67 | 20 min
AES SHORT: Entry $18.70 → Exit $18.68 | Move: $0.03 | PnL: -$0.68 | 20 min
AES SHORT: Entry $18.90 → Exit $18.74 | Move: $0.16 | PnL: -$0.54 | 20 min
```

**Pattern:** Every trade exits at 20 minutes regardless of whether it's winning or losing.

### PnL Distribution
```
PnL < -$1.00:        9 trades
PnL -$1.00 to -$0.50: 311 trades  ← Clustered around -$0.70
PnL -$0.50 to $0.00:  22 trades
PnL $0.00 to $0.50:   1 trade
PnL > $0.50:          0 trades
```

**The -$0.70 cluster = commission + small adverse move before timeout**

---

## Why Stops Aren't Being Hit

### Stop Configuration
- Target: 1.0 ATR
- Actual: 0.69 ATR (from orders data)
- Average stop distance: $0.108

### Why Stops Don't Trigger
- Timeout at 20 minutes happens BEFORE stop is hit
- Average move ($0.104) is slightly less than stop distance ($0.108)
- Even when price moves against you, timeout exits first

---

## Secondary Issues

### 1. ATR Multiple Too Low
- **Configured:** 1.0 ATR
- **Actual:** 0.69 ATR
- **Reason:** Unknown (possible bug in risk calculation)

### 2. Commission Impact
- **Per trade:** $0.70 in commissions (2 × $0.35)
- **Break-even:** Need $0.70 move just to cover costs
- **With 0.5R threshold:** Need $0.054 + $0.70 = $0.75 total move

### 3. Direction Prediction
- ML models have strong AUC (0.88 Stage 1, 0.93 Stage 2)
- But in practice, trades move against entry immediately
- Possible adverse selection at entry timing

---

## The Fix

### Option 1: Remove Early Cut Timeout (RECOMMENDED)
```json
{
  "timeouts": {
    "early_cut_minutes": 999,  // Effectively disable
    "early_cut_min_r": 0.0,
    "dead_trade_minutes": 999,
    "dead_trade_max_r": 0.0,
    "max_hold_minutes": 60     // Keep max hold only
  }
}
```

**Expected Impact:**
- Let trades run full 60 minutes
- Allow stops and targets to work as designed
- Win rate should increase to 30-40% (normal for mean reversion)

### Option 2: Loosen Early Cut
```json
{
  "timeouts": {
    "early_cut_minutes": 45,   // Later timeout
    "early_cut_min_r": -0.5,   // Allow small losses
    "dead_trade_minutes": 999,
    "dead_trade_max_r": 0.0,
    "max_hold_minutes": 60
  }
}
```

### Option 3: Widen Stops + Remove Timeout
```json
{
  "risk": {
    "stop_atr_multiple": 2.0,  // Was 1.0
    "tp_r_multiple": 2.0
  },
  "timeouts": {
    "early_cut_minutes": 999,
    "max_hold_minutes": 60
  }
}
```

---

## Test Plan

### Phase 1: Disable Timeouts (30 minutes)
1. Update policy config to disable early_cut and dead_trade
2. Run single config backtest
3. Analyze trade durations and exit reasons

### Phase 2: Compare Results (1 hour)
1. Run 8-config test grid with timeout disabled
2. Compare win rates, Sharpe, trade counts
3. Analyze which trades now reach stops vs targets

### Phase 3: Optimize (2 hours)
1. If win rate improves, test stop width variations
2. Find optimal stop_atr_multiple (1.0, 1.5, 2.0, 3.0)
3. Test different max_hold_minutes (60, 90, 120)

---

## Confidence Level

**Before:** 15% (thought stops were too tight)  
**After:** 75% (timeout is killing trades)

**Reasoning:**
- Clear evidence: 94% exit at exactly 20 minutes
- Timeout threshold (0.5R = $0.054) is unrealistic for 20-minute window
- Removing timeout should immediately improve results
- ML models are strong, execution layer is broken

---

## Next Steps

1. **IMMEDIATE:** Create policy config with timeouts disabled
2. **TEST:** Run single backtest to validate hypothesis
3. **SWEEP:** Run 8-config grid if single test shows improvement
4. **OPTIMIZE:** Find optimal stop width and hold time
5. **VALIDATE:** Run full 576-config sweep if results are promising

**Timeline:** 4 hours to validation, 1 day to optimization

---

## Lessons Learned

1. **Always check exit reasons** - Don't assume losses = stop hits
2. **Timeouts can kill strategies** - Especially with tight thresholds
3. **Commission matters** - $0.70 per trade is significant on $18 stocks
4. **Duration analysis is critical** - Clustering at 20 min revealed the issue
5. **ML models ≠ Trading performance** - Strong AUC doesn't guarantee profits
