# Matrix Optimization Report - December 10, 2025

## Test Period: April - September 2025 (6 months)

### 🏆 Optimal Configuration

| Parameter | Value |
|-----------|-------|
| **Hold Bars** | 10 |
| **Threshold** | 0.40 |
| **Position %** | 20% |
| **Trades** | 646 |
| **PnL** | +$1,665 |
| **Win Rate** | 50.3% |

---

## Grid Search Results

### Parameters Tested
- **Hold Bars:** 3, 5, 7, 10, 15
- **Threshold:** 0.40, 0.50, 0.60
- **Position %:** 5%, 10%, 15%, 20%
- **Total Combinations:** 60

### Top 10 Configurations

| Rank | Hold | Thresh | Pos% | Trades | PnL | Win% |
|------|------|--------|------|--------|-----|------|
| 1 | 10 | 0.40 | 20% | 646 | +$1,665 | 50.3% |
| 2 | 15 | 0.40 | 20% | 642 | +$1,631 | 51.2% |
| 3 | 10 | 0.40 | 15% | 646 | +$1,128 | 50.0% |
| 4 | 15 | 0.40 | 15% | 642 | +$1,107 | 51.2% |
| 5 | 15 | 0.50 | 20% | 374 | +$911 | 50.0% |
| 6 | 7 | 0.40 | 20% | 646 | +$867 | 47.5% |
| 7 | 5 | 0.40 | 20% | 648 | +$696 | 50.0% |
| 8 | 10 | 0.50 | 20% | 378 | +$679 | 49.2% |
| 9 | 5 | 0.50 | 20% | 379 | +$670 | 50.7% |
| 10 | 15 | 0.50 | 15% | 374 | +$608 | 50.0% |

### Worst 5 Configurations

| Rank | Hold | Thresh | Pos% | Trades | PnL | Win% |
|------|------|--------|------|--------|-----|------|
| 56 | 3 | 0.50 | 10% | 379 | -$402 | 47.0% |
| 57 | 3 | 0.40 | 5% | 640 | -$410 | 43.4% |
| 58 | 3 | 0.60 | 20% | 233 | -$481 | 45.9% |
| 59 | 3 | 0.50 | 15% | 379 | -$498 | 47.0% |
| 60 | 3 | 0.50 | 20% | 379 | -$589 | 47.5% |

---

## Analysis by Parameter

### By Hold Bars (Best Config Each)

| Hold Bars | Best PnL | Win Rate | Config |
|-----------|----------|----------|--------|
| **3** | -$225 | 42.0% | thresh=0.60, pos=5% |
| **5** | +$696 | 50.0% | thresh=0.40, pos=20% |
| **7** | +$867 | 47.5% | thresh=0.40, pos=20% |
| **10** | +$1,665 | 50.3% | thresh=0.40, pos=20% |
| **15** | +$1,631 | 51.2% | thresh=0.40, pos=20% |

**Finding:** Longer holds (10-15 bars) significantly outperform shorter holds.

### By Threshold (Best Config Each)

| Threshold | Best PnL | Win Rate | Config |
|-----------|----------|----------|--------|
| **0.40** | +$1,665 | 50.3% | hold=10, pos=20% |
| **0.50** | +$911 | 50.0% | hold=15, pos=20% |
| **0.60** | +$314 | 49.1% | hold=15, pos=20% |

**Finding:** Lower threshold (0.40) captures more profitable signals.

### By Position Size (Best Config Each)

| Position % | Best PnL | Win Rate | Config |
|------------|----------|----------|--------|
| **5%** | +$68 | 48.1% | hold=15, thresh=0.40 |
| **10%** | +$570 | 49.5% | hold=10, thresh=0.40 |
| **15%** | +$1,128 | 50.0% | hold=10, thresh=0.40 |
| **20%** | +$1,665 | 50.3% | hold=10, thresh=0.40 |

**Finding:** Larger positions maximize returns (linear scaling).

---

## Key Insights

### ✅ What Works
1. **Longer holds (10-15 bars)** - Trades need time to develop
2. **Lower threshold (0.40)** - More signals, more opportunities
3. **Larger positions (20%)** - Maximize edge exploitation
4. **50%+ win rate** - Consistent across top configs

### ❌ What Doesn't Work
1. **3-bar holds** - Consistently lose money (all configs negative)
2. **High threshold (0.60)** - Too few trades, misses opportunities
3. **Small positions (5%)** - Costs eat into profits

### 📊 Profitability Summary
- **Profitable configs:** 35/60 (58%)
- **Losing configs:** 25/60 (42%)
- **All 3-bar configs:** Negative PnL

---

## Recommended Configuration

### Production Settings
```python
hold_bars = 10        # 10-minute hold (on 1m bars)
threshold = 0.40      # Lower threshold for more signals
position_pct = 0.20   # 20% of equity per trade
```

### Expected Performance (6-month)
- **Trades:** ~650
- **Win Rate:** ~50%
- **PnL:** +$1,500 - $1,700
- **Monthly:** +$250 - $280

### Risk Considerations
- 20% position size is aggressive
- Consider 15% for more conservative approach (+$1,128 PnL)
- 10-bar hold = 10 minutes exposure per trade

---

## Comparison to Previous Systems

| System | PnL | Win Rate | Notes |
|--------|-----|----------|-------|
| Original (leaky) | Profitable | High | Data leakage |
| Complex stops | -$5,203 | 40.8% | Over-engineered |
| Simple 5-bar | +$1,477 | 46.7% | Baseline |
| **Optimized 10-bar** | **+$1,665** | **50.3%** | **Best** |

---

## Next Steps

1. **Validate on different periods** - Test 2024 data
2. **Live paper trading** - Forward test optimal config
3. **Risk management** - Add max daily loss limits
4. **Position sizing** - Test Kelly criterion

---

**Report Date:** December 10, 2025, 20:56 SGT
**Test Period:** April - September 2025
**Optimal Config:** hold=10, thresh=0.40, pos=20%
