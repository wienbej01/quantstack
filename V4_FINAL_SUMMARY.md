# v4 SMB Implementation - Final Summary

**Date**: 2025-12-06  
**Project**: SMB Capital-inspired universe expansion from 97 static symbols to catalyst-driven selection

---

## Executive Summary

**Goal**: Improve trading performance from 42% → 55%+ win rate via SMB Capital methodology

**Result**: Workflow validated but performance not achieved

**Status**: ✅ Technical implementation complete, ❌ Performance targets not met

---

## What Was Built

### 1. Feature Store System
- **Purpose**: Precompute daily metrics (gap%, ATR, ADV) for fast SIP selection
- **Performance**: 3-4 hours for 1,108 symbols × 3 months (vs 500+ hours naive approach)
- **Features**: Checkpointing, heartbeat monitoring, resume capability
- **Output**: 286,230 rows, 507 symbols, 64 trading days

### 2. SIP Selection (Stocks In Play)
- **Method**: SMB Capital filters (gap ≥2%, ATR ≥$2, ADV ≥10M)
- **Selection**: Top 20 stocks per day by catalyst score
- **Result**: 722 selections, 18 unique symbols, 13.9 avg/day
- **Validation**: ✅ Dynamic daily lists confirmed

### 3. Training Pipeline
- **Data**: 448k bars, 18 symbols, Mar-May 2024
- **Split**: 60% train, 20% val, 20% OOS
- **Labels**: Simple ±2% threshold (fixed broken ATR-based labeling)
- **Distribution**: ~2-3% labeled (realistic)

### 4. ML Models
- **Architecture**: LightGBM binary classifiers (separate LONG/SHORT)
- **Features**: Returns, range, volume ratio (simple features only)
- **Performance**:
  - LONG: Train AUC 0.86, Val AUC 0.75
  - SHORT: Train AUC 0.84, Val AUC 0.68
  - Some overfitting (0.12-0.16 gap)

---

## Results

### 1-Month Proof of Concept (May 2024)
- **Data**: 13 symbols, 22 days
- **Signals**: 35 (1.6/day)
- **Win rate**: 100% (⚠️ overfitted - trained and tested on same data)
- **Conclusion**: Workflow validated but metrics unreliable

### 3-Month OOS Test (Mar-May 2024)
- **Training**: Mar 1 - Apr 15 (217k bars)
- **Validation**: Apr 16 - Apr 30 (77k bars)
- **OOS Test**: May 1 - May 31 (153k bars)
- **Signals**: 4 (0.13/day) - too selective
- **Win rate**: 25% (1 win, 3 losses)
- **P&L**: -4.12%
- **Conclusion**: Model works but not profitable

---

## Key Discoveries

### ✅ What Worked

1. **Feature Store Approach**
   - 100x+ speedup vs naive daily scanning
   - Checkpointing prevents data loss
   - Scales to multi-year periods

2. **SIP Selection Logic**
   - Dynamic daily lists confirmed
   - SMB filters identify catalyst stocks
   - Integration-ready for other repos

3. **Label Generation Fix**
   - Original labeler had `directional_balance` enabled
   - Forced 50/50 LONG/SHORT split (wrong!)
   - Fixed with simple ±2% threshold
   - Result: 2-3% labeled (realistic)

4. **End-to-End Pipeline**
   - All 6 phases work: Feature Store → SIP → Training → Models → Predictions → Backtest
   - Reproducible and documented
   - Can be scaled to larger datasets

### ❌ What Didn't Work

1. **Model Performance**
   - OOS win rate: 25% (target: 55%+)
   - Too selective: 4 signals/month (target: 3-5/day)
   - Not profitable: -4.12% P&L

2. **Feature Engineering**
   - Simple features (returns, volume) insufficient
   - Need: order flow, microstructure, time-of-day patterns
   - Existing `create_training_dataset` doesn't generate proper features

3. **Dataset Size**
   - 18 symbols too small (need 100+)
   - 3 months too short (need 6-12 months)
   - Limited pattern diversity

4. **Model Architecture**
   - Simple LightGBM may not capture intraday dynamics
   - Need: sequence models (LSTM/Transformer) or more sophisticated features

---

## Root Causes of Poor Performance

### 1. Insufficient Features
**Problem**: Only using basic OHLCV-derived features  
**Impact**: Model can't distinguish profitable setups  
**Solution**: Add order flow, bid-ask spread, time-of-day, market regime features

### 2. Small Universe
**Problem**: Only 18 symbols selected by SIP  
**Impact**: Limited trading opportunities, overfitting risk  
**Solution**: Expand to 100+ symbols or relax SIP filters

### 3. High Selectivity
**Problem**: 0.50 probability threshold too high for this model  
**Impact**: Only 4 signals in a month  
**Solution**: Lower threshold to 0.30-0.40 or improve model confidence

### 4. Simple Model
**Problem**: LightGBM with 5 features can't capture complex patterns  
**Impact**: Poor generalization to OOS data  
**Solution**: More features or sequence-based models

---

## Comparison to Original Goals

| Metric | v3 Baseline | v4 Target | v4 Actual | Status |
|--------|-------------|-----------|-----------|--------|
| Universe | 97 static | 1,108 dynamic | 18 dynamic | ❌ Too small |
| Trades/day | 2.1 | 3-5 | 0.13 | ❌ Too selective |
| Win rate | 42.3% | 55%+ | 25% | ❌ Worse |
| Monthly PnL | $18.94 | $150+ | -$4.12 | ❌ Negative |
| SIP Selection | ❌ None | ✅ Dynamic | ✅ Dynamic | ✅ Works |
| Feature Store | ❌ None | ✅ Fast | ✅ Fast | ✅ Works |

---

## Recommendations

### Short-Term (1-2 weeks)

1. **Expand Universe**
   - Lower SIP filters: gap ≥1%, ATR ≥$1, ADV ≥5M
   - Target: 50-100 symbols per day
   - Retrain on larger dataset

2. **Improve Features**
   - Add: volume profile, VWAP distance, time-of-day
   - Add: relative strength vs SPY
   - Add: sector momentum

3. **Adjust Threshold**
   - Lower to 0.30-0.40 for more signals
   - Accept lower precision for higher recall

### Medium-Term (1-2 months)

1. **Expand Time Period**
   - Build feature store for 6-12 months
   - More training data = better generalization

2. **Feature Engineering**
   - Implement proper feature generation in `create_training_dataset`
   - Use existing feature packs from qx-features

3. **Model Improvements**
   - Try ensemble methods
   - Add feature interactions
   - Tune hyperparameters

### Long-Term (3-6 months)

1. **Advanced Models**
   - Sequence models (LSTM/Transformer) for time-series patterns
   - Multi-task learning (predict direction + magnitude)
   - Reinforcement learning for dynamic position sizing

2. **Alternative Approaches**
   - Use SIP for universe selection only
   - Apply traditional technical strategies (not ML)
   - Combine ML signals with rule-based filters

3. **Production Deployment**
   - Real-time SIP generation
   - Live model inference
   - Paper trading validation

---

## Value Delivered

Despite not meeting performance targets, significant value was created:

### 1. Infrastructure
- ✅ Feature store system (reusable for any strategy)
- ✅ SIP selection pipeline (usable in other repos)
- ✅ Checkpointing and monitoring (production-ready)

### 2. Knowledge
- ✅ Identified broken label generation in existing code
- ✅ Validated SMB methodology for universe selection
- ✅ Learned dataset size requirements for ML

### 3. Documentation
- ✅ Complete system documentation
- ✅ SIP access guide for external repos
- ✅ Reproducible workflow

---

## Files Created

### Scripts
- `build_daily_feature_store_3months.py` - Feature store builder
- `generate_smb_sip_3months.py` - SIP selection
- `generate_training_data_3months.py` - Training data with splits
- `train_v4_3months.py` - Model training
- `backtest_v4_3months_oos.py` - OOS backtesting

### Data
- `run/daily_features_3months/features.parquet` - 286k rows
- `run/sip_membership_smb_3months/sip_membership.parquet` - 722 selections
- `artefacts/extensions/intraday_ml/v4_3months/` - Train/val/OOS splits

### Models
- `models/v4_3months_long.txt` - LONG classifier
- `models/v4_3months_short.txt` - SHORT classifier

### Documentation
- `SYSTEM_OVERVIEW.md` - Technical documentation
- `PROJECT_STATUS.md` - Project management
- `SIP_ACCESS_GUIDE.md` - External integration guide
- `V4_FINAL_SUMMARY.md` - This document

---

## Conclusion

**Technical Success**: ✅ Complete end-to-end pipeline validated  
**Business Success**: ❌ Performance targets not met

The v4 implementation successfully built infrastructure for catalyst-driven stock selection but failed to achieve profitable trading performance. The primary issues are insufficient features, small dataset, and overly selective model.

**Next Steps**: Focus on feature engineering and dataset expansion before attempting production deployment.

---

## Session Timeline

- **10:00-11:00**: SMB scanner creation, universe identification
- **11:00-13:00**: Feature store approach, 1-month validation
- **13:00-16:00**: Label generation investigation and fix
- **16:00-17:00**: 1-month proof of concept complete
- **17:00-18:00**: 3-month expansion (feature store, SIP, training)
- **18:00-18:15**: Model training and OOS testing

**Total Duration**: ~8 hours  
**Lines of Code**: ~2,000  
**Data Processed**: 448k bars, 507 symbols, 3 months
