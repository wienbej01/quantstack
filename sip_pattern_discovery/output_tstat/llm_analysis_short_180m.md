# Pattern Analysis Report

**Target:** fwd_ret_180m
**Horizon:** 180 minutes
**Patterns analyzed:** 5

---

# Discovered Patterns for Target: fwd_ret_180m

Total patterns found: 5
Showing top 5 patterns

## Pattern 14
**Rule:** price_vs_session_avwap_pct_bin == 0 AND is_first_hour_bin == False
**Direction:** SHORT
**T-Statistic:** 29.16 (p=0.00e+00)
**Expectancy:** 0.0156% per trade
**Win Rate:** 49.5%
**Profit Factor:** 1.12
**Sharpe Ratio:** 0.45
**Avg Win:** 0.3003% | **Avg Loss:** 0.2632%
**Samples:** 1045319 trades

## Pattern 15
**Rule:** spy_above_sma20_bin == False AND spy_ret_60m_bin == 3
**Direction:** SHORT
**T-Statistic:** 28.98 (p=0.00e+00)
**Expectancy:** 0.0165% per trade
**Win Rate:** 49.3%
**Profit Factor:** 1.16
**Sharpe Ratio:** 0.72
**Avg Win:** 0.2483% | **Avg Loss:** 0.2090%
**Samples:** 405123 trades

## Pattern 17
**Rule:** price_vs_session_avwap_pct_bin == 0
**Direction:** SHORT
**T-Statistic:** 26.27 (p=0.00e+00)
**Expectancy:** 0.0125% per trade
**Win Rate:** 49.3%
**Profit Factor:** 1.09
**Sharpe Ratio:** 0.36
**Avg Win:** 0.3182% | **Avg Loss:** 0.2843%
**Samples:** 1313871 trades

## Pattern 18
**Rule:** price_vs_session_avwap_pct_bin == 0 AND spy_above_sma20_bin == True
**Direction:** SHORT
**T-Statistic:** 26.20 (p=0.00e+00)
**Expectancy:** 0.0181% per trade
**Win Rate:** 49.9%
**Profit Factor:** 1.13
**Sharpe Ratio:** 0.52
**Avg Win:** 0.3209% | **Avg Loss:** 0.2838%
**Samples:** 649162 trades

## Pattern 20
**Rule:** atr_14_bin == 4 AND is_power_hour_bin == True
**Direction:** SHORT
**T-Statistic:** 24.21 (p=0.00e+00)
**Expectancy:** 0.0726% per trade
**Win Rate:** 50.6%
**Profit Factor:** 1.23
**Sharpe Ratio:** 0.99
**Avg Win:** 0.7779% | **Avg Loss:** 0.6500%
**Samples:** 149655 trades


---

# LLM Analysis

## Pattern 14
**Verdict:** NO-GO

Although the t-statistic exceeds the 3.0 cutoff and the rules suggest a market microstructure related to average volume weighted price, the expectancy and profit factor are both too low to be economically meaningful after taking execution costs into account. The strategy appears to net more losses than profits, as indicated by a profit factor of less than 1.2.

## Pattern 15
**Verdict:** NO-GO

While this pattern has a high t-statistic suggesting statistical significance, it lacks economic rationale. The rule depends on an external factor (S&P500 above its 20-day SMA), showing regime-dependency. Furthermore, its expectancy and profit factor underperform the given thresholds after considering transaction costs. 

## Pattern 17
**Verdict:** NO-GO

This rule's pattern seems to focus only on one feature - average volume weighted price, which doesn't provide a clear fundamental explanation. Additionally, low expectancy and profit factor make it economically insignificant. The average loss is almost as large as the average win, potentially resulting in large drawdowns.

## Pattern 18
**Verdict:** NO-GO

Pattern 18 has the same features as Pattern 15 but a different rule, showing high regime dependency. It also lacks a clear informed trader bias, arbitrage, or behavioral bias to exploit. Although the t-statistic is above 3.0, both the expectancy and profit factor underperform the given thresholds, rendering it practically untradeable.

## Pattern 20
**Verdict:** GO

Pattern 20 meets our threshold requirements for t-statistic, expectancy, and profit factor, proving both statistically significant and economically viable. The rule involves trading during the last hour ("power hour") when volatility (as measured by the ATR) is high, suggesting the fact that it might exploit a behavioral bias or informed trader flows. With a high Sharpe ratio of 0.99 and a decent sample size, this strategy has good diversification potential and appear to be robust across different market regimes. However, further analysis is required to confirm these claims. Consider operating this strategy carefully while managing risk and position sizing optimally.
