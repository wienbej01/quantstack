# Top-10 Pattern Backtest Analysis
**Date:** 2026-01-18  
**Period:** 2024 Full Year (12 months)  
**Data Source:** Monthly cache with computed features + bins  
**Deduplication:** One signal per symbol/day (first occurrence)

---

## Executive Summary

**Critical Finding:** 7 out of 10 patterns show NEGATIVE expectancy in out-of-sample testing, indicating severe overfitting during discovery phase.

**Viable Patterns:** Only 3 patterns maintain positive expectancy:
1. **P225_RET15M_RET15MBIN_180m**: +0.52% expectancy (best performer)
2. **P227_VWAP_RET5MBIN_180m**: +0.34% expectancy
3. **P130_VWAP_ATR_120m**: +0.34% expectancy

---

## Pattern Performance Breakdown

### ✅ POSITIVE EXPECTANCY (3 patterns)

| Pattern ID | Expectancy | Win Rate | Sharpe | Trades | Horizon | Signal Logic |
|------------|------------|----------|--------|--------|---------|--------------|
| **P225_RET15M_RET15MBIN_180m** | **+0.52%** | 49.6% | 0.09 | 13,531 | 180m | 15m momentum turn + mid-range momentum |
| **P227_VWAP_RET5MBIN_180m** | **+0.34%** | 49.6% | 0.06 | 13,535 | 180m | VWAP cross + mid-range 5m momentum |
| **P130_VWAP_ATR_120m** | **+0.34%** | 49.2% | 0.08 | 8,617 | 120m | VWAP cross + low volatility |

**Key Observations:**
- All 3 use **momentum bin = 2.0** (mid-range) or **low volatility** filters
- Longer horizons (180m) perform better than 120m
- Win rates cluster around 49-50% (slightly below breakeven)
- Profit factors barely above 1.0 (1.01-1.02)
- Sharpe ratios near zero (0.06-0.09) - minimal risk-adjusted edge

---

### ❌ NEGATIVE EXPECTANCY (7 patterns)

| Pattern ID | Expectancy | Win Rate | Sharpe | Trades | Issue |
|------------|------------|----------|--------|--------|-------|
| P226_VWAP_RET15MBIN_180m | -0.31% | 49.4% | -0.05 | 13,535 | Slight negative edge |
| P131_RET15M_ATR_120m | -0.54% | 48.9% | -0.13 | 8,650 | Momentum turn + low vol fails |
| P132_RET5M_ATR_120m | -0.85% | 48.8% | -0.21 | 8,699 | 5m turn + low vol fails |
| P223_RET15M_RVOL_180m | -1.00% | 49.1% | -0.17 | 13,199 | Low relative volume filter fails |
| P224_RET5M_RVOL_180m | -1.16% | 48.8% | -0.19 | 13,215 | Low rvol + 5m turn fails |
| P222_RET30M_RVOL_180m | -1.42% | 48.6% | -0.24 | 13,193 | Low rvol + 30m turn fails |
| **P221_VWAP_RVOL_180m** | **-1.61%** | 48.7% | -0.27 | 13,195 | **Worst performer** |

**Key Observations:**
- **Low relative volume (rvol_bin == 0)** is a FAILED filter - all 4 rvol patterns are negative
- **Momentum turn + low ATR** combinations fail (P131, P132)
- Profit factors < 1.0 (0.95-0.99) indicate consistent losses
- Win rates 48.6-49.1% (below 50%)

---

## Pattern Category Analysis

### By Signal Type

**VWAP Cross Patterns (4 total):**
- ✅ 2 positive: P130 (+0.34%), P227 (+0.34%)
- ❌ 2 negative: P221 (-1.61%), P226 (-0.31%)
- **Verdict:** VWAP cross works ONLY with low ATR or mid-range momentum bins

**Momentum Turn Patterns (6 total):**
- ✅ 1 positive: P225 (+0.52%)
- ❌ 5 negative: P131, P132, P222, P223, P224
- **Verdict:** Momentum turns are UNRELIABLE unless combined with mid-range momentum bins

### By Filter Type

**Low ATR Filter (atr_14_bin == 0):**
- 1 positive (P130: +0.34%)
- 2 negative (P131: -0.54%, P132: -0.85%)
- **Verdict:** Low volatility helps VWAP but hurts momentum turns

**Low Relative Volume (rvol_bin == 0):**
- 0 positive
- 4 negative (all -1.0% to -1.61%)
- **Verdict:** ⚠️ **FAILED FILTER - DO NOT USE**

**Mid-Range Momentum Bins (ret_*_bin == 2.0):**
- 2 positive (P225: +0.52%, P227: +0.34%)
- 1 negative (P226: -0.31%)
- **Verdict:** Best performing filter type

---

## Statistical Significance Assessment

### Trade Count Analysis
- **120m horizon:** 8,617-8,699 trades (adequate sample size)
- **180m horizon:** 13,195-13,535 trades (strong sample size)
- All patterns have sufficient data for statistical validity

### Expectancy Confidence
Using t-stat approximation: `t = expectancy / (std / sqrt(n))`

**P225 (best pattern):**
- Expectancy: 0.52%
- Trades: 13,531
- Estimated std: ~6.8% (from avg_win/loss)
- **t-stat ≈ 0.89** → **NOT statistically significant** (need t > 1.96 for 95% confidence)

**Conclusion:** Even the best pattern lacks statistical significance for positive expectancy.

---

## Risk Assessment

### Overfitting Evidence
1. **Discovery vs Backtest Degradation:**
   - Discovery expectancy: 0.085-0.099% (from LLM analysis)
   - Backtest expectancy: -1.61% to +0.52%
   - **Degradation:** Most patterns flipped from positive to negative

2. **Win Rate Collapse:**
   - Discovery win rates: 53.5-54.2%
   - Backtest win rates: 48.6-49.6%
   - **Drop:** 3-5 percentage points

3. **Sharpe Ratio Collapse:**
   - Discovery Sharpe: 1.27-1.71
   - Backtest Sharpe: -0.27 to +0.09
   - **Drop:** Massive degradation

### Transaction Cost Impact
Assuming 2 bps per trade (0.02%):
- P225: 0.52% → 0.50% (still positive)
- P227: 0.34% → 0.32% (still positive)
- P130: 0.34% → 0.32% (still positive)

**All 3 viable patterns survive transaction costs.**

---

## Recommendations

### ✅ APPROVED FOR LIVE TRADING (with caution)
1. **P225_RET15M_RET15MBIN_180m** - Primary pattern
   - Best expectancy (+0.52%)
   - Highest trade count (13,531)
   - 3-hour hold period
   
2. **P227_VWAP_RET5MBIN_180m** - Secondary pattern
   - Solid expectancy (+0.34%)
   - High trade count (13,535)
   - 3-hour hold period

3. **P130_VWAP_ATR_120m** - Tertiary pattern
   - Positive expectancy (+0.34%)
   - Shorter 2-hour hold
   - Lower trade count (8,617)

### ❌ REJECTED PATTERNS (7 patterns)
- All patterns with rvol_bin == 0 filter
- All momentum turn + low ATR combinations
- P226 (marginal negative)

### 🔧 SYSTEM IMPROVEMENTS NEEDED

**Critical Issues:**
1. **Validation gate is too permissive** - allowed 7 overfit patterns through
2. **Low relative volume filter is broken** - all 4 patterns failed
3. **Momentum turn signals need better filters** - 5 out of 6 failed

**Recommended Fixes:**
1. Tighten validation degradation thresholds
2. Remove or redesign rvol_bin filter
3. Add minimum OOS expectancy requirement (e.g., > 0.1%)
4. Require positive Sharpe in validation period

---

## Portfolio Construction

### Recommended Allocation
- **P225:** 50% weight (best performer)
- **P227:** 30% weight (solid secondary)
- **P130:** 20% weight (diversification, shorter horizon)

### Expected Portfolio Metrics
- **Blended Expectancy:** ~0.43% per trade
- **Estimated Annual Return:** ~108% (assuming 10 trades/day, 252 days)
- **Estimated Sharpe:** ~0.08 (very low - near random)
- **Risk:** High overfitting risk, requires live monitoring

### Position Sizing
Given low Sharpe ratios (0.06-0.09), recommend:
- **Max 1% risk per trade**
- **Max 5% total exposure across all patterns**
- **Stop loss:** -2% per position

---

## Conclusion

**Reality Check:** The discovery process identified patterns with 1.27-1.71 Sharpe ratios, but OOS testing reveals 0.06-0.09 Sharpe ratios. This is a **95% degradation** and strong evidence of overfitting.

**Viable Edge:** Only 3 out of 10 patterns maintain positive expectancy, and even these show minimal statistical significance. The edge is fragile.

**Path Forward:**
1. Trade only P225, P227, P130 with strict risk limits
2. Monitor live performance weekly
3. Halt trading if expectancy drops below 0% for 2 consecutive weeks
4. Redesign discovery system to prevent rvol_bin and momentum turn overfitting

**Expected Outcome:** Marginal profitability if patterns hold, but high probability of mean reversion to zero expectancy over time.
