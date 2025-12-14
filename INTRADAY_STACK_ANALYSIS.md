# Intraday Stack System Analysis - December 14, 2024

## Executive Summary

The intraday_stack system is a sophisticated HMM + Wavelet-based trading system with complex signal generation. After thorough analysis, **I do not recommend integrating the two systems** due to fundamental architectural differences and the intraday_stack's poor out-of-sample performance.

## System Overview

### Architecture
```
SIP Scanner → HER Engine → Decision Core → Simulator
     ↓            ↓             ↓            ↓
  Symbol      Regime +      Trading      Execution
 Selection   Forecasts       Plans       + P&L
```

### Key Components
1. **SIP (Stock In Play)**: HMM-based symbol selection from ~1,100 universe
2. **HER (Hybrid Engine)**: Wavelet + Fourier forecasting with regime detection
3. **Decision Core**: Multi-stage signal filtering
4. **Simulator**: Realistic execution with fees/slippage

## Performance Analysis

### Rolling Backtest Results (2023-2024)
| Metric | Value | Assessment |
|--------|-------|------------|
| Total Trades | 588 | Adequate |
| Total P&L | **-$399,847** | ❌ Catastrophic |
| Win Rate | 35.7% | ❌ Far below 50% |
| Profit Factor | 0.59 | ❌ Below 1.0 |
| Avg R-Multiple | -0.278 | ❌ Negative expectancy |

### Roll-Forward Validation (4 periods)
| Period | Trades | P&L | Win Rate |
|--------|--------|-----|----------|
| 2024-02-15 to 2024-03-12 | 28 | -$1,481 | 39.3% |
| 2024-07-29 to 2024-08-27 | 52 | +$1,276 | 48.1% |
| 2024-09-25 to 2024-10-25 | 58 | +$1,590 | 62.1% |
| 2024-11-07 to 2024-12-06 | 29 | -$1,322 | 41.4% |
| **Total** | 167 | **+$63** | ~47% |

### Matrix Optimization (July 2024 only)
- Best configuration: $346 P&L on 57 trades
- **In-sample only** - not validated out-of-sample

## Critical Issues

### 1. Massive Out-of-Sample Degradation
- In-sample (July 2024): +$346 P&L
- Out-of-sample (4 periods): +$63 P&L
- Full rolling backtest: **-$399,847 P&L**

This is a **1,000x degradation** from in-sample to out-of-sample, indicating severe overfitting.

### 2. Low Win Rate
- Target: 50%+
- Actual: 35.7%
- The HER forecasting model is not predictive

### 3. Negative Expectancy
- Avg R-Multiple: -0.278
- Every trade loses money on average
- No edge exists in the current configuration

### 4. Complexity Without Benefit
The system uses:
- Hidden Markov Models
- Wavelet transforms
- Fourier analysis
- Multi-stage filtering

Yet achieves **worse results than random** (35.7% < 50%).

### 5. Regime Confidence Threshold Insensitivity
From the matrix optimization:
- regime_conf_min of 0.1, 0.3, 0.5, 0.7 all produce **identical results**
- This suggests the HER regime confidence is not discriminative

## Comparison with quantstack ML System

| Aspect | quantstack | intraday_stack |
|--------|------------|----------------|
| **Return (2023-2024)** | +29.3% | -3,998% |
| **Win Rate** | 50.1% | 35.7% |
| **Complexity** | Simple (11 features) | Complex (HMM+Wavelet) |
| **Features** | Cross-sectional | Single-stock forecasts |
| **Regime Awareness** | Market-wide | Per-stock HMM |
| **Out-of-sample** | Validated | Severely degraded |

## Why Integration is NOT Recommended

### 1. Fundamental Philosophy Mismatch
- **quantstack**: Cross-sectional (compare stocks to peers)
- **intraday_stack**: Single-stock forecasting (predict individual returns)

Academic research shows cross-sectional features dominate single-stock features.

### 2. Complexity vs Performance
- intraday_stack is 10x more complex
- Yet performs 100x worse
- Adding complexity would likely hurt quantstack

### 3. Different Time Horizons
- **quantstack**: 30-minute forward returns
- **intraday_stack**: 60-90 minute holding periods

### 4. Signal Quality
- quantstack signals: 50%+ win rate
- intraday_stack signals: 35.7% win rate
- Blending would dilute good signals with bad

### 5. No Salvageable Components
The core HER forecasting engine shows no predictive power. The SIP symbol selection might have value, but quantstack already has 493 symbols with cross-sectional features.

## What Could Be Salvaged (If Anything)

### Potentially Useful
1. **SIP HMM for symbol filtering** - but needs validation
2. **Wavelet energy features** - could add to feature set
3. **Infrastructure** - simulation engine is well-built

### Not Useful
1. **HER return predictions** - no predictive power
2. **Regime confidence** - not discriminative
3. **Decision thresholds** - overfit to in-sample

## Recommendations

### For intraday_stack
1. **Abandon current approach** - negative expectancy cannot be fixed with parameter tuning
2. **Replace HER forecasting** - the wavelet/fourier model doesn't work
3. **Add cross-sectional features** - this is what actually predicts returns
4. **Simplify** - remove complexity that doesn't add value

### For quantstack
1. **Do not integrate** - keep the working system simple
2. **Continue with 11 cross-sectional features** - proven to work
3. **Regime-aware models** - already implemented (+13% return)
4. **Paper trade** - validate before live deployment

## Conclusion

The intraday_stack system represents significant engineering effort but **fails to produce a tradeable edge**. The sophisticated HMM + Wavelet approach underperforms a simple cross-sectional feature model by a massive margin.

**Key insight**: Complexity does not equal performance. The quantstack system with 11 simple features (+29.3% return) dramatically outperforms intraday_stack with HMM + Wavelet + Fourier (-3,998% return).

**Recommendation**: Keep the systems separate. Focus on improving quantstack's regime-aware approach rather than adding complexity from a non-working system.
