# Regime-Segmented Pattern Discovery

## Overview

Patterns are now discovered **separately for each market regime**, not averaged across all conditions. This prevents mixing incompatible market environments and produces regime-specific trading rules.

## Regime Definitions

### 4-Way Segmentation

| Regime | Condition | Characteristics |
|--------|-----------|-----------------|
| **bull_low_vol** | SPY > SMA20 & ATR < 70th percentile | Trending up, calm |
| **bull_high_vol** | SPY > SMA20 & ATR > 70th percentile | Trending up, volatile |
| **bear_low_vol** | SPY < SMA20 & ATR < 70th percentile | Trending down, calm |
| **bear_high_vol** | SPY < SMA20 & ATR > 70th percentile | Trending down, volatile |

### Regime Features

- **spy_above_sma20**: Bull/bear classification (20-period SMA)
- **spy_high_vol**: Volatility regime (ATR percentile > 70%)
- **spy_ret_60m**: Momentum (used as pattern feature, not segmentation)

## Why Regime Segmentation?

**Problem with averaging:**
```
Overall pattern: t-stat = 3.0, expectancy = 0.15%
  ↓ But actually:
Bull regime:  t-stat = 5.2, expectancy = 0.35%  ✅ Strong
Bear regime:  t-stat = 0.8, expectancy = -0.05% ❌ Loses money
```

**Solution:**
- Discover patterns separately per regime
- Each pattern tagged with regime context
- Backtester switches pattern sets when regime changes

## Sample Size Requirements

| Lookback | Total Samples | Per Regime (4-way) | Verdict |
|----------|---------------|-------------------|---------|
| 2 months | ~400 | ~100 | ❌ Too small |
| 4 months | ~800 | ~200 | ⚠️ Marginal |
| 6 months | ~1,200 | ~300 | ✅ Adequate |
| 12 months | ~2,400 | ~600 | ✅ Solid |

**Recommendation: 6 months minimum for regime-segmented discovery**

With ~10 trades/day:
- 6 months = ~1,200 samples
- 4 regimes = ~300 samples each
- t-stat 3.0 with 300 samples = reliable

## Output Format

### Pattern Files (Per Regime)
```
output_tstat/
├── patterns_long_30m_bull_low_vol.csv
├── patterns_long_30m_bull_high_vol.csv
├── patterns_long_30m_bear_low_vol.csv
├── patterns_long_30m_bear_high_vol.csv
├── patterns_short_30m_bull_low_vol.csv
...
└── patterns_all.csv  # Combined, sorted by t-stat
```

### Pattern Schema
```csv
rule,direction,horizon,regime,t_stat,expectancy,win_rate,profit_factor,n_trades
ret_60m_bin == 4 AND spy_ret_60m_bin == 3,LONG,60m,bull_low_vol,5.12,0.052,0.558,1.95,342
```

## Usage

### Discovery
```bash
cd ~/quantstack/sip_pattern_discovery
python run_long_short_discovery.py \
  --start-date 2024-07-01 \
  --end-date 2024-12-31 \
  --min-t-stat 3.0 \
  --min-expectancy 0.01 \
  --min-trades 50
```

### Backtesting (Future)
```python
# Load regime-specific patterns
bull_patterns = pd.read_csv("patterns_long_60m_bull_low_vol.csv")
bear_patterns = pd.read_csv("patterns_short_60m_bear_high_vol.csv")

# In backtest loop:
current_regime = detect_regime(spy_data)
active_patterns = pattern_sets[current_regime]
```

## Implementation Details

### Regime Detection (features.py)
```python
# Bull/bear
spy["sma20"] = spy["close"].rolling(20).mean()
spy["spy_above_sma20"] = spy["close"] > spy["sma20"]

# Volatility
spy["atr_20"] = compute_atr(spy, 20)
spy["atr_percentile"] = spy["atr_20"].rolling(252*60).rank(pct=True)
spy["spy_high_vol"] = spy["atr_percentile"] > 0.7
```

### Pattern Discovery (discover.py)
```python
# Define regimes
regimes = {
    "bull_low_vol": (df["spy_above_sma20"] == True) & (df["spy_high_vol"] == False),
    "bull_high_vol": (df["spy_above_sma20"] == True) & (df["spy_high_vol"] == True),
    "bear_low_vol": (df["spy_above_sma20"] == False) & (df["spy_high_vol"] == False),
    "bear_high_vol": (df["spy_above_sma20"] == False) & (df["spy_high_vol"] == True),
}

# Discover per regime
for regime_name, regime_mask in regimes.items():
    df_regime = df[regime_mask]
    patterns = discover_patterns(df_regime, ...)
    patterns["regime"] = regime_name
```

## Key Advantages

1. **No regime averaging**: Patterns optimized for specific conditions
2. **Regime awareness**: Each pattern knows its context
3. **Adaptive trading**: Switch patterns when regime changes
4. **Better statistics**: Higher t-stats within regimes vs overall
5. **Risk management**: Avoid trading patterns in wrong regime

## Next Steps

1. ✅ Implement regime-segmented discovery
2. ⏳ Run 6-month discovery scan
3. ⏳ Analyze regime distribution and pattern quality
4. ⏳ Build regime-aware backtester
5. ⏳ Implement walk-forward validation per regime
