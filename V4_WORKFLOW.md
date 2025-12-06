# v4 SMB Implementation Workflow

**Started**: 2025-12-06 11:03 SGT  
**Approach**: Option 2 - 100-Symbol Subset Test  
**Estimated Time**: 2 hours total

---

## Current Status

### ✅ Step 1: Generate Training Data (IN PROGRESS)
**Command**: `python scripts/generate_training_data_subset.py`  
**Status**: RUNNING (started 11:03 SGT)  
**Duration**: 30-60 minutes  
**Output**: `artefacts/extensions/intraday_ml/v4_subset_100/training_data.parquet`

**Monitor**:
```bash
./scripts/check_v4_progress.sh
tail -f /tmp/v4_data_gen.log
```

---

## Next Steps (Execute When Step 1 Completes)

### Step 2: Train v4 Models (30 min)
```bash
python scripts/train_v4_subset.py
```

**Output**:
- `artefacts/extensions/intraday_ml/v4_subset_100/model_long/model.txt`
- `artefacts/extensions/intraday_ml/v4_subset_100/model_short/model.txt`

**Expected**:
- ROC AUC ≥ 0.95 (maintain quality)
- Volume momentum feature importance > 0.20

---

### Step 3: Generate Predictions (5 min)
```bash
python scripts/generate_v4_predictions_subset.py
```

**Filters**:
- Probability ≥ 0.75 (high confidence)
- Volume momentum ≥ 0.15

**Expected Distribution**:
- NEUTRAL: ~95%
- LONG: ~2-3%
- SHORT: ~2-3%

---

### Step 4: Backtest v4 Strategy (10 min)
```bash
python scripts/backtest_v4_subset.py
```

**Parameters**:
- Risk: 2% per trade
- Target: 2.5 ATR
- Stop: 1.0 ATR
- Max positions: 5

**Target Metrics**:
- Trades: 3-5/day (vs 2.1 in v3)
- Win rate: 55%+ (vs 42.3% in v3)
- Monthly PnL: $150+ (vs $18.94 in v3)

---

### Step 5: Compare v3 vs v4 (5 min)
```bash
python scripts/compare_v3_v4_subset.py
```

**Comparison**:
- Universe: 27 → 100 symbols
- Trades/day: 2.1 → ?
- Win rate: 42.3% → ?
- Monthly PnL: $18.94 → ?

---

## Decision Tree

### If v4 Subset Outperforms v3:
✅ **Scale to Full 1,108 Symbols**
```bash
# Generate full training data (2-3 hours)
python scripts/generate_training_data_full.py

# Train on full universe (1 hour)
python scripts/train_v4_full.py

# Backtest and compare
python scripts/backtest_v4_full.py
python scripts/compare_v3_v4_full.py
```

### If v4 Subset Underperforms v3:
❌ **Rollback to v3**
- Keep existing 27-symbol models
- Improve selectivity only (prob ≥ 0.75)
- Document learnings

---

## Files Created

### Executed
1. ✅ `scripts/create_smb_universe_simple.py` - Created 1,108-symbol list
2. 🔄 `scripts/generate_training_data_subset.py` - RUNNING

### Ready to Execute
3. ⏳ `scripts/train_v4_subset.py` - Train LONG/SHORT models
4. ⏳ `scripts/generate_v4_predictions_subset.py` - Generate predictions
5. ⏳ `scripts/backtest_v4_subset.py` - Backtest strategy
6. ⏳ `scripts/compare_v3_v4_subset.py` - Performance comparison

### Monitoring
7. ✅ `scripts/check_v4_progress.sh` - Status checker

---

## Key Metrics to Watch

### Training (Step 2)
- ROC AUC ≥ 0.95 ✓
- Volume momentum importance > 0.20 ✓
- Class balance reasonable (not 99% one class)

### Backtesting (Step 4)
- Trades/day: 3-5 (vs 2.1 current)
- Win rate: 55%+ (vs 42.3% current)
- R-multiple: 2.5+ (vs 1.6 current)
- Monthly PnL: $150+ (vs $18.94 current)

### Comparison (Step 5)
- Universe expansion: 27 → 100 symbols (+270%)
- Trade frequency improvement: +50%+
- Win rate improvement: +30%+
- PnL improvement: +700%+

---

## Timeline

| Step | Duration | Start | End |
|------|----------|-------|-----|
| 1. Data Gen | 30-60 min | 11:03 | ~11:45 |
| 2. Training | 30 min | 11:45 | 12:15 |
| 3. Predictions | 5 min | 12:15 | 12:20 |
| 4. Backtest | 10 min | 12:20 | 12:30 |
| 5. Compare | 5 min | 12:30 | 12:35 |

**Total**: ~2 hours (as estimated)

---

## Current Time: 11:05 SGT

**Next check**: 11:30 SGT (run `./scripts/check_v4_progress.sh`)

**If complete early**: Proceed immediately to Step 2 (training)
