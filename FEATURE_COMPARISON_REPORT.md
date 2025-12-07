# Feature Set Comparison: 30 vs 209 Features

**Date**: 2025-12-06  
**Models**: v4_6months_ict (30 features) vs v4_6months_comprehensive (209 features)  
**Training Period**: Jan-Jun 2024 (6 months)  
**Test Period**: OOS data

---

## Executive Summary

**Winner: 30-Feature ICT Model**

The simpler 30-feature model significantly outperformed the comprehensive 209-feature model:
- **Win rate**: 55.2% vs 47.1% (-8.1 points)
- **Total P&L**: +358.49% vs -43.94% (-402.43 points)
- **Sharpe**: 0.19 vs -0.72 (-0.91 points)

**Key Finding**: More features ≠ better performance. The model suffered from overfitting despite strong validation AUC.

---

## Model Comparison

### Training Metrics

| Metric | 30 Features (ICT) | 209 Features (Comprehensive) | Difference |
|--------|-------------------|------------------------------|------------|
| LONG AUC | 0.93 | 0.94 | +0.01 |
| SHORT AUC | 0.90 | 0.91 | +0.01 |
| Training Time | ~5 min | ~15 min | +10 min |

**Observation**: Comprehensive model had slightly better validation AUC but this didn't translate to OOS performance.

### OOS Performance

| Metric | 30 Features (ICT) | 209 Features (Comprehensive) | Difference |
|--------|-------------------|------------------------------|------------|
| **Signals** | 712 | 694 | -18 (-2.5%) |
| **Win Rate** | 55.2% | 47.1% | -8.1 points |
| **Avg P&L** | +0.50% | -0.06% | -0.56 points |
| **Total P&L** | +358.49% | -43.94% | -402.43 points |
| **Sharpe** | 0.19 | -0.72 | -0.91 points |
| **Signals/Day** | 17.0 | 16.9 | -0.1 |

### Direction-Specific Performance

#### LONG Signals

| Metric | 30 Features | 209 Features | Difference |
|--------|-------------|--------------|------------|
| Trades | 375 | 225 | -150 (-40%) |
| Win Rate | 48.3% | 53.3% | +5.0 points |
| Avg P&L | +0.09% | -0.16% | -0.25 points |

**Observation**: Comprehensive model was more selective on LONG (fewer trades) with better win rate but worse P&L.

#### SHORT Signals

| Metric | 30 Features | 209 Features | Difference |
|--------|-------------|--------------|------------|
| Trades | 337 | 469 | +132 (+39%) |
| Win Rate | 62.9% | 44.1% | -18.8 points |
| Avg P&L | +0.97% | -0.02% | -0.99 points |

**Observation**: Comprehensive model generated more SHORT signals but with dramatically worse win rate (62.9% → 44.1%).

---

## Feature Set Breakdown

### 30-Feature ICT Model

**Categories**:
1. **Basic Price/Volume** (15 features): returns, volatility, volume ratios, time-of-day
2. **ICT Concepts** (8 features): fair value gaps, order blocks, liquidity grabs, break of structure, displacement
3. **Volume-Price Analysis** (7 features): buying/selling pressure, VWAP distance, price-volume divergence

**Top 5 Features** (by importance):
1. time_since_open (11.3%)
2. volatility_20 (10.5%)
3. returns_20 (8.3%)
4. volume_momentum (6.9%)
5. range_pct (5.8%)

### 209-Feature Comprehensive Model

**Categories**:
1. **Moving Averages** (40+ features): SMA, EMA across 8 timeframes, crossovers
2. **Momentum Indicators** (30+ features): RSI, MACD, Stochastic, ADX, Williams %R, CCI, MFI
3. **Volatility** (20+ features): ATR, Bollinger Bands across multiple timeframes
4. **Volume** (30+ features): Volume ratios, momentum, OBV across timeframes
5. **Feature Interactions** (20+ features): Ratios, products, differences
6. **Cross-Sectional** (10+ features): Ranks, percentiles
7. **Statistical** (15+ features): Skew, kurtosis, acceleration
8. **ICT/VPA** (15+ features): Same as 30-feature model
9. **Support/Resistance** (10+ features): Distance calculations
10. **Time-Based** (10+ features): Hour, minute, session indicators

---

## Root Cause Analysis

### Why Did 209 Features Underperform?

#### 1. **Overfitting** ✅
- **Evidence**: High validation AUC (0.94/0.91) but poor OOS performance (47.1% win rate)
- **Cause**: Too many features allowed model to memorize training patterns that didn't generalize
- **Impact**: -8.1 point win rate drop, -402 point P&L drop

#### 2. **Feature Redundancy** ✅
- **Evidence**: 40+ moving average features (SMA/EMA across 8 timeframes) are highly correlated
- **Cause**: Multiple features capturing same information (e.g., SMA_10, SMA_15, SMA_20 all measure short-term trend)
- **Impact**: Model confused by redundant signals, reduced signal clarity

#### 3. **Noise Amplification** ✅
- **Evidence**: SHORT model win rate collapsed from 62.9% → 44.1%
- **Cause**: Adding 179 features introduced more noise than signal
- **Impact**: Model learned spurious correlations that failed OOS

#### 4. **Curse of Dimensionality** ✅
- **Evidence**: 209 features with 543k training samples = 2,600 samples per feature
- **Cause**: Insufficient data density in high-dimensional space
- **Impact**: Model struggled to find robust patterns

#### 5. **Feature Interaction Complexity** ❌
- **Evidence**: Feature interactions (ratios, products) didn't improve performance
- **Cause**: LightGBM already captures interactions through tree splits
- **Impact**: Redundant feature engineering

---

## Lessons Learned

### 1. **Simplicity Wins**
- 30 carefully selected features > 209 kitchen-sink features
- Focus on feature quality, not quantity

### 2. **Domain Knowledge Matters**
- ICT concepts (order blocks, liquidity grabs) + volume-price analysis provided edge
- Generic TA-Lib indicators (RSI, MACD, Stochastic) added noise

### 3. **Feature Importance ≠ Feature Value**
- Top features (time_since_open, volatility_20, returns_20) were already in 30-feature model
- Adding 179 features didn't improve top-5 feature set

### 4. **Validation AUC Misleading**
- 0.94 AUC looked impressive but masked overfitting
- OOS performance is the only metric that matters

### 5. **Feature Engineering Traps**
- **Trap 1**: Adding correlated features (SMA_5, SMA_10, SMA_15, SMA_20)
- **Trap 2**: Creating feature interactions LightGBM already captures
- **Trap 3**: Using generic indicators without market context

---

## Recommendations

### 1. **Stick with 30-Feature Model** ✅
- Current model is profitable (55.2% win rate, +358% P&L)
- No evidence that more features help

### 2. **Feature Selection Approach**
If expanding features, use systematic selection:
```python
# Step 1: Start with 30-feature baseline
# Step 2: Add 1 feature at a time
# Step 3: Test OOS performance
# Step 4: Keep only if improves win rate + P&L
# Step 5: Remove if redundant with existing features
```

### 3. **Focus on Feature Quality**
Prioritize features with:
- **Low correlation** with existing features (<0.7)
- **High predictive power** (IC > 0.05)
- **Temporal stability** (consistent across time periods)
- **Economic intuition** (explainable edge)

### 4. **Alternative Approaches**
Instead of adding features, try:
- **Ensemble models**: Train multiple 30-feature models on different time periods
- **Sequence models**: LSTM/Transformer to capture temporal patterns
- **Regime detection**: Different models for different market conditions
- **Better labeling**: Improve ±2% threshold with dynamic ATR-based labels

### 5. **Feature Engineering Guidelines**
**DO**:
- Use domain-specific features (ICT, VPA, microstructure)
- Test features individually before combining
- Monitor feature importance over time
- Remove features with <1% importance

**DON'T**:
- Add features without hypothesis
- Use highly correlated features (>0.7)
- Create feature interactions LightGBM captures
- Trust validation AUC alone

---

## Conclusion

**The 30-feature ICT model is superior to the 209-feature comprehensive model.**

Key metrics:
- **Win rate**: 55.2% vs 47.1% (30-feature wins by 8.1 points)
- **Total P&L**: +358.49% vs -43.94% (30-feature wins by 402 points)
- **Sharpe**: 0.19 vs -0.72 (30-feature wins by 0.91 points)

**Root cause**: Overfitting, feature redundancy, and noise amplification from adding 179 generic TA-Lib indicators.

**Recommendation**: Continue using 30-feature model. Focus on improving other aspects (labeling, thresholds, training data) rather than adding more features.

**Next steps**:
1. Analyze 30-feature model feature importance (already done - see FEATURE_IMPORTANCE_REPORT.md)
2. Test asymmetric thresholds (LONG 0.40, SHORT 0.30)
3. Expand training period to 12 months
4. Explore sequence models (LSTM) for time-of-day patterns
