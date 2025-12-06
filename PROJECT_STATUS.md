# Project Status - SMB Universe Expansion

**Date**: 2025-12-06 14:02 SGT  
**Project**: v4 Implementation - SMB Capital-Inspired Universe Expansion  
**Goal**: Improve from 42% → 55%+ win rate via catalyst-driven stock selection

---

## Quick Start (Resume Session)

### Check Current Status
```bash
# 1. Check if feature store build is complete
ls -lh run/daily_features/features.parquet

# 2. If complete, run SIP selection
python scripts/generate_smb_sip_from_features_no_pm.py

# 3. Check SIP output
python -c "
import pandas as pd
df = pd.read_parquet('run/sip_membership_smb_1month/sip_membership.parquet')
print(f'SIP rows: {len(df)}, symbols: {df[\"symbol\"].nunique()}, dates: {df[\"date\"].nunique()}')
"

# 4. If SIP looks good, proceed to training
python scripts/generate_training_data_subset.py
```

### Monitor Background Processes
```bash
# Check parallel feature store build
tail -f /tmp/build_features_parallel.log

# Check if process is running
ps aux | grep "build_daily_feature_store_parallel" | grep python
```

---

## Current State (2025-12-06 14:02 SGT)

### Active Processes
1. **Parallel Feature Store Build**
   - Script: `scripts/build_daily_feature_store_parallel.py`
   - Started: 13:56 SGT
   - Workers: 8 parallel processes
   - Status: RUNNING
   - ETA: ~17:00 SGT (3-4 hours total)
   - Output: `run/daily_features/features.parquet`
   - Log: `/tmp/build_features_parallel.log`

### Completed Today
- ✅ Created SMB scanner (`smb_scanner_monthly.py`)
- ✅ Discovered gold data has no premarket bars
- ✅ Modified SMB filters to use gap + ATR + ADV only
- ✅ Validated feature store approach (10-symbol test)
- ✅ Created parallel feature store builder
- ✅ Created all training/backtest scripts
- ✅ Updated documentation

### Blocked/Waiting
- ⏸️ SIP selection - Waiting for feature store
- ⏸️ Training data generation - Waiting for SIP
- ⏸️ Model training - Waiting for training data
- ⏸️ Backtesting - Waiting for models

---

## Workflow (Step-by-Step)

### Phase 1: Feature Store (IN PROGRESS)
**Status**: ⏳ RUNNING (ETA 17:00 SGT)

```bash
# Already running in background
# Monitor: tail -f /tmp/build_features_parallel.log
```

**Output**: `run/daily_features/features.parquet` (1,108 symbols × 22 days = ~24,000 rows)

---

### Phase 2: SIP Selection (NEXT)
**Status**: ⏸️ WAITING FOR PHASE 1  
**Duration**: < 1 minute

```bash
# Run after feature store completes
python scripts/generate_smb_sip_from_features_no_pm.py
```

**Output**: `run/sip_membership_smb_1month/sip_membership.parquet` (~20 stocks × 22 days = ~440 rows)

**Validation**:
```bash
python -c "
import pandas as pd
df = pd.read_parquet('run/sip_membership_smb_1month/sip_membership.parquet')
print('Total rows:', len(df))
print('Unique symbols:', df['symbol'].nunique())
print('Unique dates:', df['date'].nunique())
print('Avg stocks/day:', len(df) / df['date'].nunique())
print('\nTop 5 symbols:')
print(df['symbol'].value_counts().head())
"
```

**Expected**:
- Total rows: 400-500
- Unique symbols: 100-200
- Avg stocks/day: 15-25
- Top symbols should vary (not dominated by 1-2 stocks)

---

### Phase 3: Training Data Generation
**Status**: ⏸️ WAITING FOR PHASE 2  
**Duration**: 30-60 minutes

```bash
# Run after SIP selection completes
python scripts/generate_training_data_subset.py
```

**Output**: `artefacts/extensions/intraday_ml/phaseA_100_subset_v4/training_data.parquet`

**Validation**:
```bash
python -c "
import pandas as pd
df = pd.read_parquet('artefacts/extensions/intraday_ml/phaseA_100_subset_v4/training_data.parquet')
print('Total rows:', len(df))
print('Unique symbols:', df['symbol'].nunique())
print('Label distribution:')
print(df['label'].value_counts())
"
```

**Expected**:
- Total rows: 50,000-100,000
- Unique symbols: 100
- Labels: Balanced LONG/SHORT/NEUTRAL

---

### Phase 4: Model Training
**Status**: ⏸️ WAITING FOR PHASE 3  
**Duration**: 15 minutes

```bash
# Run after training data generation completes
python scripts/train_v4_subset.py
```

**Output**: 
- `models/v4_subset_long.txt`
- `models/v4_subset_short.txt`

**Validation**:
```bash
ls -lh models/v4_subset_*.txt
# Should see two model files, each ~1-5 MB
```

**Expected Metrics**:
- LONG ROC AUC: ≥ 0.95
- SHORT ROC AUC: ≥ 0.95

---

### Phase 5: Prediction Generation
**Status**: ⏸️ WAITING FOR PHASE 4  
**Duration**: 10 minutes

```bash
# Run after model training completes
python scripts/generate_v4_predictions.py
```

**Output**: `run/predictions_v4_subset.parquet`

**Validation**:
```bash
python -c "
import pandas as pd
df = pd.read_parquet('run/predictions_v4_subset.parquet')
print('Total predictions:', len(df))
print('Prediction distribution:')
print(df['prediction'].value_counts())
print('Avg prob:', df['prob'].mean())
"
```

**Expected**:
- Neutral: 95%+
- LONG: 2-3%
- SHORT: 2-3%
- Avg prob: 0.50-0.60

---

### Phase 6: Backtesting
**Status**: ⏸️ WAITING FOR PHASE 5  
**Duration**: 15 minutes

```bash
# Run after prediction generation completes
python scripts/backtest_v4_smb.py
```

**Output**: `run/backtest_v4_subset_results.txt`

**Validation**:
```bash
cat run/backtest_v4_subset_results.txt
```

**Expected Metrics**:
- Total trades: 60-100
- Win rate: 55%+
- Avg R-multiple: 2.5+
- Monthly PnL: $150+ (at 1-share scale)

---

### Phase 7: Performance Comparison
**Status**: ⏸️ WAITING FOR PHASE 6  
**Duration**: 5 minutes

```bash
# Run after backtesting completes
python scripts/compare_v3_v4.py
```

**Output**: `run/v3_v4_comparison.txt`

**Expected Improvements**:
- Trades/day: 2.1 → 4.0 (+90%)
- Win rate: 42.3% → 55%+ (+30%)
- Monthly PnL: $18.94 → $150+ (+692%)

---

## Decision Points

### After Phase 2 (SIP Selection)
**Question**: Does SIP selection look reasonable?

**Check**:
- Are 15-25 stocks selected per day?
- Is symbol distribution diverse (not dominated by 1-2 stocks)?
- Do selected stocks have meaningful gaps/volatility?

**If NO**: Adjust SMB filter thresholds in `scripts/generate_smb_sip_from_features_no_pm.py`
- Lower `min_gap_pct` (e.g., 0.015 = 1.5%)
- Lower `min_atr` (e.g., 1.5)
- Lower `min_adv` (e.g., 5M)

**If YES**: Proceed to Phase 3

---

### After Phase 6 (Backtesting)
**Question**: Does v4 outperform v3?

**Check**:
- Win rate ≥ 55%?
- Trades ≥ 3/day?
- Monthly PnL ≥ $150?

**If NO**: 
- Option A: Adjust ML threshold (lower prob_threshold to 0.70)
- Option B: Adjust risk parameters (wider stops, tighter targets)
- Option C: Retrain on full 1,108 symbols (not just 100)

**If YES**: 
- Scale to full 1,108-symbol universe
- Run full backtest on multi-year period
- Deploy to paper trading

---

## Troubleshooting

### Feature Store Build Fails
```bash
# Check log for errors
tail -100 /tmp/build_features_parallel.log

# Check if workers are running
ps aux | grep "build_daily_feature_store_parallel" | grep python

# If stuck, kill and restart
pkill -f "build_daily_feature_store_parallel"
python scripts/build_daily_feature_store_parallel.py > /tmp/build_features_parallel.log 2>&1 &
```

### SIP Selection Returns 0 Rows
```bash
# Check feature store data
python -c "
import pandas as pd
df = pd.read_parquet('run/daily_features/features.parquet')
print('Gap range:', df['gap_pct'].min(), 'to', df['gap_pct'].max())
print('ATR range:', df['atr14'].min(), 'to', df['atr14'].max())
print('ADV range:', df['adv20'].min(), 'to', df['adv20'].max())
"

# Lower thresholds if needed
# Edit: scripts/generate_smb_sip_from_features_no_pm.py
```

### Training Data Generation Fails
```bash
# Check if SIP file exists
ls -lh run/sip_membership_smb_1month/sip_membership.parquet

# Check SIP data
python -c "
import pandas as pd
df = pd.read_parquet('run/sip_membership_smb_1month/sip_membership.parquet')
print(df.head())
"

# Run with verbose logging
python scripts/generate_training_data_subset.py 2>&1 | tee /tmp/training_gen.log
```

### Model Training Fails
```bash
# Check training data
python -c "
import pandas as pd
df = pd.read_parquet('artefacts/extensions/intraday_ml/phaseA_100_subset_v4/training_data.parquet')
print('Rows:', len(df))
print('Columns:', df.columns.tolist())
print('Labels:', df['label'].value_counts())
"

# Check for missing features
# Edit: scripts/train_v4_subset.py
```

---

## Files to Monitor

### Logs
- `/tmp/build_features_parallel.log` - Feature store build progress
- `/tmp/training_gen.log` - Training data generation (if created)

### Outputs
- `run/daily_features/features.parquet` - Feature store
- `run/sip_membership_smb_1month/sip_membership.parquet` - SIP selection
- `artefacts/extensions/intraday_ml/phaseA_100_subset_v4/training_data.parquet` - Training data
- `models/v4_subset_*.txt` - Trained models
- `run/predictions_v4_subset.parquet` - Predictions
- `run/backtest_v4_subset_results.txt` - Backtest results

### Documentation
- `SYSTEM_OVERVIEW.md` - Technical system documentation
- `PROJECT_STATUS.md` - This file (project management)
- `SMB_STATUS.md` - Current status summary
- `NEXT_SESSION_PLAN.md` - Original implementation plan

---

## Next Session Checklist

1. ☐ Check if feature store build completed
2. ☐ Run SIP selection
3. ☐ Validate SIP output (15-25 stocks/day)
4. ☐ Generate training data
5. ☐ Train v4 models
6. ☐ Generate predictions
7. ☐ Run backtest
8. ☐ Compare v3 vs v4
9. ☐ Decide: scale to full 1,108 symbols or iterate

---

## Contact Points

**Current Session**: 2025-12-06 (Session 2)  
**Previous Session**: 2025-12-05 (Session 1 - SMB analysis, v3 models)  
**Next Session**: TBD (Continue from current phase)

**Key Decisions Made**:
- Selected Option 2: 100-symbol subset test
- Modified SMB filters: no PM RVOL (gold data limitation)
- Using parallel processing for feature store (8 workers)

**Key Discoveries**:
- Gold data has no premarket bars
- Feature store approach is 500x faster than daily scanning
- Parallel processing reduces build time from 27h → 3-4h
