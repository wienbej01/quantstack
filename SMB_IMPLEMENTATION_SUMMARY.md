# SMB Universe Implementation Summary

**Date**: 2025-12-06  
**Objective**: Expand from 97-symbol static universe to 1,108-symbol catalyst-driven universe

---

## Key Discoveries

### 1. Current System State
- **Existing training data**: 27 symbols (lowercase), 140K rows
- **Gold universe**: 1,108 symbols (uppercase)
- **Current SIP**: 97 symbols (static liquidity filter)
- **v3 models**: Already trained on 27-symbol subset

### 2. Data Structure
- Gold data organized as: `/gcs-mount/gold/stocks/1m/{SYMBOL}/{YEAR}/{YEAR-MM}.parquet`
- Monthly parquet files, not daily
- Existing training data uses lowercase symbols
- Symbol name mismatch prevents direct universe expansion

### 3. SMB Scanner Status
- Created `smb_scanner_monthly.py` to work with monthly parquet structure
- Functional but slow (~2 min per day for 1,108 symbols)
- Gap/RVOL/ATR calculations working correctly

---

## Correct Implementation Path

### Option A: Retrain from Scratch (RECOMMENDED)
**Time**: 4-6 hours  
**Benefit**: Clean implementation, full 1,108-symbol universe

**Steps**:
1. Generate training data for full universe using `data_prep.py`
   ```bash
   # Use all 1,108 symbols from gold
   symbols = load_full_universe()  # uppercase
   dataset = create_training_dataset(symbols, start_date, end_date, ...)
   ```

2. Train v4 models on expanded universe
   ```bash
   python scripts/train_separate_models.py  # with new data
   ```

3. Generate predictions with high selectivity (prob ≥ 0.75)

4. Backtest with existing `backtest_v3_comparison.py`

### Option B: Use Existing Models + Expand Prediction Universe
**Time**: 1-2 hours  
**Benefit**: Quick validation, uses proven v3 models

**Steps**:
1. Generate features for full 1,108-symbol universe
2. Apply existing v3 LONG/SHORT models
3. Filter predictions: prob ≥ 0.75, volume_momentum ≥ 0.15
4. Backtest on filtered signals

---

## Files Created

### Working Scripts
1. `/home/jacobw/quantstack/extensions/intraday_ml/smb_scanner_monthly.py`
   - SMB-style scanner for monthly parquet files
   - Calculates gap, PM RVOL, ATR
   - Functional but slow

2. `/home/jacobw/quantstack/scripts/create_smb_universe_simple.py`
   - Extracts all 1,108 symbols from gold
   - Saved to `/run/smb_universe.txt`
   - ✅ COMPLETE

3. `/home/jacobw/quantstack/scripts/train_v4_full_universe.py`
   - Attempts to retrain on full universe
   - ❌ BLOCKED: Symbol name mismatch (uppercase vs lowercase)

### Placeholder Scripts (Need Data)
4. `/home/jacobw/quantstack/scripts/regenerate_sip_with_smb.py`
   - Would generate daily SIP lists using SMB filters
   - Slow: ~2 min/day × 175 days = 6 hours

5. `/home/jacobw/quantstack/scripts/train_v4_smb_models.py`
   - Would train on SMB-filtered universe
   - Needs regenerated SIP data first

6. `/home/jacobw/quantstack/scripts/generate_v4_predictions.py`
   - Generate predictions with prob ≥ 0.75
   - Ready to use once models trained

7. `/home/jacobw/quantstack/scripts/backtest_v4_smb.py`
   - Backtest with 2% risk, 2.5 ATR target, 1.0 ATR stop
   - Ready to use once predictions generated

8. `/home/jacobw/quantstack/scripts/compare_v3_v4.py`
   - Compare v3 vs v4 performance
   - Ready to use once v4 backtest complete

---

## Recommended Next Steps

### Immediate (30 min)
1. Fix symbol case mismatch in training data generation
2. Verify gold data accessibility for full universe

### Short-term (2-3 hours)
1. Generate training data for 100-symbol subset (test)
2. Train v4 models on subset
3. Validate improvement over v3

### Full Implementation (4-6 hours)
1. Generate training data for full 1,108 symbols
2. Train v4 LONG/SHORT models
3. Generate predictions (prob ≥ 0.75)
4. Backtest and compare to v3
5. Document results

---

## Success Metrics

**Target** (from NEXT_SESSION_PLAN.md):
- ✅ Universe: 1,108 symbols (100% coverage)
- ✅ Trades: 3-5/day (vs 2.1 current)
- ✅ Win Rate: 55%+ (vs 42.3%)
- ✅ Monthly PnL: $150+ at 1-share (vs $18.94)

**Current Status**:
- Universe: 1,108 symbols identified ✅
- SMB filters: Implemented ✅
- Training pipeline: Blocked (symbol mismatch) ❌
- Backtest pipeline: Ready ✅

---

## Technical Debt

1. **Symbol case inconsistency**: Gold uses uppercase, training uses lowercase
2. **Monthly vs daily files**: SMB scanner expects daily, gold has monthly
3. **Slow scanning**: 1,108 symbols × gap/RVOL/ATR = 2 min/day
4. **No premarket data**: PM RVOL calculation uses proxy (first bar volume)

---

## Alternative: Pragmatic Approach

Instead of complex SMB pre-filtering, use ML to do the selection:

1. Train models on FULL 1,108-symbol universe
2. Let models learn what makes stocks "in play"
3. Use high probability threshold (≥0.75) for selectivity
4. Volume momentum feature already captures RVOL concept

**Advantage**: Simpler, faster, more adaptive  
**Disadvantage**: Less interpretable than explicit SMB rules

This aligns with the original goal: expand universe and improve selectivity through better ML, not manual filters.

---

**Status**: Implementation paused at symbol mismatch discovery  
**Decision needed**: Option A (retrain full) vs Option B (expand predictions) vs Pragmatic (ML-driven selection)
