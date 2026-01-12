# Pattern Analysis Report

**Target:** fwd_ret_30m
**Horizon:** 30 minutes
**Patterns analyzed:** 5

---

# Discovered Patterns for Target: fwd_ret_30m

Total patterns found: 5
Showing top 5 patterns

## Pattern 25
**Rule:** ret_60m_bin == 0.0 AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 21.46 (p=0.00e+00)
**Expectancy:** 0.0113% per trade
**Win Rate:** 50.7%
**Profit Factor:** 1.15
**Sharpe Ratio:** 0.68
**Avg Win:** 0.1662% | **Avg Loss:** 0.1482%
**Samples:** 254006 trades

## Pattern 34
**Rule:** ret_30m_bin == 0.0 AND ret_60m_bin == 4.0
**Direction:** LONG
**T-Statistic:** 9.44 (p=0.00e+00)
**Expectancy:** 0.0127% per trade
**Win Rate:** 49.6%
**Profit Factor:** 1.13
**Sharpe Ratio:** 0.63
**Avg Win:** 0.2194% | **Avg Loss:** 0.1906%
**Samples:** 56342 trades

## Pattern 35
**Rule:** ret_5m_bin == 3.0 AND ret_15m_bin == 0.0
**Direction:** LONG
**T-Statistic:** 8.94 (p=0.00e+00)
**Expectancy:** 0.0102% per trade
**Win Rate:** 49.5%
**Profit Factor:** 1.11
**Sharpe Ratio:** 0.49
**Avg Win:** 0.2012% | **Avg Loss:** 0.1771%
**Samples:** 84053 trades

## Pattern 36
**Rule:** ret_5m_bin == 3.0 AND price_vs_vwap_pct_bin == 0
**Direction:** LONG
**T-Statistic:** 8.13 (p=4.44e-16)
**Expectancy:** 0.0124% per trade
**Win Rate:** 50.5%
**Profit Factor:** 1.12
**Sharpe Ratio:** 0.54
**Avg Win:** 0.2216% | **Avg Loss:** 0.2008%
**Samples:** 56379 trades

## Pattern 37
**Rule:** ret_15m_bin == 3.0 AND price_vs_vwap_pct_bin == 0
**Direction:** LONG
**T-Statistic:** 6.92 (p=4.78e-12)
**Expectancy:** 0.0129% per trade
**Win Rate:** 50.4%
**Profit Factor:** 1.16
**Sharpe Ratio:** 0.76
**Avg Win:** 0.1809% | **Avg Loss:** 0.1576%
**Samples:** 20878 trades


---

# LLM Analysis

# Pattern 25
**Rule:** ret_60m_bin == 0.0 AND spy_ret_60m_bin == 4
**Recommendation:** NO-GO

- The t-statistic score is significantly high, indicating that the pattern is not a result of random chance.
- However, the expectancy is below the 0.02% threshold necessary to be meaningful after costs, and its profit factor is also below 1.5. Moreover, the average loss is too close to the average win, making it a risky pattern.
- In terms of economic rationale, while it could be indicative of mean reversion (if the stock and SPY are inversely related), there isn't a strong enough argument.
- It could be highly regime-dependent since various factors could affect SPY returns.
- It has a very high trade frequency, potential for overtrading should be analysed too.

# Pattern 34
**Rule:** ret_30m_bin == 0.0 AND ret_60m_bin == 4.0
**Recommendation:** NO-GO

- Though the t-statistic is well above the minimum required, the expectancy and profit factor are both below the required threshold.
- Economic rationale could be predicated on mean reversion or momentum, but without the specific details of the bin rules, this is unclear.
- Given the high trade frequency, this rule could lead to overtrading issues as well.

# Pattern 35
**Rule:** ret_5m_bin == 3.0 AND ret_15m_bin == 0.0
**Recommendation:** NO-GO

- Here too, despite the t-statistic being relatively high, the expectancy and profit ratio don't meet the required cut-off.
- Limited information makes explanation of an economic rationale challenging, though it could potentially be a momentum signal.
- From a practical standpoint, the high trade frequency could trigger overtrading.

# Pattern 36
**Rule:** ret_5m_bin == 3.0 AND price_vs_vwap_pct_bin == 0
**Recommendation:** NO-GO

- Again, while the t-statistic meets the threshold, the expectancy and profit factor are too low to confidently support a profitable trading rule.
- The rule invokes two direct price measures, which could be capturing short-term reversion.
- However, the high number of trades again raises concerns about overtrading.

# Pattern 37
**Rule:** ret_15m_bin == 3.0 AND price_vs_vwap_pct_bin == 0
**Recommendation:** NO-GO

- Although the t-statistics score is high, both the expectancy and profit factor are below the recommended threshold.
- An economic interpretation might be short-term reversion to the mean, but it's unclear without more specifics.
- With a relatively low trade frequency, overtrading risk seems less in this pattern. However, the other metrics do not justify implementation. 

Overall, none of the patterns meet the necessary requirements for recommendation. Careful execution, and rigorous back-testing would be advisable before implementing these.