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

## Pattern 11
**Rule:** price_vs_vwap_pct_bin == 0 AND is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 29.74 (p=0.00e+00)
**Expectancy:** 0.0990% per trade
**Win Rate:** 50.4%
**Profit Factor:** 1.88
**Sharpe Ratio:** 2.33
**Avg Win:** 0.4195% | **Avg Loss:** 0.2271%
**Samples:** 40,932 bar observations
**OVERFIT RISK SCORE:** 1.12 ⚠️ REJECT

## Pattern 1
**Rule:** rel_strength_60m_bin == 0.0 AND is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 25.27 (p=0.00e+00)
**Expectancy:** 0.0624% per trade
**Win Rate:** 48.3%
**Profit Factor:** 1.90
**Sharpe Ratio:** 1.93
**Avg Win:** 0.2736% | **Avg Loss:** 0.1347%
**Samples:** 43,057 bar observations
**OVERFIT RISK SCORE:** 0.54 ✅ ACCEPTABLE

## Pattern 2
**Rule:** ret_60m_bin == 0.0 AND is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 25.27 (p=0.00e+00)
**Expectancy:** 0.0624% per trade
**Win Rate:** 48.3%
**Profit Factor:** 1.90
**Sharpe Ratio:** 1.93
**Avg Win:** 0.2736% | **Avg Loss:** 0.1347%
**Samples:** 43,057 bar observations
**OVERFIT RISK SCORE:** 0.54 ✅ ACCEPTABLE

## Pattern 33
**Rule:** session_range_pct_bin == 3 AND is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 22.70 (p=0.00e+00)
**Expectancy:** 0.0890% per trade
**Win Rate:** 53.6%
**Profit Factor:** 1.45
**Sharpe Ratio:** 1.61
**Avg Win:** 0.5340% | **Avg Loss:** 0.4256%
**Samples:** 49,836 bar observations
**OVERFIT RISK SCORE:** 0.72 ✅ ACCEPTABLE

## Pattern 22
**Rule:** rvol_bin == 4 AND is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 20.41 (p=0.00e+00)
**Expectancy:** 0.0664% per trade
**Win Rate:** 49.5%
**Profit Factor:** 1.48
**Sharpe Ratio:** 1.50
**Avg Win:** 0.4111% | **Avg Loss:** 0.2721%
**Samples:** 46,965 bar observations
**OVERFIT RISK SCORE:** 0.36 ✅ ACCEPTABLE

## Pattern 34
**Rule:** session_range_pct_bin == 4 AND is_power_hour_bin == True
**Direction:** SHORT
**Regime:** bull_low_vol
**T-Statistic:** 20.27 (p=0.00e+00)
**Expectancy:** 0.0909% per trade
**Win Rate:** 50.1%
**Profit Factor:** 1.47
**Sharpe Ratio:** 1.68
**Avg Win:** 0.5714% | **Avg Loss:** 0.3912%
**Samples:** 36,885 bar observations
**OVERFIT RISK SCORE:** 0.70 ✅ ACCEPTABLE

## Pattern 23
**Rule:** is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 27.35 (p=0.00e+00)
**Expectancy:** 0.0368% per trade
**Win Rate:** 48.6%
**Profit Factor:** 1.27
**Sharpe Ratio:** 0.90
**Avg Win:** 0.3533% | **Avg Loss:** 0.2628%
**Samples:** 230,334 bar observations
**OVERFIT RISK SCORE:** 0.07 ✅ ACCEPTABLE

## Pattern 12
**Rule:** is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 27.42 (p=0.00e+00)
**Expectancy:** 0.0302% per trade
**Win Rate:** 48.1%
**Profit Factor:** 1.30
**Sharpe Ratio:** 0.91
**Avg Win:** 0.2720% | **Avg Loss:** 0.1935%
**Samples:** 230,334 bar observations
**OVERFIT RISK SCORE:** 0.00 ✅ ACCEPTABLE

## Pattern 3
**Rule:** price_vs_vwap_pct_bin == 0 AND is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 19.04 (p=0.00e+00)
**Expectancy:** 0.0409% per trade
**Win Rate:** 48.7%
**Profit Factor:** 1.55
**Sharpe Ratio:** 1.49
**Avg Win:** 0.2358% | **Avg Loss:** 0.1441%
**Samples:** 40,932 bar observations
**OVERFIT RISK SCORE:** 0.11 ✅ ACCEPTABLE

## Pattern 13
**Rule:** rvol_bin == 4 AND is_power_hour_bin == True
**Direction:** LONG
**Regime:** bull_low_vol
**T-Statistic:** 17.87 (p=0.00e+00)
**Expectancy:** 0.0480% per trade
**Win Rate:** 49.4%
**Profit Factor:** 1.45
**Sharpe Ratio:** 1.31
**Avg Win:** 0.3112% | **Avg Loss:** 0.2093%
**Samples:** 46,965 bar observations
**OVERFIT RISK SCORE:** 0.18 ✅ ACCEPTABLE

