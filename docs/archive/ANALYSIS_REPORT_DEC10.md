# Analysis Report - December 10, 2025

## 1. 10m Feature Generation Failure

### Root Cause
The `build_intraday_features_10m.py` script used **wrong data path format**:

**Broken (10m script):**
```python
GOLD_DIR = GCS_MOUNT / "gold" / "stocks" / "1m"
parquet_file = GOLD_DIR / f"{symbol}.parquet"  # WRONG: symbol.parquet doesn't exist
```

**Working (1m script):**
```python
DATA_ROOT = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
symbol_path = DATA_ROOT / symbol
parquet_file = symbol_path / str(year) / f"{month}.parquet"  # CORRECT: symbol/year/month.parquet
```

### Fix Applied
Updated `load_intraday_bars()` to use correct path structure: `symbol/year/YYYY-MM.parquet`

---

## 2. 1m System Performance Analysis

### Summary Metrics
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total Trades | 2,953 | - | ✓ |
| Win Rate | 36.3% | 50-60% | ❌ |
| Mean R-Multiple | 0.018 | 0.3-0.8 | ❌ |
| Median R-Multiple | -1.000 | >0 | ❌ |
| Stop Hit Rate | 60.7% | 40-60% | ❌ |
| Target Hit Rate | 28.3% | 10-20% | ⚠️ High |
| Time Exit Rate | 10.9% | 20-40% | ⚠️ Low |
| Gross PnL | +$5,421 | - | ✓ |
| Net PnL | -$7,822 | >0 | ❌ |
| Cost Impact | $13,243 | - | ⚠️ High |

### Exit Reason Breakdown
```
stop_hit:    60.7%  ← Too many stops hit
target_hit:  28.3%  ← Good target rate
time_exit:   10.9%  ← Few time exits
```

### By Direction
| Side | Trades | Win Rate | Avg R |
|------|--------|----------|-------|
| LONG | 978 | 36.7% | 0.013 |
| SHORT | 1,975 | 36.1% | 0.020 |

Both sides perform similarly poorly.

---

## 3. Root Cause Analysis: Poor Performance

### Issue 1: Stops Too Tight (1.5x ATR)
- **60.7% stop hit rate** indicates stops are triggered too frequently
- Market noise is hitting stops before trades can develop
- ATR on 1m bars is very small, making stops extremely tight

**Evidence:**
- Mean stop distance: $1.78
- Median stop distance: $0.99
- Mean ATR: $1.18

### Issue 2: High Transaction Costs
- **$13,243 total costs** on $5,421 gross profit
- Costs exceed gross profit by 2.4x
- High-frequency 1m trading amplifies costs

**Cost Breakdown:**
- Fees: $5,129 (avg $1.74/trade)
- Spread: $8,113 (avg $2.75/trade)
- Total: $4.49/trade average

### Issue 3: ML Threshold Too Permissive
- **0.30 threshold** generates too many low-quality signals
- Model AUC ~0.92 in training but poor OOS performance
- Indicates overfitting to training data

### Issue 4: Position Sizing on Tight Stops
- 1% risk with tight stops = large position sizes
- Large positions amplify spread costs
- Mean shares: ~400-600 per trade

---

## 4. Enhancement Recommendations

### Priority 1: Widen Stops (High Impact)
```python
# Current
atr_stop_multiple = 1.5  # Too tight

# Recommended
atr_stop_multiple = 2.5  # Wider stops
```
**Expected Impact:** Reduce stop hit rate from 60% to 40-45%

### Priority 2: Raise ML Threshold (High Impact)
```python
# Current
threshold = 0.30  # Too permissive

# Recommended
threshold = 0.50  # More selective
```
**Expected Impact:** Fewer trades but higher quality, win rate 45-55%

### Priority 3: Reduce Position Size (Medium Impact)
```python
# Current
risk_fraction = 0.01  # 1% risk

# Recommended
risk_fraction = 0.005  # 0.5% risk
```
**Expected Impact:** Lower cost impact per trade

### Priority 4: Add Trade Filters (Medium Impact)
```python
# Minimum ATR filter
min_atr = 0.50  # Skip low-volatility setups

# Time-of-day filter
avoid_first_15_min = True  # Skip opening noise
avoid_last_30_min = True   # Skip closing volatility

# Volume filter
min_relative_volume = 1.5  # Only trade when volume elevated
```

### Priority 5: Consider 10m Timeframe (Medium Impact)
- Fewer trades = lower costs
- Wider ATR = more reasonable stops
- Less noise = better signal quality

---

## 5. Parameter Optimization Matrix

| Parameter | Current | Conservative | Moderate | Aggressive |
|-----------|---------|--------------|----------|------------|
| ATR Stop Multiple | 1.5 | 3.0 | 2.5 | 2.0 |
| ML Threshold | 0.30 | 0.60 | 0.50 | 0.40 |
| Risk Fraction | 1.0% | 0.25% | 0.5% | 0.75% |
| R Target | 2.0 | 1.5 | 2.0 | 2.5 |
| Max Hold Bars | 390 | 60 | 120 | 240 |

### Recommended Starting Point: Moderate
```python
atr_stop_multiple = 2.5
threshold = 0.50
risk_fraction = 0.005
r_target = 2.0
max_hold_bars = 120
```

---

## 6. Expected Improvement

### Current State
- Win Rate: 36.3%
- Avg R: 0.018
- Net PnL: -$7,822

### With Recommended Changes
- Win Rate: 45-50% (wider stops, better signals)
- Avg R: 0.3-0.5 (fewer stop-outs)
- Net PnL: +$5,000 to +$15,000 (estimated)

### Key Metrics to Monitor
1. Stop hit rate < 50%
2. Win rate > 45%
3. Avg R > 0.2
4. Cost ratio < 30% of gross

---

## 7. Implementation Steps

### Step 1: Fix 10m Script (Done)
```bash
# Already fixed - correct data path format
```

### Step 2: Run Parameter Sweep
```bash
# Create parameter sweep script
python scripts/parameter_sweep.py \
  --stop-multiples 2.0,2.5,3.0 \
  --thresholds 0.40,0.50,0.60 \
  --risk-fractions 0.005,0.0075,0.01
```

### Step 3: Run 10m System
```bash
python scripts/build_intraday_features_10m.py
python scripts/rolling_train_10m.py
python scripts/compare_1m_vs_10m.py
```

### Step 4: Analyze Results
- Compare 1m vs 10m performance
- Select best parameter combination
- Validate on holdout period

---

## 8. Summary

### 10m Failure: Data Path Bug
- Script used wrong parquet path format
- Fixed by copying path logic from working 1m script

### 1m Poor Performance: Multiple Issues
1. **Stops too tight** (1.5x ATR) → 60.7% stop rate
2. **Costs too high** ($13k costs on $5k gross)
3. **Threshold too low** (0.30) → too many bad trades
4. **Overfitting** (0.92 train AUC, poor OOS)

### Key Recommendations
1. Widen stops to 2.5x ATR
2. Raise threshold to 0.50
3. Reduce risk to 0.5%
4. Add trade filters
5. Test 10m timeframe

---

**Report Generated:** December 10, 2025
**Status:** Ready for parameter optimization
