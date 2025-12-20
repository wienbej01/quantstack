# L2 Scalping Feature Analysis Report

**Date**: 2025-12-20  
**Data**: 192,841 L2 records across 48 symbols (Dec 17-19, 2025)

## Executive Summary

Analysis comparing L2-only signals vs L2+Context (OHLCV) features reveals that **pure L2 signals outperform combined strategies** for short-term scalping.

### Key Finding: L2-Only is Superior

| Strategy | Mean Return (10s) | Win Rate | Sharpe |
|----------|-------------------|----------|--------|
| **l2_extreme_obi** (OBI > 0.5) | **0.76 bps** | 31.5% | 14.60 |
| l2_high_vol (OBI + volume) | 0.69 bps | 33.3% | 9.43 |
| l2_obi_depth (OBI + depth) | 0.61 bps | 32.0% | 12.69 |
| l2_obi_03 (baseline) | 0.55 bps | 31.3% | 17.33 |
| l2_vwap_mean_rev (L2 + VWAP) | 0.43 bps | 29.5% | 11.26 |
| l2_mom_vwap (L2 + mom + VWAP) | 0.10 bps | 33.6% | 0.73 |

## Analysis Results

### 1. Best Performing Strategies

**By Mean Return (10s horizon):**
1. `l2_extreme_obi`: 0.76 bps - Uses OBI threshold of ±0.5
2. `l2_high_vol`: 0.69 bps - OBI + relative volume > 1.2
3. `l2_obi_depth`: 0.61 bps - OBI + depth imbalance confirmation

**By Win Rate:**
1. `l2_obi_mom5`: 36.1% - OBI + 5s momentum alignment
2. `l2_high_vol`: 33.3% - OBI + high volume filter
3. `l2_obi_depth`: 32.0% - OBI + depth confirmation

**By Sharpe Ratio:**
1. `l2_obi_02`: 18.57 - Lower threshold, more signals
2. `l2_obi_025`: 18.10 - Balanced threshold
3. `l2_obi_03`: 17.33 - Current baseline

### 2. Context Features Analysis

Adding OHLCV context features **reduces performance**:

| Feature Added | Impact on Return | Impact on Win Rate |
|---------------|------------------|-------------------|
| VWAP distance | -0.12 bps | -1.8% |
| RSI filter | -0.04 bps | -1.0% |
| Momentum | -0.16 bps | +4.8% |
| Combined | -0.45 bps | +2.3% |

**Why Context Hurts Performance:**
1. **Signal Delay**: 1-minute bars lag behind L2 data
2. **Over-filtering**: Context filters remove valid L2 signals
3. **Different Timescales**: VWAP/RSI designed for longer holds

### 3. Optimal Strategy Recommendations

**For Maximum Return:**
```python
# Use extreme OBI threshold
signal = 1 if obi_1 > 0.5 else (-1 if obi_1 < -0.5 else 0)
```
- Expected return: 0.76 bps per signal
- ~35,000 signals per 2 days
- Best for aggressive scalping

**For Maximum Sharpe:**
```python
# Use moderate OBI threshold
signal = 1 if obi_1 > 0.2 else (-1 if obi_1 < -0.2 else 0)
```
- Expected return: 0.52 bps per signal
- ~92,000 signals per 2 days
- Best for consistent performance

**For Best Win Rate:**
```python
# OBI + momentum confirmation
signal = 1 if (obi_1 > 0.25 and d_mid_5s > 0) else ...
```
- Win rate: 36.1%
- Fewer signals but higher accuracy

### 4. Implementation Recommendations

1. **Keep L2-only signals** for the scalping system
2. **Increase OBI threshold** from 0.3 to 0.5 for higher returns
3. **Add depth imbalance** as secondary confirmation
4. **Remove VWAP/RSI filters** - they hurt performance
5. **Consider volume filter** only during high-volume periods

### 5. Updated Signal Logic

```python
# Recommended signal generation
def generate_signal(snapshot):
    # Primary: Extreme OBI
    if snapshot.obi_1 > 0.5:
        return BUY
    elif snapshot.obi_1 < -0.5:
        return SELL
    
    # Secondary: OBI + depth confirmation
    if snapshot.obi_1 > 0.3 and snapshot.depth_imb_k > 0.1:
        return BUY
    elif snapshot.obi_1 < -0.3 and snapshot.depth_imb_k < -0.1:
        return SELL
    
    return HOLD
```

## Data Summary

- **Total L2 Records**: 192,841
- **Symbols**: 48 NYSE stocks
- **Date Range**: Dec 17-19, 2025
- **1-min Bars Downloaded**: ~42,000 from Polygon
- **Context Coverage**: 100%

## Files Generated

- `analysis/output/analysis_results_*.csv` - Raw comparison data
- `analysis/output/strategy_comparison.csv` - Strategy metrics
- `analysis/l2_context_analysis.py` - Main analysis script
- `analysis/extended_analysis.py` - Multi-strategy comparison

## Conclusion

**L2 microstructure data alone provides superior signal quality for short-term scalping.** Adding 1-minute OHLCV context features introduces lag and over-filtering that degrades performance. The optimal approach is to use extreme OBI thresholds (±0.5) with optional depth imbalance confirmation.
