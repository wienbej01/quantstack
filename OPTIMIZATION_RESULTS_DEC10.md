# Optimization Results - December 10, 2025

## Executive Summary

**Mixed Results:** Optimizations improved some metrics but system still unprofitable.

| Metric | Original | Optimized | Change |
|--------|----------|-----------|--------|
| **Trades** | 2,953 | 1,330 | -55.0% ✅ |
| **Win Rate** | 36.3% | 40.8% | +12.3% ✅ |
| **Net PnL** | -$7,822 | -$5,203 | +$2,619 ✅ |
| **Stop Hits** | 60.7% | 45.6% | -24.9% ✅ |
| **Costs** | $13,243 | $2,330 | -82.4% ✅ |
| **Mean R** | 0.018 | -0.061 | -438% ❌ |

## Key Improvements ✅

### 1. Reduced Overtrading (-55% trades)
- **Original:** 2,953 trades (excessive)
- **Optimized:** 1,330 trades (more selective)
- **Impact:** Higher threshold (0.50) filtered out low-quality signals

### 2. Better Win Rate (+12.3%)
- **Original:** 36.3% win rate
- **Optimized:** 40.8% win rate
- **Impact:** Trade filters and wider stops improved success rate

### 3. Fewer Stop-Outs (-25%)
- **Original:** 60.7% stop hits (too tight)
- **Optimized:** 45.6% stop hits (more reasonable)
- **Impact:** 2.5x ATR stops vs 1.5x ATR

### 4. Massive Cost Reduction (-82%)
- **Original:** $13,243 total costs
- **Optimized:** $2,330 total costs
- **Impact:** Smaller positions (0.5% vs 1% risk) + fewer trades

## Remaining Issues ❌

### 1. Still Losing Money
- Net PnL: -$5,203 (improved but negative)
- Gross PnL: -$2,872 (strategy fundamentally flawed)

### 2. Poor R-Multiple Distribution
- Mean R: -0.061 (worse than original)
- Median R: -1.0 (most trades still hit stops)

### 3. Direction Bias
- **LONG:** 50.0% win rate, +0.369 R (profitable!)
- **SHORT:** 36.6% win rate, -0.255 R (losing)

## Exit Reason Analysis

| Reason | Original | Optimized | Change |
|--------|----------|-----------|--------|
| **Stop Hit** | 60.7% | 45.6% | -25% ✅ |
| **Target Hit** | 28.3% | 17.7% | -37% ❌ |
| **Time Exit** | 10.9% | 36.6% | +236% ⚠️ |

**Issue:** More time exits (36.6%) suggests 2-hour hold time too short.

## Root Cause Analysis

### 1. Strategy Edge Questionable
- Even with optimizations, gross PnL negative
- Suggests fundamental issue with ML predictions
- High training AUC (0.92) but poor OOS performance = overfitting

### 2. SHORT Side Broken
- LONG trades: 50% win rate, profitable
- SHORT trades: 36.6% win rate, losing
- Consider LONG-only strategy

### 3. Feature Quality Issues
- 1-minute noise overwhelming signal
- ICT/VPA features may not work on this timeframe
- Need different feature set or timeframe

## Recommendations

### Immediate (High Priority)
1. **Test LONG-only strategy** (50% win rate, +0.369 R)
2. **Extend hold time** to 4-6 hours (reduce time exits)
3. **Investigate SHORT side failure** (feature analysis)

### Medium Priority
4. **Try 10m timeframe** (less noise, better signal)
5. **Feature engineering review** (reduce overfitting)
6. **Add regime detection** (market condition filters)

### Low Priority
7. **Parameter fine-tuning** (threshold 0.45-0.55 range)
8. **Alternative ML models** (XGBoost, neural networks)

## Next Steps

### 1. LONG-Only Test
```python
# Modify backtest to trade LONG signals only
# Expected: ~414 trades, 50% win rate, positive PnL
```

### 2. 10m System Test
```python
# Run fixed 10m feature script
python scripts/build_intraday_features_10m.py
python scripts/rolling_train_10m.py
```

### 3. Hold Time Analysis
```python
# Test 4-6 hour hold times vs 2 hours
max_hold_bars = [240, 360]  # 4h, 6h
```

## Conclusion

**Partial Success:** Optimizations worked as intended:
- ✅ Reduced overtrading and costs
- ✅ Improved win rate and stop management
- ✅ Better risk control

**Core Problem Remains:** Strategy lacks fundamental edge
- Gross PnL still negative
- SHORT side consistently losing
- 1m timeframe may be too noisy

**Path Forward:** Focus on LONG-only strategy and 10m timeframe testing.

---

**Report Date:** December 10, 2025, 18:21 SGT  
**Status:** Optimization complete, strategy refinement needed  
**Next Action:** Test LONG-only and 10m systems
