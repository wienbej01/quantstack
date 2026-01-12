# Pattern Analysis Report

**Target:** fwd_ret_90m
**Horizon:** 90 minutes
**Patterns analyzed:** 5

---

# Discovered Patterns for Target: fwd_ret_90m

Total patterns found: 5
Showing top 5 patterns

## Pattern 16
**Rule:** is_power_hour_bin == True AND spy_ret_60m_bin == 4
**Direction:** SHORT
**T-Statistic:** 26.89 (p=0.00e+00)
**Expectancy:** 0.0614% per trade
**Win Rate:** 52.5%
**Profit Factor:** 1.43
**Sharpe Ratio:** 1.34
**Avg Win:** 0.3914% | **Avg Loss:** 0.3036%
**Samples:** 101080 trades

## Pattern 19
**Rule:** is_first_hour_bin == True AND spy_ret_60m_bin == 3
**Direction:** SHORT
**T-Statistic:** 25.26 (p=0.00e+00)
**Expectancy:** 0.0186% per trade
**Win Rate:** 52.6%
**Profit Factor:** 1.16
**Sharpe Ratio:** 0.85
**Avg Win:** 0.2501% | **Avg Loss:** 0.2380%
**Samples:** 221303 trades

## Pattern 27
**Rule:** atr_14_bin == 4 AND is_power_hour_bin == True
**Direction:** SHORT
**T-Statistic:** 18.10 (p=0.00e+00)
**Expectancy:** 0.0415% per trade
**Win Rate:** 49.9%
**Profit Factor:** 1.19
**Sharpe Ratio:** 0.74
**Avg Win:** 0.5280% | **Avg Loss:** 0.4432%
**Samples:** 149655 trades

## Pattern 28
**Rule:** price_vs_session_avwap_pct_bin == 0 AND spy_ret_60m_bin == 4
**Direction:** SHORT
**T-Statistic:** 16.80 (p=0.00e+00)
**Expectancy:** 0.0149% per trade
**Win Rate:** 48.0%
**Profit Factor:** 1.13
**Sharpe Ratio:** 0.58
**Avg Win:** 0.2679% | **Avg Loss:** 0.2183%
**Samples:** 208794 trades

## Pattern 29
**Rule:** ret_60m_bin == 3.0 AND price_vs_session_avwap_pct_bin == 0
**Direction:** SHORT
**T-Statistic:** 16.51 (p=0.00e+00)
**Expectancy:** 0.0117% per trade
**Win Rate:** 50.1%
**Profit Factor:** 1.14
**Sharpe Ratio:** 0.62
**Avg Win:** 0.1854% | **Avg Loss:** 0.1626%
**Samples:** 179819 trades


---

# LLM Analysis

## Pattern 16
**Analysis**: Pattern 16 recommends going short during the power hour when the 60-minute return of the SPY is in the top bin. The rule likely capitalizes on end-of-day volatility and potential reversion to the mean after strong SPY moves. The rule is clearly statistically significant with a t-stat of 26.9. It has a moderate expectancy of 0.0614% which should provide a meaningful return after costs. The profit factor is slightly below our threshold at 1.43, and the Sharpe ratio is above 1, indicating a decent risk-adjusted return. With 101,080 trades, this pattern seems to strike a good balance of size and frequency.

**Go/No-Go Decision**: Recommend Approval. This pattern is statistically strong, has a reasonably Justifiable economic rationale, and seems tradable in practice.

## Pattern 19
**Analysis**: Pattern 19 recommends going short in the first hour when the 60-minute return of the SPY is in the third bin. It takes advantage of the market open volatility but exhibits a lower profit factor (1.16) and Sharpe ratio (0.85), compared to our thresholds. Although its t-stat indicates statistical significance, its low expectancy will hardly survive transaction costs, making it economically unfeasible.

**Go/No-Go Decision**: Reject. Low profit factor, expectancy and Sharpe ratio, make this pattern economically unfeasible.

## Pattern 27
**Analysis**: Pattern 27 uses the ATR (Average True Range, a volatility measure) and the power hour for short trades. It likely targets illiquid, highly volatile stocks that may revert towards the end of the session. Despite its relatively high t-stat, it has a moderate expectancy that could be wiped out by transaction costs, and a low Sharpe ratio of 0.74. Combined with a low profit factor of 1.19, this pattern isn't compelling.

**Go/No-Go Decision**: Reject. Profit factor and Sharpe ratio are below thresholds, expectancy may not survive transaction costs.

## Pattern 28
**Analysis**: Pattern 28 goes short when the stock is below its volume weighted average price and the SPY has made top bin returns. It likely targets reversion after a strong SPY run. However, the low expectancy, Sharpe ratio, and profit factor suggest that the potential gains of this rule may not compensate for its risks.

**Go/No-Go Decision**: Reject. Low expectancy, profit factor and Sharpe ratio make this pattern economically unfeasible.

## Pattern 29
**Analysis**: Pattern 29 again targets reversion, going short after a strong stock run when the price is below the average VWAP. However, it suffers from a similar problem as Pattern 28, with low expectancy, profit factor, and Sharpe ratio indicating minimal economic benefits.

**Go/No-Go Decision**: Reject. Low expectancy, profit factor and Sharpe ratio make this pattern unattractive for trading. 

Overall, based on the analysis, only Pattern 16 seems to offer a decently robust and economically feasible trading pattern.