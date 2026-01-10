# Session Summary - December 5, 2025
**Duration:** ~6 hours  
**Branch:** `feature/migrate-to-backtrader`  
**Status:** Ready for model retraining (Option A)

---

## Executive Summary

**Completed:**
1. ✅ Migrated from broken custom backtest engine to Backtrader
2. ✅ Fixed EOD close (max 376m vs 4400m before)
3. ✅ Implemented 1-minute execution with proper stop/target monitoring
4. ✅ Diagnosed root cause: ML model has zero predictive power
5. ✅ Identified fixes: Class weights config + weak features + long horizon
6. ✅ Updated all configurations for retraining

**Next Step:** Retrain models with Option A (new output directory)

---

## Key Findings

### 1. Backtest Engine Fixed ✅

**Problem:** Custom engine didn't monitor stops/targets
- Bracket orders don't work with 10-minute bars
- 64% of trades had zero price movement
- All exits via timeout or EOD

**Solution:** 
- Implemented OHLC-based stop/target checking
- Migrated to 1-minute execution data
- Fixed EOD close at 15:55 ET

**Results:**
- Max duration: 376m (6.3h) vs 4400m (73h) before ✅
- Target hits: 176 (32.2%) vs 2 (0.4%) before ✅
- Proper price movements ✅

### 2. ML Model Has Zero Predictive Power ❌

**Evidence:**
- prob_long correlation with favorable movement: **+0.018** (zero)
- prob_short correlation: **-0.021** (zero)
- Target hit rate: **34.0%** vs 38.5% expected (worse than random)
- Model predicts **94.5% neutral** (learned class imbalance)

**Root Causes:**
1. **Config bug:** `class_weight: balanced` but code expects `class_weights` (plural)
2. **Weak features:** Best correlation 0.051 (should be 0.10-0.30)
3. **Horizon too long:** 60-120 minutes too hard to predict with OHLCV

### 3. Class Imbalance is ACCEPTABLE ✅

**Training data:**
- Neutral: 86.4% (121,505 samples)
- Long: 7.6% (10,650 samples)
- Short: 6.0% (8,487 samples)

**This is expected and correct** for 3-5 trades/day target.

**Issue:** Model not learning minority class due to:
- Config bug (class weights not applied)
- Weak features (can't distinguish patterns)

---

## Changes Made

### 1. Backtrader Integration

**Files Created:**
- `extensions/intraday_ml/backtest_bt_1m.py` - 1-minute execution engine
- `extensions/intraday_ml/backtest_bt_ohlc.py` - OHLC monitoring (10m bars)
- `extensions/intraday_ml/backtest_bt_detailed.py` - Detailed trade logging
- `scripts/run_backtest_1m.py` - 1-minute backtest runner
- `scripts/test_backtrader.py` - Quick validation test

**Results (May 2024, 1m execution):**
```
Trades:       546
Win Rate:     35.3%
Total PnL:    -$6.02 (breakeven)
Max Duration: 376m (6.3h) ✅

Exit Reasons:
- STOP:   342 (62.6%)
- TARGET: 176 (32.2%)
- EOD:    28 (5.1%)
```

### 2. Configuration Updates

**A. Shortened Prediction Horizon**
```yaml
# configs/extensions/intraday_ml/targets_bigmove.yaml
horizons: [15, 30, 45]  # Changed from [30, 60, 120]
forward_minutes: 30     # Changed from 60
forward_minutes_alt: 45 # Changed from 120
```

**B. Enhanced Features (OHLCV-only)**
```yaml
# configs/extensions/intraday_ml/features_10m.yaml
- Extended windows: [3, 6, 12, 18] bars (up to 3 hours)
- Multi-timeframe: 30m and 60m context
- Price levels: distance to high/low/open, range position
- Intraday patterns: opening range, session levels, volume profile
- Breakout strength and trend indicators
```

**C. Fixed Class Weights**
```yaml
# configs/extensions/intraday_ml/model_bigmove_stage1.yaml
# configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml
class_weights:  # Changed from class_weight
  auto_balance:
    enabled: true
    blend_factor: 0.7
    floor: 0.1
    cap: 10.0
```

### 3. Analysis Scripts

**Created:**
- `scripts/analyze_predictive_power.py` - Feature correlation analysis
- `scripts/analyze_stop_target_rates.py` - Performance vs random walk
- `scripts/generate_trade_report.py` - Detailed trade logging

**Documentation:**
- `DIAGNOSIS_AND_FIX.md` - Complete root cause analysis
- `FEATURE_EVALUATION.md` - Feature set assessment
- `MAY2024_ANALYSIS.md` - OOS validation results
- `BACKTRADER_MIGRATION.md` - Migration documentation

---

## Next Steps - Option A (Recommended)

### Command to Run

```bash
# Stage 1: Train bigmove probability model (~3 hours)
python -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2

# Stage 2: Train direction classifier (~2 hours)
python -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
  --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2/bigmove_stage2_dir

# Total time: ~5 hours
```

### What Will Happen

1. **Feature generation** (~2-3 hours)
   - New features with extended windows
   - Multi-timeframe context (30m, 60m)
   - Price levels and intraday patterns
   - Saved to: `phaseA_full_sip_v2/oos_features.parquet`

2. **Label generation** (~30 min)
   - New horizons: 15, 30, 45 minutes
   - Saved to: `phaseA_full_sip_v2/training_data.parquet`

3. **Stage 1 training** (~30 min)
   - With class_weights properly applied
   - Saved to: `phaseA_full_sip_v2/bigmove_stage1/`

4. **Stage 2 training** (~30 min)
   - With class_weights properly applied
   - Saved to: `phaseA_full_sip_v2/bigmove_stage2_dir/`

### Validation After Training

```bash
# Generate new predictions
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
  --expected-r-floor 1.0 \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions_bigmove.parquet

# Check prediction distribution
python -c "
import pandas as pd
preds = pd.read_parquet('artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions_bigmove.parquet')
preds['predicted_class'] = preds[['prob_-1', 'prob_0', 'prob_1']].idxmax(axis=1)
print('Prediction distribution:')
print(preds['predicted_class'].value_counts(normalize=True) * 100)
print('\nTarget: Neutral 60-70%, Long 15-20%, Short 15-20%')
"

# Run backtest
python scripts/run_backtest_1m.py
```

### Success Criteria

**Predictions:**
- Neutral: 60-70% (down from 94.5%)
- Long: 15-20% (up from 1.0%)
- Short: 15-20% (up from 4.5%)

**Feature Correlation:**
- Best feature: > 0.10 (up from 0.051)
- prob_long vs favorable movement: > 0.10 (up from 0.018)

**Backtest Performance:**
- Target hit rate: > 40% (up from 34%, vs 38.5% random)
- Win rate: > 42% (up from 35.3%)
- Positive PnL

---

## Current System State

### Data Periods (Confirmed)
- **Training:** Oct 2023 - Apr 15, 2024 (134 days)
- **Validation:** Apr 16-30, 2024
- **OOS:** May 1-31, 2024 (22 days)

### Existing Artifacts (Old Config)
```
artefacts/extensions/intraday_ml/phaseA_full_sip/
├── training_data.parquet (81.8 MB) - OLD (60-120min horizon)
├── oos_features.parquet (10.3 MB) - OLD (68 features)
├── oos_predictions_bigmove.parquet (2.1 MB) - OLD (zero predictive power)
└── trade_report_may2024_1m.csv - Backtest results
```

### New Artifacts (Will Be Created)
```
artefacts/extensions/intraday_ml/phaseA_full_sip_v2/
├── training_data.parquet - NEW (15-30-45min horizon)
├── oos_features.parquet - NEW (~100 features with multi-timeframe)
├── bigmove_stage1/ - NEW (with class_weights)
├── bigmove_stage2_dir/ - NEW (with class_weights)
└── oos_predictions_bigmove.parquet - NEW (hopefully predictive!)
```

---

## Risk Management (Validated)

**Stop/Target Logic:** ✅ Working correctly
- ATR-based: 0.69x ATR average (range 0.17x to 1.25x)
- Support/resistance: Uses risk_reference_level
- Stop distance: Median $0.084 (0.29% of price)
- R-multiple: 1.6 (target = 1.6x stop)

**Execution:** ✅ Working correctly
- 1-minute bars from `~/gcs-mount/gold/stocks/1m/`
- EOD close at 15:55 ET
- Proper stop/target monitoring

---

## Performance Comparison

### Before (Broken Engine)
```
Win Rate:     0.3%
Avg PnL:      -$0.70
Exit:         94% timeout
Max Duration: 4400m (73 hours)
```

### After (Backtrader, Old Model)
```
Win Rate:     35.3%
Avg PnL:      -$0.01
Exit:         62.6% stop, 32.2% target, 5.1% EOD
Max Duration: 376m (6.3 hours) ✅
```

### Expected (After Retraining)
```
Win Rate:     42-48%
Avg PnL:      +$0.05 to +$0.15
Target Rate:  40-45% (vs 38.5% random)
Correlation:  0.10-0.15 (vs 0.02 current)
```

---

## Files Modified

### Configurations
1. `configs/extensions/intraday_ml/targets_bigmove.yaml` - Shortened horizons
2. `configs/extensions/intraday_ml/features_10m.yaml` - Enhanced features
3. `configs/extensions/intraday_ml/model_bigmove_stage1.yaml` - Fixed class_weights
4. `configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml` - Fixed class_weights

### Code
5. `extensions/intraday_ml/backtest_bt_1m.py` - 1-minute execution engine
6. `extensions/intraday_ml/backtest_bt_ohlc.py` - OHLC monitoring
7. `scripts/run_backtest_1m.py` - Backtest runner
8. `scripts/analyze_predictive_power.py` - Analysis tools

### Documentation
9. `DIAGNOSIS_AND_FIX.md` - Root cause analysis
10. `FEATURE_EVALUATION.md` - Feature assessment
11. `MAY2024_ANALYSIS.md` - OOS validation
12. `BACKTRADER_MIGRATION.md` - Migration guide

---

## Git Status

**Branch:** `feature/migrate-to-backtrader`  
**Last Commit:** `65268bd` - "feat: enhance features and shorten prediction horizon"  
**Status:** All changes committed and pushed

**To resume:**
```bash
cd /home/jacobw/quantstack
git checkout feature/migrate-to-backtrader
git pull origin feature/migrate-to-backtrader
```

---

## Key Learnings

1. **Class imbalance is acceptable** for low-frequency trading (3-5 trades/day)
2. **Config naming matters** - `class_weight` vs `class_weights` broke everything
3. **Feature strength is critical** - 0.05 correlation is too weak
4. **Prediction horizon matters** - 60-120min too long for OHLCV features
5. **Always validate predictions** before running full backtest
6. **1-minute execution** essential for proper stop/target monitoring

---

## Questions for Next Session

1. Did Stage 1 training complete successfully?
2. What is the new prediction distribution? (Target: 60-70% neutral)
3. What is the new feature correlation? (Target: > 0.10)
4. What is the backtest performance? (Target: > 40% target rate)
5. If still not working, consider:
   - Even shorter horizon (10-20 minutes)
   - Separate LONG/SHORT models
   - Rule-based system instead of ML

---

## Contact Information

**Session Date:** December 5, 2025  
**Working Directory:** `/home/jacobw/quantstack`  
**Data Location:** `~/gcs-mount/gold/stocks/1m/`  
**Branch:** `feature/migrate-to-backtrader`

---

## Quick Reference Commands

```bash
# Resume work
cd /home/jacobw/quantstack
git checkout feature/migrate-to-backtrader

# Start training (Option A)
python -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2

# Check progress
ls -lh artefacts/extensions/intraday_ml/phaseA_full_sip_v2/

# Validate predictions
python scripts/analyze_predictive_power.py

# Run backtest
python scripts/run_backtest_1m.py
```

---

**Status:** Ready to proceed with Option A retraining (~5 hours)
