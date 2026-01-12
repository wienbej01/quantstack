# Pattern Discovery Fix: Positive Conditions Only

## Problem Identified

The initial 6-month discovery found 30 patterns, but **27 of them were negative conditions** with no economic rationale:

```
❌ "is_first_hour_bin == False AND is_power_hour_bin == False"
   → "Not first hour AND not power hour" = 80% of the day
   → Not actionable, trivially true, no economic rationale

❌ "rel_underperform_extreme_bin == False AND is_power_hour_bin == False"
   → "Stock NOT underperforming AND NOT power hour"
   → Negative conditions don't provide entry signals
```

**Only 3 patterns had positive conditions with economic rationale:**
```
✅ "ret_60m_bin == 4.0 AND is_first_hour_bin == True"
   → Strong momentum in first hour continues

✅ "ret_60m_bin == 4.0 AND session_range_pct_bin == 4"
   → Strong momentum at session high = breakout

✅ "session_range_pct_bin == 1 AND is_first_hour_bin == False"
   → Low in session range = continuation down
```

## Root Cause

1. **Event features are rare** - `rel_underperform_extreme == True` occurs in ~5% of bars
2. **Negative conditions are common** - `rel_underperform_extreme == False` occurs in ~95% of bars
3. **Scanner optimizes t-stat** - More samples → higher t-stat → negative conditions dominate
4. **Statistical ≠ Economic significance** - High t-stat doesn't mean tradeable

## Solution Implemented

### 1. Filter Candidate Rules to Positive Conditions Only

**Binary features (True/False):**
- OLD: Test both `== True` and `== False`
- NEW: Only test `== True` (actual event occurrence)

**Binned features (0-4):**
- OLD: Test all bins (0, 1, 2, 3, 4)
- NEW: Only test extreme bins with economic meaning:
  - **Bin 0**: Extreme low (mean reversion opportunity)
  - **Bin 3**: High momentum (continuation)
  - **Bin 4**: Extreme high momentum (strong continuation)

### 2. Updated Pattern Generation Logic

```python
# For binary event features
if len(unique_vals) == 2 and True in unique_vals:
    mask = df[col] == True  # Only test positive condition
    rules.append((f"{col} == True", mask))

# For binned features
elif len(unique_vals) <= 5:
    for val in unique_vals:
        if val in [0, 3, 4]:  # Only extreme bins
            mask = df[col] == val
            rules.append((f"{col} == {val}", mask))
```

### 3. Enhanced LLM Analysis

Updated prompt to prioritize:
1. **Economic rationale** (WHY does this work?)
2. **Actionable signals** (not "NOT X" patterns)
3. **Microstructure explanation** (cross-asset, volume-price, range dynamics)

## Expected Results After Fix

### Patterns We Should Find

**Cross-Ticker Relative Strength:**
```
rel_underperform_extreme == True AND price_down_vol_weak == True
→ Stock underperforming SPY by >1% on weak volume = mean reversion
```

**Volume-Price Divergence:**
```
price_up_vol_weak == True AND at_session_high == True
→ Price at session high on weak volume = exhaustion reversal
```

**Session Range Events:**
```
new_session_high == True AND price_up_vol_strong == True
→ Breaking session high on strong volume = breakout continuation
```

**Momentum Continuation:**
```
ret_60m_bin == 4 AND rel_outperform_extreme == True
→ Strong momentum + outperforming SPY = continuation
```

### Patterns We Should NOT Find

```
❌ is_power_hour_bin == False
❌ rel_underperform_extreme_bin == False
❌ at_session_low_bin == False
❌ Any "NOT X" condition
```

## Run Command

```bash
cd ~/quantstack/sip_pattern_discovery

# Clear cache (pattern engine changed)
rm -f output_tstat/cached_*.parquet

# Re-run with positive conditions only
python run_long_short_discovery.py \
  --start-date 2024-07-01 \
  --end-date 2024-12-31 \
  --min-t-stat 3.0 \
  --min-expectancy 0.01 \
  --min-trades 30 \
  --horizons 30,60,90,180
```

## Expected Outcome

- **Fewer patterns** (10-20 instead of 30)
- **All actionable** (positive event conditions)
- **Clear economic rationale** (cross-ticker, volume-price, range dynamics)
- **Lower t-stats** (fewer samples per pattern, but more meaningful)
- **Higher expectancy** (focused on actual alpha sources)

## Key Insight

**Statistical significance ≠ Economic significance**

A pattern with t-stat 60 but no economic rationale (e.g., "NOT power hour") is worthless.
A pattern with t-stat 5 but clear microstructure edge (e.g., "underperforming SPY on weak volume") is valuable.

The fix ensures we only discover patterns with **actionable entry signals** and **clear economic rationale**.
