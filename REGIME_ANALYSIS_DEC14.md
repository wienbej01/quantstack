# Regime-Aware Strategy Analysis - December 14, 2024

## Executive Summary

Regime awareness **improves returns when using separate models per regime**, but **hurts performance when switching feature sets**.

## Backtest Results (2023-2024)

| Approach | Return | Win Rate | Trades | Max DD |
|----------|--------|----------|--------|--------|
| **Regime-aware models** | **+13.0%** | 49.7% | 5,142 | TBD |
| Baseline (no regime) | +8.3% | 50.3% | 2,684 | -12.5% |
| Regime-aware features | -10.5% | 49.2% | 6,219 | TBD |

## Key Findings

### 1. Regime Detection
- **Bull**: Market return (20-bar) > 67th percentile
- **Bear**: Market return (20-bar) < 33rd percentile  
- **Sideways**: Between thresholds
- **High Vol**: Market volatility > 67th percentile

### 2. Strategy Performance by Regime

| Regime | Best Strategy | Win Rate | Edge |
|--------|---------------|----------|------|
| Bull + High Vol | Breakout | 52.2% | +2.2% |
| Bear + High Vol | Breakout | 51.9% | +1.9% |
| Bull + Normal | Fade | 49.8% | -0.2% |
| Bear + Normal | Fade | 48.1% | -1.9% |
| Sideways + High Vol | Fade | 46.4% | -3.6% |

**Key insight**: Breakout strategies work in HIGH VOLATILITY regimes regardless of trend direction.

### 3. Feature Set Performance by Regime

| Regime | Cross-Sectional | All Features | Winner |
|--------|-----------------|--------------|--------|
| Bear | **59.9%** | 47.3% | Cross-sectional |
| Sideways | **57.9%** | 32.9% | Cross-sectional |
| Bull | 46.4% | **51.8%** | All features |

**Key insight**: Cross-sectional features dominate in BEAR and SIDEWAYS markets. All features work better in BULL markets.

### 4. Win Rate by Regime (Baseline Model)

| Regime | Win Rate | Trades |
|--------|----------|--------|
| Bull | 51.5% | 849 |
| Bear | 51.3% | 682 |
| Sideways | 48.9% | 1,153 |

## Recommendations for SIP

### 1. Use Regime-Aware Model Selection
Train separate models for each regime, but use the SAME feature set (cross-sectional).

### 2. Strategy Selection by Regime
- **High Volatility (any trend)**: Use BREAKOUT strategies
- **Low Volatility**: Use FADE/REVERSION strategies
- **Bear Market**: Prioritize cross-sectional features
- **Bull Market**: Can include more technical features

### 3. Position Sizing by Regime
- **High Vol**: Reduce position size (higher risk)
- **Low Vol**: Can increase position size
- **Bear**: Tighter stops, smaller positions

## Implementation

```python
# Regime detection
def detect_regime(df):
    mkt_ret_20 = df.groupby('timestamp')['returns'].transform('mean').rolling(20).sum()
    mkt_vol_20 = df.groupby('timestamp')['returns'].transform('std').rolling(20).mean()
    
    trend = 'sideways'
    if mkt_ret_20 > mkt_ret_20.quantile(0.67):
        trend = 'bull'
    elif mkt_ret_20 < mkt_ret_20.quantile(0.33):
        trend = 'bear'
    
    high_vol = mkt_vol_20 > mkt_vol_20.quantile(0.67)
    
    return trend, high_vol

# Model selection
def select_model(trend, high_vol, models):
    if high_vol:
        return models['breakout']
    elif trend == 'bear':
        return models['cross_sectional']
    else:
        return models['default']
```

## Conclusion

**Regime awareness adds +4.7% return** (13.0% vs 8.3%) when implemented correctly:
1. Use separate models per regime
2. Keep feature set consistent (cross-sectional)
3. Adjust strategy (breakout in high vol, fade in low vol)
4. Don't over-complicate with regime-specific features
