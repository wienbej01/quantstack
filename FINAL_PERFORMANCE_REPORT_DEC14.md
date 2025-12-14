# Final Performance Report - December 14, 2024

## Executive Summary

After comprehensive feature generation, optimization, model training, and rolling backtesting, the **regime-aware strategy with 11 cross-sectional features** delivers the best performance.

## Performance Comparison

| Approach | Return | Win Rate | Max DD | Trades | Sharpe |
|----------|--------|----------|--------|--------|--------|
| **Regime-aware (11 features)** | **+13.0%** | 49.7% | -19.6% | 5,142 | ~0.4 |
| Cross-sectional only (11) | +8.3% | 50.3% | -12.5% | 2,684 | ~0.3 |
| Optimized (18 features) | +7.3% | 48.8% | -23.5% | 7,712 | 0.21 |
| All 57 features | -21.3% | 48.5% | -52.9% | 7,598 | <0 |
| Top 502-analysis (28) | -19.2% | 48.9% | -34.9% | 4,834 | <0 |

## Key Findings

### 1. Less is More
Adding more features **hurts performance**:
- 11 features → +13.0%
- 18 features → +7.3%
- 28 features → -19.2%
- 57 features → -21.3%

### 2. Regime Awareness Helps
Separate models per regime add **+4.7%** return:
- Regime-aware: +13.0%
- Single model: +8.3%

### 3. Cross-Sectional Features Dominate
The 11 winning features are all **market-relative**:
```
cross_rank_ret, cross_rank_vol, sector_momentum, cross_dispersion,
market_breadth, up_down_ratio, rel_strength_5/10/20, market_ret_5/10
```

### 4. Performance by Regime
| Regime | Win Rate | Avg Return | Trades |
|--------|----------|------------|--------|
| Bull | 50.2% | -0.002% | 2,031 |
| Bear | 49.4% | -0.014% | 1,721 |
| Sideways | 49.4% | +0.030% | 1,390 |

### 5. Top Model Features (by importance)
1. ret_20bar (29.2%)
2. market_breadth (24.2%)
3. ret_15bar (17.4%)
4. mkt_vol_10 (9.7%)
5. sector_momentum (6.8%)

## Recommended Configuration

```python
# Feature set
FEATURES = [
    "cross_rank_ret", "cross_rank_vol", "sector_momentum", 
    "cross_dispersion", "market_breadth", "up_down_ratio",
    "rel_strength_5", "rel_strength_10", "rel_strength_20",
    "market_ret_5", "market_ret_10"
]

# Model
model = GradientBoostingClassifier(
    n_estimators=50, 
    max_depth=3,
    learning_rate=0.1
)

# Regime-aware training
for regime in ["bull", "bear", "sideways"]:
    models[regime] = model.fit(X[regime], y[regime])

# Position sizing
vol_adj = 0.7 if high_vol else 1.0
position_size = equity * 0.01 / 0.02 * vol_adj
```

## Run Commands

```bash
# Best approach: Regime-aware
python scripts/regime_aware_strategy.py

# Alternative: Cross-sectional only
python scripts/roll_forward_test.py
```

## Files
- `scripts/regime_aware_strategy.py` - Production implementation
- `run/regime_aware_backtest.csv` - Trade log
- `run/final_backtest_trades.csv` - Full pipeline results
- `run/final_backtest_monthly.csv` - Monthly summary
