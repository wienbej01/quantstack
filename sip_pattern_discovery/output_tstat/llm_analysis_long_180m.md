# Pattern Analysis Report

**Target:** fwd_ret_180m
**Horizon:** 180 minutes
**Patterns analyzed:** 5

---

# Discovered Patterns for Target: fwd_ret_180m

Total patterns found: 5
Showing top 5 patterns

## Pattern 2
**Rule:** price_vs_session_avwap_pct_bin == 4 AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 53.72 (p=0.00e+00)
**Expectancy:** 0.0447% per trade
**Win Rate:** 54.1%
**Profit Factor:** 1.36
**Sharpe Ratio:** 1.54
**Avg Win:** 0.3101% | **Avg Loss:** 0.2687%
**Samples:** 305937 trades

## Pattern 3
**Rule:** atr_14_bin == 0 AND is_power_hour_bin == False
**Direction:** LONG
**T-Statistic:** 53.36 (p=0.00e+00)
**Expectancy:** 0.0110% per trade
**Win Rate:** 49.8%
**Profit Factor:** 1.15
**Sharpe Ratio:** 0.79
**Avg Win:** 0.1735% | **Avg Loss:** 0.1504%
**Samples:** 1147293 trades

## Pattern 4
**Rule:** is_power_hour_bin == False AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 51.01 (p=0.00e+00)
**Expectancy:** 0.0185% per trade
**Win Rate:** 51.3%
**Profit Factor:** 1.15
**Sharpe Ratio:** 0.74
**Avg Win:** 0.2798% | **Avg Loss:** 0.2571%
**Samples:** 1212123 trades

## Pattern 5
**Rule:** atr_14_bin == 0 AND is_first_hour_bin == False
**Direction:** LONG
**T-Statistic:** 50.82 (p=0.00e+00)
**Expectancy:** 0.0127% per trade
**Win Rate:** 50.0%
**Profit Factor:** 1.16
**Sharpe Ratio:** 0.73
**Avg Win:** 0.1859% | **Avg Loss:** 0.1606%
**Samples:** 1228356 trades

## Pattern 6
**Rule:** atr_14_bin == 0
**Direction:** LONG
**T-Statistic:** 47.81 (p=0.00e+00)
**Expectancy:** 0.0116% per trade
**Win Rate:** 49.8%
**Profit Factor:** 1.14
**Sharpe Ratio:** 0.66
**Avg Win:** 0.1897% | **Avg Loss:** 0.1651%
**Samples:** 1321068 trades


---

# LLM Analysis

## Pattern 2

- The given rule may be exploiting the behavioral bias of investors to follow the trend (evidenced by the price performing better than average) and macroeconomic elements (signaled by positive S&P500 performance). This suggests a reasonable economic rationale.
- Recent results show a profitable expectancy, slightly above the necessary threshold. Keep in mind that slippage/commissions could decrease this margin.
- The quantity and frequency of trades fall within the optimal operation range, making it a sound opportunity without posing a risk of overtrading.
- The pattern's performance seems middle of the road with an acceptable win rate and a profit factor slightly under the expected threshold. However, the Sharpe ratio is reasonable and indicates a adequate risk-adjusted return.
- **Recommendation**: GO, contingent on a more in-depth examination of liquidity and other trading conditions as well as monitoring for regime changes.

## Pattern 3, Pattern 4, Pattern 5, and Pattern 6

- For all four patterns, expectancy is considerably below the 0.02% lower limit, suggesting that the patterns might not be worthwhile after covering trading costs.
- For each rule, the profit factor is below 1.2, suggesting they are barely profitable.
- While the number of trades is large and diversification is highly feasible, the low Sharpe ratios indicate that the risk-adjusted returns may not outweigh the complexity.
- **Recommendation**: NO-GO. The low expectancy and profit factor combined with a lack of a clear economic rationale for exploitation resulting in these trading patterns makes it unlikely for these patterns to generate sufficient profits.
  
*Note*: Even though statistical significance is high (T-statistic >3.0) for all patterns, it is the economic significance and tradability of these patterns that affect their practical application and return potential.