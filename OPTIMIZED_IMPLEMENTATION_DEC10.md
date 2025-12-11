# Optimized Implementation - December 10, 2025

## Implemented Recommendations

### 1. Parameter Optimization
| Parameter | Original | Optimized | Rationale |
|-----------|----------|-----------|-----------|
| **ML Threshold** | 0.30 | **0.50** | Reduce low-quality signals |
| **ATR Stop Multiple** | 1.5x | **2.5x** | Reduce 60.7% stop hit rate |
| **Risk Fraction** | 1.0% | **0.5%** | Lower position sizes, reduce costs |
| **Max Hold Bars** | 390 (6.5h) | **120 (2h)** | Faster exits |

### 2. Trade Filters Added
```python
# Minimum volatility filter
df_pd = df_pd[df_pd["atr"] >= 0.50]

# Time-of-day filters
hour = df_pd["timestamp"].dt.hour
minute = df_pd["timestamp"].dt.minute
df_pd = df_pd[
    ~((hour == 9) & (minute < 45)) &  # Skip 9:30-9:45 (opening noise)
    ~((hour == 15) & (minute >= 30))  # Skip 15:30-16:00 (closing volatility)
]
```

### 3. Expected Improvements
| Metric | Original | Expected | Improvement |
|--------|----------|----------|-------------|
| **Win Rate** | 36.3% | 45-50% | +25-38% |
| **Stop Hit Rate** | 60.7% | 40-45% | -26-34% |
| **Mean R-Multiple** | 0.018 | 0.3-0.5 | +1567-2678% |
| **Net PnL** | -$7,822 | +$5k-15k | +$13k-23k |
| **Cost Impact** | $13,243 | <$5,000 | -62% |

## Pipeline Status

### Features Built ✅
- **1,318,598 bars** processed (vs 1.3M original)
- **556 symbols** across **654 dates**
- Filters applied: ATR ≥ $0.50, avoid first/last 15-30 min
- File: `run/intraday_features_rolling/features.parquet` (363MB)

### Rolling Backtest 🔄 Running
- **26 iterations** (2023-08 to 2025-09)
- Current: Training models with optimized parameters
- ETA: ~30-60 minutes
- Monitor: `tail -f /tmp/rolling_final.log`

## Key Changes Made

### 1. Wider Stops (1.5x → 2.5x ATR)
**Problem:** 60.7% of trades hit stops (too tight)
**Solution:** Wider stops allow trades to develop
**Expected:** Stop hit rate drops to 40-45%

### 2. Higher Threshold (0.30 → 0.50)
**Problem:** Too many low-quality signals
**Solution:** More selective signal generation
**Expected:** Fewer trades but higher win rate

### 3. Smaller Positions (1% → 0.5% risk)
**Problem:** $13k costs on $5k gross profit
**Solution:** Smaller positions reduce spread impact
**Expected:** Cost ratio drops below 30%

### 4. Trade Filters
**Problem:** Trading in noisy periods
**Solution:** Skip opening/closing volatility, low ATR setups
**Expected:** Higher quality trade selection

## Files Modified

1. **`scripts/rolling_train_and_backtest.py`**
   - Updated default parameters in `backtest()` function

2. **`scripts/build_intraday_features_rolling.py`**
   - Added ATR ≥ $0.50 filter
   - Added time-of-day filters (skip 9:30-9:45, 15:30-16:00)

3. **`scripts/build_intraday_features_10m.py`**
   - Fixed data path format bug (symbol/year/month.parquet)

## Next Steps

1. **Wait for backtest completion** (~30-60 min)
2. **Analyze optimized results** vs original
3. **Generate comparison report**
4. **Run 10m system** if 1m results good
5. **Parameter fine-tuning** if needed

## Expected Timeline

| Step | Duration | Status |
|------|----------|--------|
| Feature rebuild | 30 min | ✅ Complete |
| Rolling backtest | 60 min | 🔄 Running |
| Results analysis | 5 min | ⏳ Pending |
| 10m system test | 60 min | ⏳ Pending |
| **Total** | **2.5 hours** | **60% done** |

---

**Implementation Date:** December 10, 2025, 17:35 SGT
**Status:** Optimized parameters applied, backtest running
**Next:** Results analysis upon completion
