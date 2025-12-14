# Regime-Aware Strategy Guide

## Overview

The regime-aware strategy improves returns by **+4.7%** (13.0% vs 8.3%) by training separate models for different market regimes while maintaining consistent cross-sectional features.

## Quick Start

```bash
# Run regime-aware backtest
python scripts/regime_aware_strategy.py
```

## Performance

| Approach | Return | Win Rate | Max DD | Trades |
|----------|--------|----------|--------|--------|
| **Regime-aware** | **+13.0%** | 49.7% | -19.6% | 5,142 |
| Baseline | +8.3% | 50.3% | -12.5% | 2,684 |

## How It Works

### 1. Regime Detection

```python
def detect_regime(df):
    # 20-bar rolling market return and volatility
    mkt_ret_20 = market_return.rolling(20).sum()
    mkt_vol_20 = market_volatility.rolling(20).mean()
    
    # Trend regime
    if mkt_ret_20 > 67th_percentile:
        trend = "bull"
    elif mkt_ret_20 < 33rd_percentile:
        trend = "bear"
    else:
        trend = "sideways"
    
    # Volatility regime
    high_vol = mkt_vol_20 > 67th_percentile
```

### 2. Separate Models Per Regime

Train independent GradientBoosting models for bull, bear, and sideways markets:

```python
models = {}
for regime in ["bull", "bear", "sideways"]:
    X_regime = X[df["trend"] == regime]
    y_regime = y[df["trend"] == regime]
    models[regime] = GradientBoostingClassifier().fit(X_regime, y_regime)
```

### 3. Regime-Specific Prediction

```python
def predict(df, models):
    for regime, model in models.items():
        mask = df["trend"] == regime
        predictions[mask] = model.predict_proba(X[mask])[:, 1]
```

### 4. Volatility-Adjusted Position Sizing

```python
# Reduce position size in high volatility
vol_adj = 0.7 if high_vol else 1.0
position_size = equity * 0.01 / 0.02 * vol_adj
```

## Features Used

The strategy uses **11 cross-sectional features** consistently across all regimes:

```python
CROSS_SECTIONAL_FEATURES = [
    "cross_rank_ret",      # Percentile rank of returns vs peers
    "cross_rank_vol",      # Percentile rank of volume vs peers
    "sector_momentum",     # Average return of sector peers
    "cross_dispersion",    # Cross-sectional return dispersion
    "market_breadth",      # Number of active symbols
    "up_down_ratio",       # Fraction of stocks with positive returns
    "rel_strength_5",      # 5-bar relative strength vs market
    "rel_strength_10",     # 10-bar relative strength vs market
    "rel_strength_20",     # 20-bar relative strength vs market
    "market_ret_5",        # 5-bar market return
    "market_ret_10",       # 10-bar market return
]
```

## Key Insights

### What Works
1. **Separate models per regime** - Different market conditions require different model weights
2. **Consistent feature set** - Cross-sectional features work across all regimes
3. **Lower threshold in high vol** - More signals when volatility is high (0.55 vs 0.58)
4. **Reduced position size in high vol** - Risk management

### What Doesn't Work
1. **Regime-specific features** - Switching features per regime hurts performance (-10.5%)
2. **Single model for all regimes** - Misses regime-specific patterns

## Integration with SIP

The regime-aware strategy integrates with the SIP (Stock In Play) selection:

```python
# In SIP configuration
sip:
  method: "hmm"
  config:
    mode: "daily"
    regime_aware: true  # Enable regime detection
    
# Strategy selection based on regime
strategy:
  bull_high_vol: "breakout"
  bear_high_vol: "breakout"
  bull_normal: "momentum"
  bear_normal: "cross_sectional"
  sideways: "cross_sectional"
```

## Files

- `scripts/regime_aware_strategy.py` - Main implementation
- `run/regime_aware_backtest.csv` - Backtest results
- `REGIME_ANALYSIS_DEC14.md` - Detailed analysis
