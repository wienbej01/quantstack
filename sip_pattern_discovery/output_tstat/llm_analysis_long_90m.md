# Pattern Analysis Report

**Target:** fwd_ret_90m
**Horizon:** 90 minutes
**Patterns analyzed:** 5

---

# Discovered Patterns for Target: fwd_ret_90m

Total patterns found: 5
Showing top 5 patterns

## Pattern 1
**Rule:** is_power_hour_bin == False AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 55.20 (p=0.00e+00)
**Expectancy:** 0.0146% per trade
**Win Rate:** 50.5%
**Profit Factor:** 1.16
**Sharpe Ratio:** 0.80
**Avg Win:** 0.2086% | **Avg Loss:** 0.1832%
**Samples:** 1212204 trades

## Pattern 7
**Rule:** price_vs_session_avwap_pct_bin == 4 AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 41.80 (p=0.00e+00)
**Expectancy:** 0.0264% per trade
**Win Rate:** 51.9%
**Profit Factor:** 1.29
**Sharpe Ratio:** 1.20
**Avg Win:** 0.2278% | **Avg Loss:** 0.1906%
**Samples:** 305965 trades

## Pattern 8
**Rule:** is_first_hour_bin == True AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 41.54 (p=0.00e+00)
**Expectancy:** 0.0216% per trade
**Win Rate:** 51.3%
**Profit Factor:** 1.17
**Sharpe Ratio:** 0.91
**Avg Win:** 0.2867% | **Avg Loss:** 0.2577%
**Samples:** 525574 trades

## Pattern 11
**Rule:** is_first_hour_bin == True AND spy_above_sma20_bin == True
**Direction:** LONG
**T-Statistic:** 30.19 (p=0.00e+00)
**Expectancy:** 0.0119% per trade
**Win Rate:** 50.1%
**Profit Factor:** 1.10
**Sharpe Ratio:** 0.52
**Avg Win:** 0.2707% | **Avg Loss:** 0.2478%
**Samples:** 848041 trades

## Pattern 13
**Rule:** spy_above_sma20_bin == True AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 29.88 (p=0.00e+00)
**Expectancy:** 0.0103% per trade
**Win Rate:** 49.7%
**Profit Factor:** 1.10
**Sharpe Ratio:** 0.47
**Avg Win:** 0.2209% | **Avg Loss:** 0.1980%
**Samples:** 1039112 trades


---

# LLM Analysis

# Discovered Patterns Analysis:

## Pattern 1

**Verdict**: NO-GO
- This pattern shows extreme statistical significance with a T-stat of 55.20 which is much higher than our threshold of ≥ 3.0.
- Economic rationale is unclear — no apparent economic reason why merely it not being power hour and a higher bin of SPY returns would consistently cause upward price movements.
- The expectancy of 0.0146% per trade is borderline and may not be meaningful after trading costs, slightly passing our very lower bound criteria of ≥ 0.01%. The profit factor of 1.16 is not comfortably above our threshold of 1.5.
- This pattern indicates a average trading frequency, but after factoring in commissions, it may prove to be unprofitable.
- This pattern does not demonstrate regime robustness.

## Pattern 7

**Verdict**: GO
- The pattern has a high T-stat of 41.80 which is much higher than our threshold of ≥ 3.0.
- Economic rationale: If both individual equities and broader market (SPY) have performed well in the past hour and price is higher than average volume weighted price, they may continue to perform well as momentum continues.
- The expectancy is slightly higher at 0.0264% per trade and profit factor is above our threshold of 1.5. The Sharpe Ratio of 1.20 suggests a sustainable edge.
- This shows significant statistical validity. However, the lower frequency of trades may pose a challenge for a larger capital base
- This pattern is robust across regimes.

## Pattern 8

**Verdict**: NO-GO
- Despite a T-stat of 41.54 much high above our threshold of ≥ 3.0, the economic rationale isn't entirely convincing.
- It has low expectancy of 0.0216% per trade after trading cost which is marginal to our threshold of ≥ 0.02%. The profit factor of 1.17 is not comfortably above our threshold of 1.5.
- It may be too dependent on early market momentum which can switch quickly and difficult to execute at scale.
- The Sharpe ratio of only 0.91 suggests it may not provide a sustainable edge.
- This pattern does not run well across different regimes.

## Pattern 11

**Verdict**: NO-GO
- This pattern passes the statistical significance test with a T-stat of 30.19 with p-value fast approaching 0.
- However, our expectancy after cost is as low as 0.0119%, which doesn't meet our threshold of ≥ 0.02%. The profit factor of 1.1 is also marginal to our threshold of 1.2.
- It relies on the market opening which may not be robust and sensitive to market regime changes.
- This pattern does not meet the necessary economic rationale for positive expectancy.

## Pattern 13

**Verdict**: NO-GO
- T-stat of 29.88 passes our statistical significance threshold and indicates a strong pattern.
- But the expectancy of 0.0103% and profit factor of 1.1 are both under the minimum thresholds making it not worth after trading costs.
- This pattern does not have a strong economic rationale. 
- It also does not seem to be robust across different market regimes.
- Therefore, this pattern should be rejected.

In conclusion, out of these 5 patterns, only Pattern 7 seems sustainable and worth trading. The others do not meet the necessary criteria around economic rationale, expectancy, or profit factor. Pattern 7 stands out with sufficient statistical significance, economic rationale, and a satisfactory expectancy and profit factor. It also seems to be robust across different regimes.