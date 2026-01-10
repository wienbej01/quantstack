# Model Inconsistency Analysis - December 12, 2025

## Executive Summary

The current ML system is **NOT consistently profitable**. While it shows +$13k total PnL, this masks extreme volatility:
- Equity swung from $10k → $166k → $23k
- Only 54% of months profitable
- 2 symbols account for 500%+ of all profits
- This is **curve fitting**, not prediction

## The Evidence

### Monthly Performance
| Metric | Value |
|--------|-------|
| Profitable months | 13/24 (54%) |
| Best month | Aug 2023: +$66k |
| Worst month | Nov 2024: -$28k |
| Monthly PnL std | $18,000 |

### Symbol Concentration (CRITICAL)
| Symbol | PnL | % of Total |
|--------|-----|------------|
| AMSC | +$37,254 | 280% |
| DRVN | +$29,409 | 221% |
| SMCI | -$39,606 | -298% |
| **Top 2** | +$66,663 | **502%** |

**The entire system's profit comes from 2 stocks.**

### Time-of-Day Performance
| Hour | PnL | Win Rate |
|------|-----|----------|
| 9-10 AM | +$66k | 85% |
| 12 PM | -$34k | 33% |
| 2 PM | -$50k | 38% |

**Morning trades work, afternoon trades lose.**

---

## Root Causes

### 1. ARBITRARY LABEL THRESHOLD

**Problem**: Using fixed 1.5% move as label threshold.

```
Label rates by month:
- 2023-08: 1.35% long rate (high volatility)
- 2024-06: 0.32% long rate (low volatility - 4x less!)
```

**Impact**: 
- In low-vol months, almost nothing gets labeled
- Model learns different patterns in different regimes
- Threshold should be RELATIVE to volatility (e.g., 1.5x ATR)

**Fix**: Use ATR-normalized labels
```python
# Instead of:
label_long = forward_return > 0.015  # Fixed 1.5%

# Use:
label_long = forward_return > (atr * 1.5)  # Relative to volatility
```

### 2. RAW PRICE FEATURES (Feature Drift)

**Problem**: Features include raw prices that drift over time.

```
Feature drift detected:
- prev_session_close: $80 → $160 (doubled!)
- vwap_session: $80 → $160
- first_open: $80 → $160
```

**Impact**:
- Model trained on $80 stocks doesn't work on $160 stocks
- Tree splits become meaningless as prices drift
- Features are not stationary

**Fix**: Normalize all features
```python
# Instead of:
features['vwap_session'] = vwap  # Raw price

# Use:
features['price_vs_vwap'] = (close - vwap) / vwap  # Relative
features['price_vs_open'] = (close - open) / open  # Relative
```

### 3. NO REGIME DETECTION

**Problem**: Model trained on 6 months of mixed regimes.

```
Training window includes:
- Bull markets
- Bear markets  
- High volatility
- Low volatility
- Trending days
- Mean-reverting days
```

**Impact**:
- Model averages across regimes
- Learns conflicting patterns
- Fails when regime changes

**Fix**: Add regime features or filter
```python
# Option 1: Add regime features
features['vix_level'] = vix  # Market volatility regime
features['trend_strength'] = adx  # Trending vs ranging
features['market_return_5d'] = spy_return  # Bull/bear

# Option 2: Train separate models per regime
if vix > 20:
    model = high_vol_model
else:
    model = low_vol_model
```

### 4. OVERFITTING TO SPECIFIC STOCKS

**Problem**: Aug 2023 profits came from ONE stock.

```
Aug 2023 breakdown:
- Total: 248 trades, +$66k
- AMSC alone: 205 trades, +$37k (83% of trades!)
```

**Impact**:
- Model learned AMSC-specific patterns
- When AMSC stopped trending, model failed
- Not generalizable

**Fix**: Diversification constraints
```python
# Limit trades per symbol per day
max_trades_per_symbol = 3

# Limit exposure per symbol
max_symbol_exposure = 0.10  # 10% of portfolio

# Require minimum symbol diversity
min_symbols_per_day = 5
```

### 5. TIME-OF-DAY IGNORED

**Problem**: Model treats all hours equally.

```
Performance by hour:
- 9-10 AM: +$66k (85% win rate)
- 2 PM: -$50k (38% win rate)
```

**Impact**:
- Morning patterns don't work in afternoon
- Liquidity, volatility differ by time
- Model averages across times

**Fix**: Time-aware features or filtering
```python
# Option 1: Add time features
features['hour'] = timestamp.hour
features['minutes_from_open'] = (timestamp - market_open).minutes
features['is_first_hour'] = hour < 10
features['is_last_hour'] = hour >= 15

# Option 2: Only trade profitable hours
if hour < 11:  # Morning only
    execute_trade()
```

### 6. VALIDATION PERIOD TOO SHORT

**Problem**: 1-month validation can't detect overfitting.

```
Current setup:
- Train: 6 months
- Validation: 1 month (too short!)
- OOS: 1 month
```

**Impact**:
- Overfitting not detected
- Model selection based on noise
- Poor generalization

**Fix**: Longer validation, walk-forward
```python
# Better setup:
train_months = 6
validation_months = 2  # Longer validation
oos_months = 1

# Or use walk-forward with multiple folds
for fold in range(5):
    train on months [0:6]
    validate on months [6:8]
    test on months [8:9]
    # Rotate forward
```

---

## Recommended Fixes (Priority Order)

### HIGH PRIORITY

1. **Normalize Labels by Volatility**
   - Use `forward_return > atr * 1.5` instead of fixed 1.5%
   - Makes labels consistent across volatility regimes

2. **Remove/Normalize Raw Price Features**
   - Replace `vwap_session` with `(close - vwap) / vwap`
   - Replace `prev_session_close` with `gap_pct`
   - All features should be ratios or z-scores

3. **Add Time-of-Day Filter**
   - Only trade 9:30-11:00 AM (profitable hours)
   - Or add hour as a feature

### MEDIUM PRIORITY

4. **Add Regime Features**
   - VIX level (or realized volatility)
   - Market trend (SPY 5-day return)
   - Sector momentum

5. **Diversification Constraints**
   - Max 3 trades per symbol per day
   - Max 10% exposure per symbol
   - Require 5+ symbols per day

6. **Longer Validation Period**
   - Use 2-3 months validation
   - Or use cross-validation

### LOWER PRIORITY

7. **Separate Models by Regime**
   - High-vol model vs low-vol model
   - Trending model vs mean-reversion model

8. **Feature Selection**
   - Remove features with high drift
   - Use only stable, normalized features

---

## Expected Impact

| Fix | Expected Improvement |
|-----|---------------------|
| Normalize labels | +20% consistency |
| Remove price drift | +15% consistency |
| Time filter | +30% win rate (fewer trades) |
| Diversification | -50% variance |
| Regime features | +10% accuracy |

**Combined**: Should achieve 65%+ profitable months (vs 54% now)

---

## Implementation Plan

### Phase 1: Quick Wins (1-2 days)
1. Add time-of-day filter (morning only)
2. Add diversification limits
3. Test impact

### Phase 2: Feature Engineering (3-5 days)
1. Normalize all price features
2. Add ATR-relative labels
3. Rebuild features
4. Retrain and test

### Phase 3: Regime Awareness (1 week)
1. Add VIX/volatility features
2. Add market trend features
3. Test regime-specific models

---

## Conclusion

The current model is **not consistently predictive**. It's curve-fitting to specific stocks (AMSC) and time periods (Aug 2023). The fixes above address the root causes:

1. **Labels**: Make relative to volatility
2. **Features**: Normalize to remove drift
3. **Time**: Filter to profitable hours
4. **Diversity**: Prevent concentration
5. **Regime**: Account for market conditions

Without these fixes, the system will continue to have wild swings between profit and loss.
