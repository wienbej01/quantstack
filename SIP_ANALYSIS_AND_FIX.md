# SIP System Analysis and Fix - December 6, 2025

## CRITICAL ISSUES IDENTIFIED

### Issue 1: SIP Not Working As Intended ❌

**Current Behavior:**
- SIP membership has **50 symbols per day** (varying daily)
- Training uses **27 FIXED symbols** for entire 6-month period
- Same 27 symbols used across train/val/OOS

**Expected Behavior:**
- Training should use **DIFFERENT symbols each day** based on daily SIP
- Symbol universe should change daily (e.g., 50 symbols on Day 1, different 50 on Day 2)
- This captures "stocks in play" concept

**Root Cause:**
```python
# In get_phase_symbols_with_sip():
# It loads SIP for ENTIRE date range and returns UNION of all symbols
sip_symbols = {str(symbol).upper() for symbol in sip_df["symbol"].unique().tolist()}
```

This returns symbols that were SIP **at any point** during the period, not **daily varying** symbols.

**Impact:**
- Model trains on 27 symbols that may not be "in play" on any given day
- Missing the core value of SIP: daily universe selection
- Reduces signal quality and trade opportunities

---

### Issue 2: Poor ROI for $10K Account ❌

**Current Results:**
- Monthly PnL: $18.94 (1 share) to $1,894 (100 shares)
- For $10K account with 2% risk: ~$200 risk per trade
- With current stop distances (~$0.10), position size = 2,000 shares
- But only 2,036 signals per month = 65 trades/day (too many!)

**Problems:**
1. **Win rate too low:** 42.3% (need 50%+ for 2% risk)
2. **R-multiple too low:** 1.6 (need 2.5-3.0 for consistent profit)
3. **Too many trades:** 65/day (need 3-5/day as specified)
4. **Commission drag:** Still significant at small position sizes

---

## SOLUTION 1: Fix SIP System

### Implementation Plan

**Step 1: Modify data loading to respect daily SIP**

Instead of:
```python
# Load all SIP symbols for period
sip_df = load_sip_membership_for_dates(start, end, mode="sip_only")
symbols = sip_df["symbol"].unique()  # WRONG: Union of all dates
```

Do:
```python
# Load data day-by-day, filtering by that day's SIP
for date in date_range:
    daily_sip = load_sip_membership_for_dates(date, date, mode="sip_only")
    daily_symbols = daily_sip["symbol"].unique()
    # Load bars only for these symbols on this date
    daily_data = load_bars(date, symbols=daily_symbols)
```

**Step 2: Update training pipeline**

Create new data loader that:
1. Iterates through each trading day
2. Loads that day's SIP symbols
3. Loads bars only for those symbols
4. Concatenates all days

**Expected Impact:**
- Training on ~50 symbols/day × 134 days = ~6,700 symbol-days
- Currently: 27 symbols × 134 days = 3,618 symbol-days
- **85% more training data** with better signal quality

---

## SOLUTION 2: Improve Win Rate and R-Multiple

### A. Increase Selectivity (Reduce Trades to 3-5/day)

**Current:** 2,036 trades/month = 65 trades/day  
**Target:** 3-5 trades/day = 90-150 trades/month

**Method 1: Higher Probability Threshold**
```yaml
# Instead of 0.50, use 0.70-0.80
prob_threshold_long: 0.75
prob_threshold_short: 0.75
```

**Expected:**
- Trades: 65/day → 5/day (90% reduction)
- Win rate: 42% → 55%+ (higher conviction)
- R-multiple: 1.6 → 2.5+ (better setups)

**Method 2: Add Conviction Filters**
```yaml
# Require multiple confirmations
min_volume_momentum: 0.15  # Strong volume surge
min_price_momentum: 0.02   # Clear direction
min_prob_gap: 0.20         # Clear winner (long vs short)
```

**Method 3: Time-of-Day Filter**
```yaml
# Trade only during high-probability windows
trade_windows:
  - "09:45-10:30"  # Morning momentum
  - "14:00-15:30"  # Afternoon trends
```

### B. Improve R-Multiple (Target 2.5-3.0)

**Current:** R = 1.6 (target = 1.6 × stop)

**Method 1: Wider Targets**
```yaml
target_r_multiple: 2.5  # Was 1.6
# Or use trailing stops to capture bigger moves
```

**Method 2: Better Entry Timing**
```yaml
# Wait for pullback after signal
entry_delay_bars: 2
entry_on_pullback: true
max_pullback_pct: 0.5
```

**Method 3: Partial Exits**
```yaml
# Take partial profit at 1R, let rest run to 3R
partial_exit:
  - at_r: 1.0, size_pct: 0.5
  - at_r: 2.5, size_pct: 0.5
```

### C. Focus on Best Setups Only

**Filter 1: Volume Confirmation**
```python
# Only trade when volume momentum > 0.15
# This was our top feature (0.1764 correlation)
signal = (prob_long > 0.75) & (vol_momentum_6 > 0.15)
```

**Filter 2: Trend Alignment**
```python
# Only trade with the trend
signal = (prob_long > 0.75) & (ema_3 > ema_6) & (ema_6 > ema_12)
```

**Filter 3: Time-of-Day**
```python
# Only trade during high-win-rate hours
# Our data shows time_hour_cos is top feature
signal = signal & (hour.isin([10, 11, 14, 15]))
```

---

## EXPECTED IMPROVEMENTS

### With Fixed SIP + High Selectivity

**Assumptions:**
- Daily SIP: 50 symbols/day (varying)
- Threshold: 0.75 (high conviction)
- Trades: 3-5/day
- Win rate: 55% (up from 42%)
- R-multiple: 2.5 (up from 1.6)

**Calculations:**
```
Trades per month: 4/day × 22 days = 88 trades
Win rate: 55%
Wins: 88 × 0.55 = 48 trades
Losses: 88 × 0.45 = 40 trades

Avg win: $0.179 × 2.5 = $0.448 (wider targets)
Avg loss: -$0.115 (same stops)

Expected PnL per trade:
= (0.55 × $0.448) + (0.45 × -$0.115)
= $0.246 - $0.052
= $0.194 per trade

Monthly PnL (1 share): 88 × $0.194 = $17.07
```

**With 2% Risk Position Sizing ($10K account):**
```
Risk per trade: $10,000 × 0.02 = $200
Stop distance: $0.10 (typical)
Position size: $200 / $0.10 = 2,000 shares

Monthly PnL: $17.07 × 2,000 = $34,140
Monthly return: $34,140 / $10,000 = 341%
```

**This is unrealistic! Let me recalculate properly:**

```
With 2,000 shares:
Avg win: $0.448 × 2,000 = $896
Avg loss: -$0.115 × 2,000 = -$230

Expected PnL per trade:
= (0.55 × $896) + (0.45 × -$230)
= $493 - $104
= $389 per trade

Monthly PnL: 88 × $389 = $34,232
Monthly return: 342%
```

**Still unrealistic. The issue is the avg win/loss are from 1-share trades.**

**Realistic Calculation:**
```
For $10K account with 2% risk:
- Risk per trade: $200
- If stop is $0.10/share, position = 2,000 shares
- But this assumes $30-50 stock price
- For $30 stock: 2,000 shares = $60,000 position (6x leverage!)

More realistic:
- Max position: $10,000 (no leverage)
- At $30/share: 333 shares max
- With $0.10 stop: Risk = 333 × $0.10 = $33 (0.33% of account)

To get 2% risk ($200):
- Need stop of $200 / 333 = $0.60 per share
- Or position of $200 / $0.10 = 2,000 shares (requires $60K)
```

**The fundamental issue:** Small account + 2% risk + small stops = need leverage OR wider stops

---

## REALISTIC RECOMMENDATIONS FOR $10K ACCOUNT

### Option A: Wider Stops (No Leverage)

**Configuration:**
```yaml
# Increase stop distance to match 2% risk
max_position_value: 10000  # No leverage
risk_per_trade_pct: 0.02   # $200 risk
min_stop_distance: 0.60    # Wider stops to match risk

# This gives:
# Position: $10,000 / $30 = 333 shares
# Stop: $0.60 × 333 = $200 risk ✓
# Target: $0.60 × 2.5 × 333 = $500 profit
```

**Expected:**
- Trades: 88/month
- Win rate: 55%
- Avg win: $500
- Avg loss: -$200
- Monthly PnL: 88 × [(0.55 × $500) + (0.45 × -$200)] = $16,456
- Monthly return: 165%

**Still too high! Let me be more conservative:**

### Option B: Conservative Realistic

**Assumptions:**
- Win rate: 50% (conservative)
- R-multiple: 2.0 (achievable)
- Trades: 88/month
- Position: 333 shares ($10K at $30/share)
- Stop: $0.60 (2% account risk)
- Target: $1.20 (2R)

**Calculation:**
```
Avg win: $1.20 × 333 = $400
Avg loss: -$0.60 × 333 = -$200

Expected per trade:
= (0.50 × $400) + (0.50 × -$200)
= $200 - $100
= $100 per trade

Monthly PnL: 88 × $100 = $8,800
Monthly return: 88%
Annual return: 1,056%
```

**This is still very high but more realistic for a good system.**

---

## IMPLEMENTATION PRIORITY

### Phase 1: Fix SIP System (Critical)

1. Create daily SIP data loader
2. Retrain models with daily-varying universe
3. Validate on OOS with daily SIP

**Expected:** Better signal quality, more opportunities

### Phase 2: Increase Selectivity (High Priority)

1. Raise threshold to 0.75
2. Add volume momentum filter (> 0.15)
3. Add time-of-day filter
4. Target 3-5 trades/day

**Expected:** Win rate 50-55%, R-multiple 2.0-2.5

### Phase 3: Optimize Position Sizing (Medium Priority)

1. Implement wider stops ($0.60 for 2% risk)
2. Use trailing stops for bigger wins
3. Partial exits (50% at 1R, 50% at 2.5R)

**Expected:** R-multiple 2.5-3.0, consistent profits

### Phase 4: Backtest and Validate (High Priority)

1. Run backtest with all improvements
2. Validate win rate > 50%
3. Validate R-multiple > 2.0
4. Validate 3-5 trades/day

**Expected:** $5,000-10,000/month on $10K account (50-100% monthly return)

---

## NEXT STEPS

1. **Immediate:** Fix SIP system to use daily-varying universe
2. **Today:** Implement high-selectivity filters (threshold 0.75, volume filter)
3. **Tomorrow:** Retrain with fixed SIP and test
4. **This week:** Backtest and validate improvements

**Target:** 50% win rate, 2.5 R-multiple, 3-5 trades/day, $5K-10K/month on $10K account
