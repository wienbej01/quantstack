# System Diagnosis and Fix - December 5, 2025

## Executive Summary

**ROOT CAUSE IDENTIFIED:** ML model has zero predictive power due to extreme class imbalance (86.4% neutral labels) and **class weighting not being applied**.

---

## Problem Statement

- **Win rate:** 35.3% (worse than random 38.5%)
- **Target hit rate:** 34.0% vs 38.5% expected
- **ML predictions:** Zero correlation with outcomes (+0.018 for LONG, -0.021 for SHORT)
- **System performance:** Breakeven (-$6.02 on 546 trades)

---

## Root Cause Analysis

### 1. Extreme Class Imbalance

**Training Data:**
```
Neutral (0): 121,505 samples (86.4%)
Long (1):     10,650 samples (7.6%)
Short (-1):    8,487 samples (6.0%)
```

**14:1 imbalance ratio**

### 2. Model Learned Imbalance, Not Patterns

**OOS Predictions:**
```
Predicted Neutral: 94.5%
Predicted Long:     1.0%
Predicted Short:    4.5%
```

**Model behavior:**
- 88.5% of predictions have prob_neutral > 0.5
- 61.4% have prob_neutral > 0.7
- Model is essentially predicting "no big move" always

### 3. Config Mismatch - Class Weights Not Applied

**Config says:**
```yaml
# model_bigmove_stage1.yaml
training:
  class_weight: balanced
```

**But code expects:**
```python
# train_lgbm.py line 266
class_weights_cfg = model_config.get("class_weights", {})  # Note: plural
```

**Result:** Class balancing is NOT being applied during training!

### 4. Predictive Power Analysis

**Correlation with favorable price movement:**
- LONG: prob_long → +0.018 (zero)
- SHORT: prob_short → -0.021 (zero)

**By probability quintile (LONG):**
```
Q1 (lowest):  47.7% target rate ← BEST
Q2:           49.5% target rate
Q3:           28.9% target rate ← WORST
Q4:           32.3% target rate
Q5 (highest): 34.3% target rate
```

**Conclusion:** Model has no signal, just noise.

---

## The Fix

### Immediate: Correct Class Weight Configuration

**Change model configs:**

```yaml
# configs/extensions/intraday_ml/model_bigmove_stage1.yaml
training:
  n_folds: 5
  seed: 37
  decision_threshold: 0.5

class_weights:  # Changed from class_weight
  auto_balance:
    enabled: true
    blend_factor: 0.7
    floor: 0.1
    cap: 10.0
```

```yaml
# configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml
training:
  n_folds: 4
  seed: 41
  decision_threshold: 0.5

class_weights:  # Changed from class_weight
  auto_balance:
    enabled: true
    blend_factor: 0.7
    floor: 0.1
    cap: 10.0
```

### Alternative: Manual Class Weights

```yaml
class_weights:
  base:
    -1: 10.0  # SHORT (6.0% of data)
    0: 1.0    # NEUTRAL (86.4% of data)
    1: 10.0   # LONG (7.6% of data)
```

### Additional Improvements

**1. Increase ATR Multiplier (Get More Directional Labels)**

```yaml
# configs/extensions/intraday_ml/targets_bigmove.yaml
atr_multiplier: 1.50  # Increase from 1.10
atr_multiplier_long: 1.60  # Increase from 1.15
atr_multiplier_short: 1.70  # Increase from 1.20
```

**Goal:** Reduce neutral labels from 86% to ~70%

**2. Use Focal Loss**

```yaml
# In model config
loss_tuning:
  focal_loss:
    enabled: true
    gamma: 2.0
    alpha: 0.25
```

**3. Undersample Neutral Class**

Add to training pipeline:
```python
# Keep all directional labels, sample 30% of neutral
neutral_mask = labels == 0
directional_mask = labels != 0

neutral_sample = features[neutral_mask].sample(frac=0.3, random_state=42)
directional_all = features[directional_mask]

balanced_features = pd.concat([neutral_sample, directional_all])
```

---

## Validation Plan

### Step 1: Retrain with Class Weights

```bash
# Update configs
vim configs/extensions/intraday_ml/model_bigmove_stage1.yaml
vim configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml

# Retrain Stage 1
python -m extensions.intraday_ml_models.train_bigmove_stage1 \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
  --output-root artefacts/extensions/intraday_ml/bigmove_stage1_balanced

# Retrain Stage 2
python -m extensions.intraday_ml_models.train_bigmove_stage2_dir \
  --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
  --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
  --model-config configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml \
  --output-root artefacts/extensions/intraday_ml/bigmove_stage2_dir_balanced
```

### Step 2: Generate New Predictions

```bash
python -m extensions.intraday_ml.experiments.score_bigmove_oos \
  --features artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet \
  --baseline-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet \
  --models-config configs/extensions/intraday_ml/bigmove_models_config_balanced.yaml \
  --expected-r-floor 1.0 \
  --output-signals artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove_balanced.parquet
```

### Step 3: Validate Predictions

Check if class distribution improved:
```python
predictions = pd.read_parquet('oos_predictions_bigmove_balanced.parquet')
predictions['predicted_class'] = predictions[['prob_-1', 'prob_0', 'prob_1']].idxmax(axis=1)
print(predictions['predicted_class'].value_counts(normalize=True))

# Target: 
# Neutral: 60-70% (down from 94.5%)
# Long: 15-20% (up from 1.0%)
# Short: 15-20% (up from 4.5%)
```

### Step 4: Run Backtest

```bash
python scripts/run_backtest_1m.py
```

**Success Criteria:**
- prob_long correlation with favorable movement > 0.10
- prob_short correlation with favorable movement > 0.10
- Target hit rate > 40% (vs 38.5% random)
- Win rate > 42%

---

## Expected Improvements

### Before (Current)
```
Predicted Neutral: 94.5%
Predicted Long: 1.0%
Predicted Short: 4.5%

Correlation: ~0.02 (zero)
Target hit rate: 34.0% (worse than random)
Win rate: 35.3%
```

### After (With Class Weights)
```
Predicted Neutral: 60-70%
Predicted Long: 15-20%
Predicted Short: 15-20%

Correlation: 0.10-0.15 (positive signal)
Target hit rate: 40-45% (better than random)
Win rate: 42-48%
```

---

## Timeline

**Immediate (1-2 hours):**
1. Update model configs with correct class_weights syntax
2. Retrain Stage 1 model (~30 min)
3. Retrain Stage 2 model (~30 min)

**Validation (1 hour):**
4. Generate new OOS predictions
5. Check prediction distribution
6. Validate correlations

**Testing (1 hour):**
7. Run backtest on May 2024
8. Analyze results
9. Compare to baseline

**Total: 3-4 hours to validated fix**

---

## Alternative: If Retraining Doesn't Work

### Option A: Simpler Model
- Use only technical indicators (RSI, MACD, Bollinger Bands)
- No ML, just rules
- Faster to implement and validate

### Option B: Different Horizon
- Current: 60-120 minute prediction
- Try: 15-30 minute prediction (easier to predict)

### Option C: Ensemble
- Train separate models for LONG and SHORT
- Binary classification instead of 3-class
- Better class balance (50/50 instead of 86/7/6)

---

## Key Learnings

1. **Always check class distribution** before training
2. **Validate config parameters** are actually used
3. **Test predictions** before running full backtest
4. **Class imbalance** can completely destroy model performance
5. **Config naming matters** (class_weight vs class_weights)

---

## Files to Modify

1. `configs/extensions/intraday_ml/model_bigmove_stage1.yaml`
2. `configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml`
3. (Optional) `configs/extensions/intraday_ml/targets_bigmove.yaml`

---

## Status

- [x] Root cause identified
- [x] Fix documented
- [ ] Configs updated
- [ ] Models retrained
- [ ] Predictions validated
- [ ] Backtest run
- [ ] Results analyzed

**Next Action:** Update configs and retrain models
