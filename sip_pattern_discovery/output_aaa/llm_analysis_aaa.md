# Discovered Patterns for Target: AAA Patterns

Total patterns found: 10
Showing top 10 patterns

## CRITICAL OVERFITTING CHECKS
You MUST flag patterns with:
- Win rate > 65% as **HIGH OVERFIT RISK**
- Sharpe > 3.0 as **EXTREME METRICS - SUSPECT**
- Expectancy > 0.10% as **UNREALISTIC EDGE**
- Samples < 10,000 as **INSUFFICIENT DATA**

## DEGRADATION RISK SCORE
Calculate: Risk = (win_rate - 0.50) * 2 + (sharpe - 1.5) * 0.5 + (expectancy - 0.03) * 10
If Risk > 1.0: **REJECT** pattern as likely overfit

## APPROVAL CRITERIA
Only approve patterns with:
- Moderate metrics (not extreme)
- Clear economic rationale with causal mechanism
- Regime alignment with current market
- Event-based conditions (time-constrained)

---

## Pattern 130
**Rule:** vwap_cross_up_bin == True AND atr_14_bin == 0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 38.98 (p=0.00e+00)
**Expectancy:** 0.0854% per trade
**Win Rate:** 53.9%
**Profit Factor:** 1.40
**Sharpe Ratio:** 1.71
**Avg Win:** 0.5517% | **Avg Loss:** 0.4590%
**Samples:** 130,213 bar observations
**OVERFIT RISK SCORE:** 0.74 ✅ ACCEPTABLE

## Pattern 131
**Rule:** ret_15m_turned_positive_bin == True AND atr_14_bin == 0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 37.04 (p=0.00e+00)
**Expectancy:** 0.0852% per trade
**Win Rate:** 53.7%
**Profit Factor:** 1.40
**Sharpe Ratio:** 1.70
**Avg Win:** 0.5526% | **Avg Loss:** 0.4574%
**Samples:** 119,497 bar observations
**OVERFIT RISK SCORE:** 0.73 ✅ ACCEPTABLE

## Pattern 132
**Rule:** ret_5m_turned_positive_bin == True AND atr_14_bin == 0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 34.06 (p=0.00e+00)
**Expectancy:** 0.0826% per trade
**Win Rate:** 53.5%
**Profit Factor:** 1.39
**Sharpe Ratio:** 1.66
**Avg Win:** 0.5495% | **Avg Loss:** 0.4537%
**Samples:** 105,784 bar observations
**OVERFIT RISK SCORE:** 0.68 ✅ ACCEPTABLE

## Pattern 221
**Rule:** vwap_cross_up_bin == True AND rvol_bin == 0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 33.86 (p=0.00e+00)
**Expectancy:** 0.0986% per trade
**Win Rate:** 53.5%
**Profit Factor:** 1.33
**Sharpe Ratio:** 1.51
**Avg Win:** 0.7481% | **Avg Loss:** 0.6492%
**Samples:** 127,550 bar observations
**OVERFIT RISK SCORE:** 0.76 ✅ ACCEPTABLE

## Pattern 222
**Rule:** ret_30m_turned_positive_bin == True AND rvol_bin == 0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 32.62 (p=0.00e+00)
**Expectancy:** 0.0975% per trade
**Win Rate:** 53.4%
**Profit Factor:** 1.32
**Sharpe Ratio:** 1.49
**Avg Win:** 0.7470% | **Avg Loss:** 0.6462%
**Samples:** 120,304 bar observations
**OVERFIT RISK SCORE:** 0.74 ✅ ACCEPTABLE

## Pattern 223
**Rule:** ret_15m_turned_positive_bin == True AND rvol_bin == 0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 32.23 (p=0.00e+00)
**Expectancy:** 0.0967% per trade
**Win Rate:** 53.5%
**Profit Factor:** 1.32
**Sharpe Ratio:** 1.48
**Avg Win:** 0.7460% | **Avg Loss:** 0.6502%
**Samples:** 120,132 bar observations
**OVERFIT RISK SCORE:** 0.74 ✅ ACCEPTABLE

## Pattern 224
**Rule:** ret_5m_turned_positive_bin == True AND rvol_bin == 0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 30.44 (p=0.00e+00)
**Expectancy:** 0.0961% per trade
**Win Rate:** 53.4%
**Profit Factor:** 1.32
**Sharpe Ratio:** 1.47
**Avg Win:** 0.7455% | **Avg Loss:** 0.6492%
**Samples:** 108,318 bar observations
**OVERFIT RISK SCORE:** 0.73 ✅ ACCEPTABLE

## Pattern 225
**Rule:** ret_15m_turned_positive_bin == True AND ret_15m_bin == 2.0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 33.78 (p=0.00e+00)
**Expectancy:** 0.0905% per trade
**Win Rate:** 53.9%
**Profit Factor:** 1.28
**Sharpe Ratio:** 1.29
**Avg Win:** 0.7778% | **Avg Loss:** 0.7143%
**Samples:** 173,606 bar observations
**OVERFIT RISK SCORE:** 0.68 ✅ ACCEPTABLE

## Pattern 226
**Rule:** vwap_cross_up_bin == True AND ret_15m_bin == 2.0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 30.39 (p=0.00e+00)
**Expectancy:** 0.0949% per trade
**Win Rate:** 54.2%
**Profit Factor:** 1.29
**Sharpe Ratio:** 1.35
**Avg Win:** 0.7806% | **Avg Loss:** 0.7165%
**Samples:** 128,450 bar observations
**OVERFIT RISK SCORE:** 0.73 ✅ ACCEPTABLE

## Pattern 227
**Rule:** vwap_cross_up_bin == True AND ret_5m_bin == 2.0
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 29.38 (p=0.00e+00)
**Expectancy:** 0.0909% per trade
**Win Rate:** 53.7%
**Profit Factor:** 1.27
**Sharpe Ratio:** 1.27
**Avg Win:** 0.7860% | **Avg Loss:** 0.7151%
**Samples:** 135,703 bar observations
**OVERFIT RISK SCORE:** 0.68 ✅ ACCEPTABLE

