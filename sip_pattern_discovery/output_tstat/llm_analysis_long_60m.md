# Pattern Analysis Report

**Target:** fwd_ret_60m
**Horizon:** 60 minutes
**Patterns analyzed:** 5

---

# Discovered Patterns for Target: fwd_ret_60m

Total patterns found: 5
Showing top 5 patterns

## Pattern 9
**Rule:** is_first_hour_bin == True AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 37.86 (p=0.00e+00)
**Expectancy:** 0.0167% per trade
**Win Rate:** 51.1%
**Profit Factor:** 1.16
**Sharpe Ratio:** 0.83
**Avg Win:** 0.2409% | **Avg Loss:** 0.2177%
**Samples:** 525574 trades

## Pattern 10
**Rule:** price_vs_session_avwap_pct_bin == 4 AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 31.90 (p=0.00e+00)
**Expectancy:** 0.0170% per trade
**Win Rate:** 50.7%
**Profit Factor:** 1.22
**Sharpe Ratio:** 0.91
**Avg Win:** 0.1884% | **Avg Loss:** 0.1594%
**Samples:** 306563 trades

## Pattern 21
**Rule:** ret_60m_bin == 0.0 AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 24.00 (p=0.00e+00)
**Expectancy:** 0.0164% per trade
**Win Rate:** 52.1%
**Profit Factor:** 1.17
**Sharpe Ratio:** 0.76
**Avg Win:** 0.2216% | **Avg Loss:** 0.2064%
**Samples:** 253797 trades

## Pattern 22
**Rule:** ret_30m_bin == 0.0 AND spy_ret_60m_bin == 4
**Direction:** LONG
**T-Statistic:** 23.96 (p=0.00e+00)
**Expectancy:** 0.0167% per trade
**Win Rate:** 52.3%
**Profit Factor:** 1.17
**Sharpe Ratio:** 0.74
**Avg Win:** 0.2225% | **Avg Loss:** 0.2094%
**Samples:** 265117 trades

## Pattern 23
**Rule:** ret_60m_bin == 0.0 AND atr_14_bin == 1
**Direction:** LONG
**T-Statistic:** 23.65 (p=0.00e+00)
**Expectancy:** 0.0106% per trade
**Win Rate:** 50.0%
**Profit Factor:** 1.18
**Sharpe Ratio:** 0.85
**Avg Win:** 0.1415% | **Avg Loss:** 0.1205%
**Samples:** 193351 trades


---

# LLM Analysis

## Pattern 9
**Go/No-Go:** No-Go
**Reasoning:** While the t-stat is high (37.86), the expectancy (0.0167%) is lower than the required level after trading costs. Furthermore, the profit factor (1.16) is below the minimum threshold (1.5), suggesting that profits and losses are not distinct enough to provide a sustainable edge. Lastly, the economic rationale is not very clear for this pattern, making it hard to expect its profitability in different market regimes.

## Pattern 10
**Go/No-Go:** No-Go
**Reasoning:** Although the t-stat (31.90) and win rate (50.7%) are good, the expectancy (0.0170%) is still below the threshold after costs. The profit factor (1.22) is also lower than the minimum requirement of 1.5. The economic rationale isn't very robust and the pattern might be regime-dependent, impacting its continuous profitability.

## Pattern 21
**Go/No-Go:** No-Go
**Reasoning:** Despite having a decent t-stat (24.00) and win rate (52.1%), the expectancy (0.0164%) doesn't meet the threshold, particularly after trading costs. Also, the profit factor (1.17) is not sufficient enough for the pattern to be considered profitable. The economic rationale for this pattern doesn't seem strong and it may not work across different market conditions.

## Pattern 22
**Go/No-Go:** No-Go
**Reasoning:** Like Pattern 21, this pattern has a good t-stat (23.96) and win rate (52.3%). However, the expectancy (0.0167%) and profit factor (1.17) are not good enough. Also, the economic rationale is not very clear, and the pattern might be regime-dependent, questioning its sustained profitability.

## Pattern 23
**Go/No-Go:** No-Go
**Reasoning:** The pattern has a great t-stat (23.65) but fails in other areas. The expectancy (0.0106%) is too low even before considering trading costs. The profit factor (1.18) is below the approval criteria. Without a clear economic rationale behind it, there's a risk of the pattern being a statistical artifact.

NOTE: While statistical significance forms the basis of pattern identification, the more crucial aspect lies in the economic rationale and the execution feasibility of the strategy. The value of a pattern largely depends on its potential to yield profits after costs. Therefore, none of the patterns analyzed meet the approval criteria for trading. They either have too low expectancy, low profit factor, or lack of clear economic rationale. Future research could focus on exploring patterns with a strong theoretical basis that might work across different market conditions.