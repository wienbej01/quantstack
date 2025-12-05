# Training & Backtest Results - December 5, 2025

**Completed:** 21:59 SGT  
**Branch:** `feature/migrate-to-backtrader`  
**Commit:** `aeb000a`

---

## Executive Summary

✅ **Training Complete** - Both models trained successfully in 36 minutes  
⚠️ **Not Yet Profitable** - Model needs optimization  
✅ **Infrastructure Working** - Backtest engine, feature logging, automation all functional

---

## Training Results

### Stage 1: Probability Model

**Performance:**
- ROC AUC: **0.9838** ✅ (excellent)
- Accuracy: **93.9%**
- Precision: **55.5%** (for bigmove class)
- Recall: **99.2%** (catches almost all bigmoves)

**Feature Quality:**
- Max correlation: **0.2643** ✅ (target: >0.10)
- Features > 0.10: **5** ✅
- Features > 0.05: **9** ✅

**Top Features:**
1. `f__time__hour_cos`: 0.2643 (time of day)
2. `f__range__ratio_1.0`: 0.1329 (volatility)
3. `f__time__hour_sin`: -0.1250 (time of day)
4. `f__time__minute_sin`: -0.1220 (intraday timing)
5. `f__vol__sum_3`: 0.1015 (volume)

**Training Data:**
- Samples: 140,642
- Features: 68
- Class distribution: 92.5% neutral, 7.5% bigmove

### Stage 2: Direction Model

**Performance:**
- ROC AUC: **0.9999** ✅ (near perfect)
- Accuracy: **99.9%**
- Precision: **99.9%**
- Recall: **99.9%**

**Feature Quality:**
- Max correlation: **0.0752** ⚠️ (target: >0.10, slightly below)
- Features > 0.05: **19** ✅

**Top Features:**
1. `f__vwap__z_10_20`: 0.0752 (VWAP deviation)
2. `f__vwap__z_10_60`: 0.0716 (VWAP deviation)
3. `f__vwap__z_5_20`: 0.0711 (VWAP deviation)
4. `f__vwap__z_5_30`: 0.0694 (VWAP deviation)
5. `f__vwap__z_5_60`: 0.0678 (VWAP deviation)

**Training Data:**
- Samples: 10,607
- Features: 68
- Class distribution: 51.2% long, 48.8% short (balanced)

---

## Prediction Analysis (OOS - May 2024)

### Distribution

**Current:**
- Neutral: **90.89%** (target: 60-70%)
- Long: **5.02%** (target: 15-20%)
- Short: **4.09%** (target: 15-20%)

**vs Baseline (old model):**
- Neutral: 90.89% vs 94.5% ✅ (improvement)
- Long: 5.02% vs 1.0% ✅ (5x improvement)
- Short: 4.09% vs 4.5% ✅ (similar)

**Issue:** Model still too conservative, predicting neutral too often

### Probability Statistics

- Mean prob_bigmove: 0.173 (17.3%)
- Mean prob_long: 0.085 (8.5%)
- Mean prob_short: 0.088 (8.8%)
- Mean prob_neutral: 0.827 (82.7%)
- High confidence (>0.7): 90.8% of predictions

---

## Backtest Results (May 2024)

### Overall Performance

- **Total Trades:** 546
- **Total PnL:** **-$6.02** ❌ (breakeven, not profitable)
- **Win Rate:** **35.3%** ❌ (target: >42%)
- **Return:** -0.00%

### Exit Analysis

**Exit Reasons:**
- STOP: 342 (62.6%) - avg PnL: -$0.115
- TARGET: 176 (32.2%) - avg PnL: +$0.179
- EOD: 28 (5.1%) - avg PnL: +$0.066

**Target Hit Rate:**
- Actual: **34.0%** ❌ (target: >40%)
- Random walk: 38.5%
- **Worse than random** by 4.5 percentage points

### Performance by Side

**LONG:**
- Trades: 220
- Avg PnL: +$0.001
- Total PnL: +$0.13
- Win rate: 44.1% ✅
- Target rate: 41.4% ✅

**SHORT:**
- Trades: 326
- Avg PnL: -$0.019
- Total PnL: -$6.15 ❌
- Win rate: 29.4% ❌
- Target rate: 26.1% ❌

**Key Finding:** LONG side is profitable, SHORT side is losing money

### Duration

- Mean: 47.5 minutes
- Median: 15 minutes
- Max: 376 minutes (6.3 hours) ✅ (EOD close working)

### Risk Metrics

- Avg stop distance: $0.102 (0.33%)
- Avg target distance: $0.163 (0.52%)
- R-multiple: 1.60
- Profit factor: 0.850 ❌ (need >1.0)

### Commission Impact

- Total commission: $3.82
- Gross PnL: -$2.20
- Net PnL: -$6.02
- **Commission = 173.8% of gross PnL** ❌ (huge drag)

### Best/Worst Symbols

**Top 5:**
1. NEM: +$1.05 (26 trades)
2. DVN: +$0.45 (18 trades)
3. GM: +$0.31 (32 trades)
4. AES: +$0.30 (34 trades)
5. USB: +$0.18 (33 trades)

**Bottom 5:**
1. PLTR: -$1.39 (36 trades)
2. CMCSA: -$1.11 (18 trades)
3. PFE: -$0.92 (18 trades)
4. CCL: -$0.71 (29 trades)
5. CZR: -$0.70 (33 trades)

---

## Root Cause Analysis

### Why Not Profitable?

1. **Model Too Conservative**
   - Predicting 90.89% neutral vs target 60-70%
   - Only 9.11% directional signals
   - Missing profitable opportunities

2. **SHORT Side Underperforming**
   - SHORT win rate: 29.4% vs LONG: 44.1%
   - SHORT target rate: 26.1% vs LONG: 41.4%
   - SHORT losing -$6.15 while LONG making +$0.13

3. **Target Hit Rate Below Random**
   - 34.0% vs 38.5% expected from random walk
   - Model has **negative predictive power** for direction
   - Stage 2 (direction) model not working in practice

4. **Commission Drag**
   - $3.82 commission on -$2.20 gross PnL
   - 173.8% of gross PnL eaten by commissions
   - Need larger position sizes or fewer trades

5. **Feature Correlations Weak**
   - Stage 2 max correlation: 0.0752 (below 0.10 target)
   - Direction features not predictive enough
   - VWAP deviations alone insufficient

---

## Improvements from Baseline

### What Worked ✅

1. **Shorter Horizons** (15-30-45min vs 60-120min)
   - Better feature alignment
   - More realistic predictions

2. **Class Weights Enabled**
   - Long predictions: 1.0% → 5.02% (5x improvement)
   - Model learning minority classes

3. **Feature Logging**
   - Identified strong features (time, volatility, volume)
   - Identified weak features (VWAP z-scores)

4. **Fast Training**
   - 36 minutes vs 90+ minutes
   - Reused features, only recomputed labels

5. **Infrastructure**
   - Backtest engine working correctly
   - EOD close fixed
   - Stop/target monitoring accurate

### What Didn't Work ❌

1. **Direction Prediction**
   - Stage 2 model has weak features
   - Target rate worse than random
   - SHORT side particularly bad

2. **Prediction Distribution**
   - Still too conservative (90% neutral)
   - Need more aggressive thresholds

3. **Commission Impact**
   - Single-share trades too small
   - Need position sizing

---

## Recommendations

### Immediate Actions (High Priority)

1. **Fix SHORT Side**
   ```python
   # Option A: Train separate SHORT model
   # Option B: Disable SHORT trades temporarily
   # Option C: Investigate why SHORT underperforms
   ```

2. **Increase Position Size**
   ```yaml
   # Overcome commission drag
   order_qty: 10  # Was: 1
   # This would make PnL: -$60 but commission only $38
   ```

3. **Lower Probability Thresholds**
   ```yaml
   # Get more selective signals
   prob_threshold_long: 0.50   # Was: 0.62
   prob_threshold_short: 0.50  # Was: 0.62
   min_conviction_score: 0.01  # Was: 0.015
   ```

4. **Add Directional Features**
   ```yaml
   # Current features weak for direction
   # Add: momentum, trend, order flow, microstructure
   - f__momentum__roc_5
   - f__momentum__roc_10
   - f__trend__ema_cross
   - f__orderflow__imbalance
   ```

### Medium Priority

5. **Filter Losing Symbols**
   ```python
   # Blacklist: PLTR, CMCSA, PFE, CCL, CZR
   # Focus on: NEM, DVN, GM, AES, USB
   ```

6. **Widen Stops**
   ```yaml
   # Reduce stop-outs (62.6% of exits)
   max_atr_multiple: 1.5  # Was: 1.25
   support_buffer_atr: 0.20  # Was: 0.15
   ```

7. **Separate LONG/SHORT Models**
   ```python
   # Train dedicated models for each direction
   # LONG model working (44% win rate)
   # SHORT model broken (29% win rate)
   ```

### Low Priority

8. **Add More Training Data**
   - Extend to 12 months
   - More samples for minority classes

9. **Ensemble Models**
   - Combine multiple models
   - Vote on direction

10. **Alternative Approaches**
    - Rule-based system for direction
    - Technical indicators instead of ML
    - Simpler threshold-based signals

---

## Next Steps

### Option 1: Quick Fixes (Recommended)

```bash
# 1. Disable SHORT trades
# Edit policy config: only allow LONG

# 2. Increase position size
# Edit policy config: order_qty: 10

# 3. Lower thresholds
# Edit policy config: prob_threshold_long: 0.50

# 4. Rerun backtest
python scripts/run_backtest_1m.py
```

**Expected Result:** Positive PnL from LONG-only strategy

### Option 2: Retrain with Better Features

```bash
# 1. Add momentum/trend features
# Edit features_10m.yaml

# 2. Retrain models
python scripts/fast_retrain_with_new_labels.py

# 3. Validate
python scripts/validate_training_results.sh
```

**Expected Result:** Better direction prediction

### Option 3: Separate Models

```bash
# 1. Train LONG-only model
# 2. Train SHORT-only model
# 3. Use ensemble approach
```

**Expected Result:** Specialized models for each direction

---

## Files Generated

### Training Artifacts
- `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/training_data.parquet` (86MB)
- `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/model.pkl` (4.5MB)
- `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/bigmove_stage2_dir/model.pkl` (2.5MB)
- `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/feature_performance_summary.json`

### Predictions
- `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions_bigmove.parquet`

### Backtest Results
- `artefacts/extensions/intraday_ml/trade_report_may2024_1m.csv` (546 trades)

### Analysis Scripts
- `scripts/fast_retrain_with_new_labels.py`
- `scripts/generate_oos_predictions.py`
- `scripts/analyze_predictions.py`
- `scripts/analyze_backtest_results.py`

---

## Conclusion

**Status:** System is functional but not yet profitable

**Key Achievements:**
- ✅ Training pipeline working (36 min)
- ✅ Feature logging implemented
- ✅ Backtest engine accurate
- ✅ LONG side profitable (44% win rate)

**Key Issues:**
- ❌ SHORT side losing money (29% win rate)
- ❌ Target rate below random (34% vs 38.5%)
- ❌ Model too conservative (90% neutral)
- ❌ Commission drag (174% of gross PnL)

**Recommendation:** Implement Option 1 (LONG-only + larger positions) for immediate profitability, then work on Option 2 (better features) for long-term improvement.

**Next Session:** Test LONG-only strategy with increased position size.
