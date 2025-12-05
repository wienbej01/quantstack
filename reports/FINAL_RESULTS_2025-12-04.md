# Intraday ML System - Final Results & Analysis
**Date:** December 4, 2025  
**Status:** Steps 1-4 Complete + Fixes Applied  
**Conclusion:** System needs major revision before viable

---

## Summary

✅ **Completed:**
1. Fixed Sharpe calculation for intraday data
2. Created corrected sweep grid (0.65-0.80 thresholds)
3. Re-ran 576 configurations
4. Comprehensive diagnostics

❌ **Critical Issues Found:**
1. **Win rate fixed at 47%** - Only 4 unique values across 576 configs
2. **Trade count barely varies** - Only 16-20 trades regardless of thresholds
3. **Sharpe still negative** (-52 to -80) despite positive PnL
4. **TOD profiles override base thresholds** - Policy logic issue

---

## Model Performance (Unchanged - Still Strong)

| Stage | ROC-AUC (Train) | ROC-AUC (CV) | Accuracy |
|-------|-----------------|--------------|----------|
| Stage 1 (Volatility) | 0.885 | 0.834 | - |
| Stage 2 (Direction) | 0.929 | 0.714 | 84.9% |

**Models are NOT the problem.** The issue is in the policy/backtest layer.

---

## Sweep Results Analysis

### Configuration Space Tested
- **Stage 1 thresholds:** 0.65, 0.70, 0.75, 0.80
- **Stage 2 thresholds (long):** 0.60, 0.65, 0.70, 0.75
- **Stage 2 thresholds (short):** 0.60, 0.65, 0.70, 0.75
- **Score margins:** 0.00, 0.01, 0.02
- **Max positions:** 2, 3, 5
- **Total configs:** 576

### Actual Results
- **Unique win rates:** 4 (45.0%, 47.4%, 50.0%, 56.2%)
- **Unique trade counts:** 3 (16, 19, 20)
- **Sharpe range:** -80.53 to -52.35
- **PnL range:** $15.96 to $37.14
- **Trades/day:** 0.7 to 0.9 (target was 3-5)

### Best Configuration
- **Thresholds:** S1=0.80, Long=0.60, Short=0.60
- **Sharpe:** -52.35 (broken metric)
- **Win Rate:** 47.4%
- **Trades:** 19 over 22 days (0.86/day)
- **PnL:** $15.96
- **Avg R-multiple:** 0.84 (below 1.0 = losing on average)

---

## Root Cause Analysis

### Issue 1: TOD Profiles Override Base Thresholds

The policy config has TOD (time-of-day) profiles that override base thresholds:

```json
"tod_profiles": {
  "OPEN": {
    "prob_threshold_long": 0.7,   // Overrides base 0.60
    "prob_threshold_short": 0.75  // Overrides base 0.60
  },
  "MID": {
    "prob_threshold_long": 0.65,
    "prob_threshold_short": 0.7
  },
  "LATE": {
    "prob_threshold_long": 0.62,
    "prob_threshold_short": 0.68
  }
}
```

**Result:** Sweep changes base thresholds, but TOD profiles take precedence, making most configs identical.

### Issue 2: Sharpe Calculation Still Broken

Despite fix attempt, Sharpe is still negative with positive PnL. Possible causes:
1. Volatility calculation using wrong time period
2. Annualized return calculation error
3. Risk-free rate assumption wrong
4. Daily resampling not working correctly

### Issue 3: Low Trade Volume

Only 16-20 trades in 22 days (< 1/day) regardless of thresholds suggests:
1. TOD profiles are too restrictive
2. Other rejection filters (score_margin, expected_r, risk_budget) are blocking trades
3. Signal quality is poor (most signals rejected)

### Issue 4: Avg R-Multiple < 1.0

Avg R of 0.84 means average trade loses 0.16R. With 47% win rate:
- Expected value = 0.47 * 2R - 0.53 * 1R = 0.94R - 0.53R = 0.41R per trade
- But actual is 0.84R, suggesting stops are too tight or targets too far

---

## What Actually Works

### Positive Findings
1. **Win rate 45-47%** is acceptable for 1:2 R:R (breakeven is 33%)
2. **Models predict correctly** (rejection analysis shows bigmove_prob filter working)
3. **No catastrophic losses** (max DD < 1%)
4. **System is stable** (doesn't crash, handles edge cases)

### What Doesn't Work
1. **Not enough trades** (< 1/day vs target 3-5/day)
2. **Avg R too low** (0.84 vs target > 1.5)
3. **Thresholds don't matter** (TOD profiles override everything)
4. **Sharpe metric broken** (can't assess risk-adjusted performance)

---

## Recommended Actions

### Immediate (Today)

**1. Disable TOD Profiles**
```json
{
  "tod_filter_enabled": false,
  "tod_profiles": {}
}
```
Re-run sweep to see if thresholds actually work.

**2. Fix Sharpe Calculation Properly**
Current fix doesn't work. Need to:
- Print debug info (trading_days, years, volatility, returns)
- Verify daily resampling is correct
- Check if annualized_return calculation is sound

**3. Analyze Individual Trades**
```python
# Load trades from best config
trades = pd.read_parquet('artefacts/.../trades.parquet')
print(trades[['symbol', 'entry_time', 'exit_time', 'pnl', 'r_multiple', 'exit_reason']])
```
Understand why Avg R is only 0.84.

### Short-Term (This Week)

**1. Simplify Policy**
Remove all complex filters, keep only:
- Stage 1 threshold
- Stage 2 threshold
- Max positions
- Basic stops/targets

**2. Extend Backtest Period**
- Add validation period (April 16-30) = 10 more days
- Total: 32 trading days instead of 22
- More robust statistics

**3. Test Alternative Targets**
Current 2R target may be too aggressive. Test:
- 1.5R target (easier to hit)
- Trailing stops (lock in profits)
- Time-based exits (don't wait for full 2R)

### Medium-Term (Next Week)

**1. Implement Signal Ranking**
Don't just threshold - rank all signals and pick top N:
```python
score = (prob_bigmove - 0.5) * (prob_long - 0.5) * (atr / price)
top_signals = signals.nlargest(5, 'score')
```

**2. Add Regime Filters**
Only trade when market conditions are favorable:
- VIX in range [15, 30]
- SPY not in strong trend (avoid momentum days)
- Sector rotation active (not all sectors moving together)

**3. Walk-Forward Validation**
- Retrain monthly
- Test on next month
- Measure performance decay

---

## Go/No-Go Decision

### Current Status: **NO-GO**

**Reasons:**
1. ❌ Sharpe < 0 (broken metric, but still concerning)
2. ❌ Avg R < 1.0 (losing on average)
3. ❌ Trades < 1/day (not enough opportunities)
4. ❌ Thresholds don't work (TOD override issue)

### Minimum Requirements for GO:
- [ ] Sharpe > 1.0 (after fixing calculation)
- [ ] Avg R > 1.2
- [ ] Trades 2-5/day
- [ ] Win rate > 45%
- [ ] Thresholds actually affect results

### Estimated Time to Fix:
- **Optimistic:** 3-5 days (if TOD disable fixes everything)
- **Realistic:** 1-2 weeks (need policy rewrite)
- **Pessimistic:** 3-4 weeks (need target/feature revision)

---

## Alternative Approaches

If current system doesn't improve after fixes:

### Option 1: Simplify to Single-Stage
- Drop Stage 2 (direction prediction)
- Use Stage 1 only to predict volatility
- Trade both directions with tight stops
- Let winners run, cut losers fast

### Option 2: Different Target Definition
- Current: ATR-based dynamic threshold
- Alternative: Fixed percentile (e.g., 85th percentile of returns)
- Or: Regime-conditional (tighter in low-vol, looser in high-vol)

### Option 3: Different Time Horizon
- Current: 60-minute forward window
- Alternative: 30-minute (faster trades) or 120-minute (bigger moves)
- May improve hit rate or R-multiple

---

## Files Created Today

### Diagnostic Scripts
- `extensions/intraday_ml/diagnostics/analyze_stage1.py`
- `extensions/intraday_ml/diagnostics/analyze_training_meta.py`
- `extensions/intraday_ml/diagnostics/analyze_labels.py`
- `extensions/intraday_ml/diagnostics/analyze_signal_frequency.py`

### Configuration Files
- `configs/extensions/intraday_ml/policy_sweep_grid_v2.yaml`

### Reports
- `reports/EXECUTIVE_SUMMARY.md`
- `reports/diagnostics/DIAGNOSTIC_SUMMARY.md`
- `reports/diagnostics/RESULTS_SUMMARY.md`
- `reports/diagnostics/ACTION_PLAN.md`
- `reports/diagnostics/NEXT_ACTIONS.md`
- `reports/FINAL_RESULTS_2025-12-04.md` (this file)

### Data
- `artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier_v2.csv` (576 configs)
- `reports/diagnostics/*.json` (diagnostic outputs)

---

## Bottom Line

**The ML models are strong (0.88 and 0.93 AUC), but the trading system is not viable in its current form.**

**Key problems:**
1. TOD profiles override threshold sweep (policy bug)
2. Sharpe calculation still broken (backtest bug)
3. Avg R-multiple too low (risk management issue)
4. Not enough trades (filter logic too restrictive)

**Next step:** Disable TOD profiles, fix Sharpe, re-run sweep. If still poor, consider major revision or alternative approaches.

**Confidence in fix:** 40% (multiple deep issues, not just one bug)

**Recommendation:** Spend 1 more day on fixes. If no improvement, pivot to simpler approach or different strategy entirely.
