# Feature Set Evaluation - December 5, 2025

## Executive Summary

**Current features are TOO WEAK for 60-120 minute predictions.**

- **Best feature:** 0.051 correlation (day of week)
- **Best category:** VWAP (0.024 avg correlation)
- **Overall:** All features < 0.06 correlation

**For comparison:** Good ML features typically have 0.10-0.30 correlation with target.

---

## Current Feature Set (68 features)

### By Category

| Category | Count | Avg Correlation | Max Correlation | Assessment |
|----------|-------|-----------------|-----------------|------------|
| VWAP | 18 | 0.024 | 0.039 | ⚠️ Weak |
| Conviction | 21 | 0.015 | 0.026 | ⚠️ Weak |
| Time | 6 | 0.017 | 0.051 | ⚠️ Weak |
| Momentum | 7 | 0.013 | 0.022 | ❌ Very Weak |
| Volume | 7 | 0.013 | 0.016 | ❌ Very Weak |
| Returns | 5 | 0.013 | 0.020 | ❌ Very Weak |
| MA | 3 | 0.014 | 0.020 | ❌ Very Weak |
| Range | 1 | 0.003 | 0.003 | ❌ Useless |

### Top 10 Features

1. `f__time__dow_cos` (0.051) - Day of week
2. `f__vwap__z_30_20` (0.039) - VWAP z-score
3. `f__vwap__z_20_30` (0.035) - VWAP z-score
4. `f__vwap__z_5_30` (0.035) - VWAP z-score
5. `f__vwap__z_30_30` (0.035) - VWAP z-score
6. `f__vwap__z_10_30` (0.033) - VWAP z-score
7. `f__vwap__z_5_60` (0.032) - VWAP z-score
8. `f__vwap__z_20_20` (0.032) - VWAP z-score
9. `f__vwap__z_5_20` (0.031) - VWAP z-score
10. `f__conv__zscore_12` (0.025) - Conviction z-score

**Pattern:** VWAP features dominate, but still very weak.

---

## Problem Analysis

### 1. Prediction Horizon Too Long

**Current:** 60-120 minutes into future

**Issue:** 10-minute bar features can't predict 1-2 hours ahead
- Market microstructure changes too much
- News/events can occur
- Intraday trends reverse
- Too much noise

**Evidence:** Even best features < 0.06 correlation

### 2. Missing Critical Features

**Not included:**
- ❌ Multi-timeframe context (1m, 5m, 30m, 60m)
- ❌ Market regime (trending vs ranging)
- ❌ Relative strength vs SPY/sector
- ❌ Support/resistance levels
- ❌ Volume profile / VPOC
- ❌ Order flow imbalance
- ❌ Tape reading signals
- ❌ Opening range breakouts
- ❌ Previous day high/low
- ❌ Intraday pivot points

### 3. Feature Engineering Too Simple

**Current features:**
- Basic returns (1-12 bars)
- Simple moving averages
- ATR volatility
- VWAP distance

**Missing:**
- Adaptive indicators (based on volatility)
- Non-linear transformations
- Feature interactions
- Regime-conditional features
- Time-decay weighted features

### 4. Microstructure Disabled

```yaml
microstructure:
  enabled: false  # ← DISABLED
```

**This is critical for intraday trading!**

Microstructure includes:
- Bid-ask spread
- Order book imbalance
- Trade size distribution
- Tick direction
- Volume at price levels

---

## Recommendations

### Priority 1: Shorten Prediction Horizon

**Change from 60-120 minutes to 15-30 minutes**

```yaml
# configs/extensions/intraday_ml/targets_bigmove.yaml
horizons:
  - 15  # Changed from 30
  - 30  # Changed from 60
  - 45  # Changed from 120

big_move:
  forward_minutes: 30  # Changed from 60
  forward_minutes_alt: 45  # Changed from 120
```

**Rationale:**
- Shorter horizon = more predictable
- Better feature-target alignment
- Still enough time for 1.6R trades

### Priority 2: Add Multi-Timeframe Features

**Add to features_10m.yaml:**

```yaml
multi_timeframe:
  enabled: true
  timeframes:
    - 1m   # Microstructure
    - 5m   # Short-term momentum
    - 30m  # Intermediate trend
    - 60m  # Intraday trend
  features:
    - returns
    - volume_ratio
    - vwap_distance
    - atr
    - rsi
```

**Expected improvement:** +0.05 to +0.10 correlation

### Priority 3: Add Market Context

```yaml
market_context:
  enabled: true
  benchmark: SPY
  features:
    - relative_strength  # Stock vs SPY
    - beta_realized      # Rolling beta
    - correlation_5d     # Recent correlation
    - sector_momentum    # If sector data available
```

**Expected improvement:** +0.03 to +0.05 correlation

### Priority 4: Add Support/Resistance

```yaml
price_levels:
  enabled: true
  lookback_days: 5
  features:
    - distance_to_vwap
    - distance_to_prev_high
    - distance_to_prev_low
    - distance_to_open
    - opening_range_position
    - pivot_points
```

**Expected improvement:** +0.05 to +0.08 correlation

### Priority 5: Enable Microstructure

```yaml
microstructure:
  enabled: true  # ENABLE THIS
  features:
    - spread_bps
    - volume_imbalance
    - trade_intensity
    - tick_direction
```

**Expected improvement:** +0.03 to +0.05 correlation

### Priority 6: Add Feature Interactions

```yaml
feature_engineering:
  interactions:
    enabled: true
    pairs:
      - [vwap_distance, volume_ratio]
      - [returns_1, atr]
      - [rsi, volume_ratio]
  polynomial:
    enabled: true
    degree: 2
    features: [vwap_distance, returns_1, volume_ratio]
```

**Expected improvement:** +0.02 to +0.04 correlation

---

## Expected Impact

### Current State
```
Best feature: 0.051 correlation
Average top-10: 0.035 correlation
Model performance: Zero predictive power
```

### After Improvements
```
Best feature: 0.15-0.20 correlation (3-4x improvement)
Average top-10: 0.10-0.12 correlation
Model performance: Positive edge (5-10 pp above random)
```

---

## Implementation Priority

### Phase 1: Quick Wins (2-3 hours)

1. **Shorten horizon to 15-30 minutes**
   - Edit targets_bigmove.yaml
   - Retrain models
   - Test: Should see immediate improvement

2. **Enable microstructure**
   - Edit features_10m.yaml
   - Regenerate features
   - Retrain models

3. **Fix class_weights config**
   - Edit model configs
   - Retrain with proper balancing

**Expected:** 40-45% target rate (vs 34% current)

### Phase 2: Feature Engineering (1-2 days)

4. **Add multi-timeframe features**
   - Implement 1m, 5m, 30m, 60m context
   - Requires feature engineering code

5. **Add market context (SPY relative)**
   - Load SPY data
   - Calculate relative strength

6. **Add support/resistance levels**
   - Implement pivot points
   - Previous day high/low

**Expected:** 45-50% target rate

### Phase 3: Advanced (2-3 days)

7. **Feature interactions**
8. **Regime detection**
9. **Volume profile**

**Expected:** 50-55% target rate

---

## Alternative: Simpler Approach

If feature engineering is too complex, consider:

### Option A: Rule-Based System

**No ML, just rules:**
```python
# Entry conditions
if (
    price > vwap and
    volume > avg_volume * 1.5 and
    rsi < 70 and
    distance_to_resistance > 2 * atr
):
    enter_long()
```

**Advantages:**
- Interpretable
- Fast to implement
- No training needed
- Can work with weak features

### Option B: Ensemble of Simple Models

**Train separate models:**
1. VWAP reversion model (mean reversion)
2. Momentum breakout model (trend following)
3. Volume surge model (unusual activity)

**Combine predictions:**
- Each model specializes
- Ensemble reduces overfitting
- Better than one complex model

---

## Specific Feature Recommendations

### High-Value Features to Add

**1. Opening Range (First 30 minutes)**
```python
f__or__breakout_long   # Price > OR high
f__or__breakout_short  # Price < OR low
f__or__position        # Where in OR (0-1)
f__or__width_atr       # OR width in ATR units
```

**2. Previous Day Levels**
```python
f__prev__dist_to_high  # Distance to yesterday's high
f__prev__dist_to_low   # Distance to yesterday's low
f__prev__dist_to_close # Distance to yesterday's close
```

**3. Intraday Trend**
```python
f__trend__slope_30m    # 30-min price slope
f__trend__strength     # R-squared of trend
f__trend__duration     # Bars in current trend
```

**4. Volume Analysis**
```python
f__vol__surge_5m       # 5-min volume vs average
f__vol__acceleration   # Volume trend
f__vol__profile_poc    # Price at volume peak
```

**5. Relative Strength**
```python
f__rel__vs_spy_1h      # 1-hour return vs SPY
f__rel__vs_spy_1d      # 1-day return vs SPY
f__rel__beta_realized  # Recent beta
```

---

## Testing Plan

### Step 1: Baseline (Current)
- Features: 68 basic features
- Horizon: 60-120 minutes
- Result: 0.051 max correlation

### Step 2: Quick Fixes
- Horizon: 15-30 minutes
- Microstructure: Enabled
- Class weights: Fixed
- Expected: 0.08-0.10 max correlation

### Step 3: Enhanced Features
- Multi-timeframe: Added
- Market context: Added
- Support/resistance: Added
- Expected: 0.12-0.15 max correlation

### Step 4: Advanced
- Feature interactions
- Regime detection
- Expected: 0.15-0.20 max correlation

---

## Conclusion

**Current features are inadequate for 60-120 minute predictions.**

**Immediate actions:**
1. Shorten horizon to 15-30 minutes (biggest impact)
2. Enable microstructure features
3. Fix class_weights config
4. Retrain and test

**Medium-term:**
5. Add multi-timeframe context
6. Add market relative strength
7. Add support/resistance levels

**Expected improvement:** From 34% target rate to 45-50% target rate.

---

## Files to Modify

1. `configs/extensions/intraday_ml/targets_bigmove.yaml` - Shorten horizons
2. `configs/extensions/intraday_ml/features_10m.yaml` - Enable microstructure
3. `configs/extensions/intraday_ml/model_bigmove_stage1.yaml` - Fix class_weights
4. `configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml` - Fix class_weights

**Estimated time:** 2-3 hours for Phase 1, then test.
