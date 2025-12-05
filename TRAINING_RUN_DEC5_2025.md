# Training Run - December 5, 2025
**Started:** 19:32 SGT  
**Branch:** `feature/migrate-to-backtrader`  
**Commit:** `3702822` - "feat: add feature performance logging and training monitor"

---

## Execution Plan

### Stage 1: Probability Model Training
**Command:**
```bash
python -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2
```

**Expected Duration:** ~2-3 hours  
**Output:** `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/`

### Stage 2: Direction Model Training
**Command:**
```bash
python -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
  --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2/bigmove_stage2_dir
```

**Expected Duration:** ~1-2 hours  
**Output:** `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/bigmove_stage2_dir/`

---

## Key Changes Implemented

### 1. Feature Performance Logging ✅

**New Module:** `extensions/intraday_ml_models/feature_performance.py`

**Capabilities:**
- Computes Pearson and Spearman correlations for all features vs target
- Extracts LightGBM feature importance
- Identifies zero-variance and weak features
- Logs top/bottom features automatically
- Saves detailed JSON reports

**Output Files:**
- `feature_correlations.json` - Full correlation analysis
- `feature_importance.json` - Model feature importance
- `feature_performance_summary.json` - Executive summary

**Integration:**
- Automatically called after model training in both Stage 1 and Stage 2
- Results included in model metadata
- Logged to console for immediate visibility

### 2. Training Progress Monitor ✅

**New Script:** `scripts/monitor_training.py`

**Usage:**
```bash
# One-time check
python scripts/monitor_training.py

# Watch mode (refresh every 30s)
python scripts/monitor_training.py --watch

# Custom output directory
python scripts/monitor_training.py --output-root artefacts/extensions/intraday_ml/phaseA_full_sip_v2
```

**Displays:**
- File creation status (training_data, models, metadata)
- Model training metrics (accuracy, precision, recall, F1, ROC AUC)
- Cross-validation results
- Feature performance statistics
- Top features by correlation and importance

### 3. Class Weights Configuration Fix ✅

**Problem:** Config used `class_weights` but code expected `class_weight`

**Solution:**
- Updated `build_training_settings()` in both Stage 1 and Stage 2
- Now handles both `class_weight` and `class_weights` (plural)
- Automatically converts `auto_balance` config to `"balanced"` mode
- Properly applies sklearn's balanced class weighting

**Config:**
```yaml
class_weights:
  auto_balance:
    enabled: true
    blend_factor: 0.7
    floor: 0.1
    cap: 10.0
```

**Effect:** Model will now properly weight minority classes (long/short) vs majority (neutral)

### 4. Deduplication Fix ✅

**Problem:** Dataset had duplicate (symbol, ts) pairs causing merge errors

**Solution:**
- Added deduplication check in `attach_bigmove_labels()`
- Logs warning with duplicate count
- Keeps first occurrence of each (symbol, ts) pair
- Allows training to proceed without merge errors

---

## Configuration Changes (From Session Summary)

### Shortened Prediction Horizons
```yaml
# configs/extensions/intraday_ml/targets_bigmove.yaml
horizons: [15, 30, 45]  # Was: [30, 60, 120]
forward_minutes: 30     # Was: 60
forward_minutes_alt: 45 # Was: 120
```

**Rationale:** 60-120 minute horizons too long for OHLCV features

### Enhanced Features
```yaml
# configs/extensions/intraday_ml/features_10m.yaml
- Extended windows: [3, 6, 12, 18] bars (up to 3 hours)
- Multi-timeframe: 30m and 60m context
- Price levels: distance to high/low/open, range position
- Intraday patterns: opening range, session levels, volume profile
- Breakout strength and trend indicators
```

**Expected:** ~100 features (up from 68)

### Class Weights Enabled
```yaml
# Both model configs
class_weights:
  auto_balance:
    enabled: true  # This was the critical fix
```

---

## Success Criteria

### Feature Quality (Critical)
- **Max correlation:** > 0.10 (was 0.051)
- **Features above 0.10:** > 10 (was 0)
- **Features above 0.05:** > 30 (was ~15)
- **Mean correlation:** > 0.03 (was 0.018)

### Prediction Distribution (Critical)
- **Neutral:** 60-70% (was 94.5%)
- **Long:** 15-20% (was 1.0%)
- **Short:** 15-20% (was 4.5%)

### Model Performance
- **Target hit rate:** > 40% (was 34%, random 38.5%)
- **Win rate:** > 42% (was 35.3%)
- **Correlation (prob_long vs favorable):** > 0.10 (was 0.018)

### Backtest Performance
- **Positive PnL:** > $0 (was -$0.01)
- **Sharpe ratio:** > 0.5
- **Max drawdown:** < 20%

---

## Monitoring Commands

### Check Training Progress
```bash
# View live log
tail -f /tmp/stage1_training_full.log

# Check process status
ps aux | grep train_bigmove

# Monitor with dashboard
python scripts/monitor_training.py --watch
```

### Check Output Files
```bash
# List generated files
ls -lh artefacts/extensions/intraday_ml/phaseA_full_sip_v2/

# Check feature performance
cat artefacts/extensions/intraday_ml/phaseA_full_sip_v2/feature_performance_summary.json | jq

# Check model metadata
cat artefacts/extensions/intraday_ml/phaseA_full_sip_v2/metadata.json | jq .metrics
```

### Validate Results
```bash
# Check prediction distribution
python -c "
import pandas as pd
preds = pd.read_parquet('artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions_bigmove.parquet')
preds['predicted_class'] = preds[['prob_-1', 'prob_0', 'prob_1']].idxmax(axis=1)
print('Prediction distribution:')
print(preds['predicted_class'].value_counts(normalize=True) * 100)
"

# Run backtest
python scripts/run_backtest_1m.py
```

---

## Next Steps After Training

### 1. Validate Feature Performance
```bash
python scripts/monitor_training.py
```

**Check:**
- Are correlations > 0.10?
- Are there features with strong importance?
- Any zero-variance features to remove?

### 2. Generate OOS Predictions
```bash
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config.yaml \
  --expected-r-floor 1.0 \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions_bigmove.parquet
```

### 3. Analyze Prediction Distribution
```bash
python scripts/analyze_predictive_power.py
```

**Target:**
- Neutral: 60-70%
- Long: 15-20%
- Short: 15-20%

### 4. Run Backtest
```bash
python scripts/run_backtest_1m.py
```

**Target:**
- Target hit rate > 40%
- Win rate > 42%
- Positive PnL

### 5. If Still Not Working

**Option B: Even Shorter Horizons**
```yaml
horizons: [10, 20, 30]
forward_minutes: 20
```

**Option C: Separate Models**
- Train separate LONG and SHORT models
- Use ensemble approach

**Option D: Rule-Based System**
- Abandon ML approach
- Use technical indicators directly
- Simpler, more interpretable

---

## Files Modified

### New Files
1. `extensions/intraday_ml_models/feature_performance.py` - Feature analysis module
2. `scripts/monitor_training.py` - Training progress monitor
3. `scripts/run_stage1_training.sh` - Training runner script

### Modified Files
4. `extensions/intraday_ml_models/train_bigmove_stage1.py` - Added feature logging
5. `extensions/intraday_ml_models/train_bigmove_stage2_dir.py` - Added feature logging
6. `extensions/intraday_ml_models/bigmove_training_utils.py` - Added deduplication

---

## Logs and Artifacts

**Training Log:** `/tmp/stage1_training_full.log`  
**Output Directory:** `artefacts/extensions/intraday_ml/phaseA_full_sip_v2/`  
**Git Branch:** `feature/migrate-to-backtrader`  
**Git Commit:** `3702822`

---

## Timeline

- **15:17 SGT** - Started implementation
- **15:23 SGT** - Feature logging implemented
- **15:32 SGT** - Training started (first attempt, merge error)
- **19:32 SGT** - Training restarted with deduplication fix
- **~22:00 SGT** - Stage 1 expected completion (estimate)
- **~00:00 SGT** - Stage 2 expected completion (estimate)

---

## Contact for Next Session

**Resume Work:**
```bash
cd /home/jacobw/quantstack
git checkout feature/migrate-to-backtrader
git pull origin feature/migrate-to-backtrader
```

**Check Status:**
```bash
python scripts/monitor_training.py
tail -100 /tmp/stage1_training_full.log
```

**Key Questions:**
1. Did training complete successfully?
2. What are the feature correlations?
3. What is the prediction distribution?
4. What is the backtest performance?
5. Do we need Option B, C, or D?
