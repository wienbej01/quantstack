# Intraday ML System Diagnostic Report
**Generated:** 2025-12-04
**Stage 1 Training Completed:** 2025-12-03 20:36:59 (5 hours runtime)
**Stage 2 Training:** In Progress

---

## Stage 1 Model Performance

### Training Statistics
- **Samples:** 508,830 (97 symbols, 2023-10-02 to 2024-04-15)
- **Big Move Rate:** 14.21% (72,320 positive / 436,510 negative)
- **Class Imbalance:** 6.0:1 (negative:positive)
- **Features:** 68 features across 8 families

### Model Metrics (Train Set)
- **ROC-AUC:** 0.8850 ⭐ (Strong discrimination)
- **Precision:** 0.4032 (40% of predicted big moves are real)
- **Recall:** 0.8079 (Catches 81% of actual big moves)
- **F1 Score:** 0.5379

### Cross-Validation (5-Fold)
- **ROC-AUC:** 0.8336 ± 0.0018 (Stable across folds)
- **Precision:** 0.3647 ± 0.0022
- **Recall:** 0.7121 ± 0.0025
- **F1:** 0.4824 ± 0.0023

### Confusion Matrix
```
                Predicted
                No Move    Big Move
Actual No Move   350,034    86,476  (FPR: 19.8%)
Actual Big Move   13,894    58,426  (FNR: 19.2%)
```

---

## Feature Importance Analysis

### Top 10 Most Important Features
1. **f__vwap__value_3** (1503) - VWAP 3-bar
2. **f__vol__atr_6** (1378) - ATR 6-bar (volatility)
3. **f__vol__rolling_std_6** (1281) - Rolling std 6-bar
4. **f__vwap__value_6** (1202) - VWAP 6-bar
5. **f__vwap__dist_30** (1081) - Distance from 30-bar VWAP
6. **f__vol__sum_6** (1050) - Volume sum 6-bar
7. **f__vol__atr_3** (1048) - ATR 3-bar
8. **f__range__ratio_1.0** (1007) - Price range ratio
9. **f__vol__sum_3** (977) - Volume sum 3-bar
10. **f__vol__rel_6** (943) - Relative volume 6-bar

### Feature Family Distribution
- **Convergence (conv):** 21 features - Order flow proxies
- **VWAP:** 18 features - Price/VWAP relationships
- **Volatility (vol):** 7 features - ATR, rolling std, volume
- **Momentum (mom):** 7 features - RSI, ROC
- **Time:** 6 features - Hour/day cyclical encoding
- **Returns (ret):** 5 features - Simple returns
- **Moving Averages (ma):** 3 features
- **Range:** 1 feature

### Importance Concentration
- **Top 10 features:** 28.4% of total importance
- **Top 20 features:** 48.1% of total importance

**Interpretation:** Moderate concentration. No single feature dominates (healthy).

---

## Key Findings & Concerns

### ✅ Strengths
1. **Strong ROC-AUC (0.885):** Model has good discrimination ability
2. **High Recall (80.8%):** Catches most big moves (good for opportunity capture)
3. **Stable CV Performance:** Low std deviation across folds (not overfitting)
4. **Diverse Feature Usage:** Top 10 features only account for 28% (not relying on single signal)
5. **VWAP + Volatility Dominance:** Makes intuitive sense for breakout prediction

### ⚠️ Concerns
1. **Low Precision (40.3%):** 60% of predicted big moves are false positives
   - **Impact:** With 3-5 trades/day budget, false positives are expensive
   - **Mitigation:** Need higher probability threshold (0.70-0.75 instead of 0.50)

2. **Class Imbalance (6:1):** Big moves are rare
   - **Current:** 14.2% positive rate
   - **Risk:** Model may be too eager to predict big moves
   - **Action:** Test different decision thresholds in policy sweep

3. **High False Positive Rate (19.8%):** 1 in 5 non-big-moves get flagged
   - **At 0.50 threshold:** Would generate ~86K false signals on 508K samples
   - **Need:** Tighter threshold to reduce false positives

4. **ATR in Features AND Labels:** Potential circularity
   - **f__vol__atr_6** is 2nd most important feature
   - **Target threshold** uses ATR × 1.10
   - **Risk:** Model may be learning the threshold formula, not true predictive patterns
   - **Action:** Test alternative target definitions (percentile-based)

---

## Signal Budget Analysis (Pending Step 3)

**Status:** Cannot run until Step 3 (OOS scoring) completes
**Purpose:** Determine how many signals/day at different thresholds

**Expected Results:**
- At prob > 0.50: ~20-30 signals/day (too many)
- At prob > 0.65: ~10-15 signals/day (manageable)
- At prob > 0.70: ~5-8 signals/day (target range)
- At prob > 0.75: ~2-4 signals/day (too few)

**Action:** Run after Step 3 completes

---

## Recommendations

### Immediate (After Step 2 Completes)
1. **Run Step 3 & 4** to get OOS predictions and policy sweep results
2. **Analyze signal frequency** at thresholds 0.65-0.75
3. **Check Stage 2 directional accuracy** (need >55% to be viable)

### Short-Term (Next Iteration)
1. **Raise probability thresholds** in policy config:
   - Stage 1: 0.70 (from 0.60)
   - Stage 2: 0.65 (from 0.60)
2. **Test alternative target definitions:**
   - Percentile-based (85th percentile of symbol's returns)
   - Regime-conditional (tighter in low-vol, looser in high-vol)
3. **Add ranking mechanism** to pick best 3-5 signals when >5 available

### Medium-Term (Weeks 3-4)
1. **Feature engineering:**
   - Cross-sectional features (relative to SPY, sector)
   - Regime indicators (VIX, market breadth)
   - Lagged labels (did symbol have big move yesterday?)
2. **Address ATR circularity:**
   - Test targets without ATR dependency
   - Use different volatility measure in features vs labels
3. **Cost model:**
   - Add commission ($1/trade) + slippage (4 bps)
   - Re-run backtest with realistic costs

---

## Next Steps

**While Stage 2 Trains:**
- ✅ Stage 1 diagnostics complete
- ✅ Label analysis complete
- ⏳ Signal frequency analysis (pending Step 3)

**After Step 2 Completes:**
1. Run Stage 2 diagnostics (directional model performance)
2. Run Step 3 (OOS scoring)
3. Run signal frequency analysis
4. Run Step 4 (policy sweep)
5. Analyze sweep results for optimal thresholds

**Decision Point:**
- If OOS Sharpe > 1.5 after costs → Proceed to paper trading
- If OOS Sharpe 1.0-1.5 → Iterate on thresholds/ranking
- If OOS Sharpe < 1.0 → Revisit target definition or features
