# Pattern Analysis Report

**Target:** fwd_ret_30m
**Horizon:** 30 minutes
**Patterns analyzed:** 2

---

# Discovered Patterns for Target: fwd_ret_30m

Total patterns found: 2
Showing top 2 patterns

## Pattern 26
**Rule:** is_power_hour_bin == True AND spy_ret_60m_bin == 4
**Direction:** SHORT
**T-Statistic:** 20.76 (p=0.00e+00)
**Expectancy:** 0.0294% per trade
**Win Rate:** 48.3%
**Profit Factor:** 1.41
**Sharpe Ratio:** 1.03
**Avg Win:** 0.2110% | **Avg Loss:** 0.1401%
**Samples:** 102089 trades

## Pattern 33
**Rule:** atr_14_bin == 4 AND is_power_hour_bin == True
**Direction:** SHORT
**T-Statistic:** 13.88 (p=0.00e+00)
**Expectancy:** 0.0198% per trade
**Win Rate:** 48.9%
**Profit Factor:** 1.18
**Sharpe Ratio:** 0.57
**Avg Win:** 0.2674% | **Avg Loss:** 0.2174%
**Samples:** 150388 trades


---

# LLM Analysis

**Pattern 26 Analysis:** 

1. **Statistical Significance**: The t-statistic (20.76, p=0.00) suggests the pattern is not random with high confidence. 

2. **Expectancy Analysis**: The pattern's expectancy is 0.0294%, above the 0.02% threshold. After accounting for typical slippage and commissions, the pattern is likely still profitable although likely to shrink. A Sharpe ratio of 1.03 suggests a reasonable edge.

3. **Win Rate vs Profit Factor**: Moderate win rate (48.3%) with profit factor of 1.41. This suggests a marginally profitable yet resilient pattern with average wins bigger than average losses.

4. **Sample Size Validation**: With a large 102089 trade sample size, it provides adequate confidence in the pattern robustness.

5. **Regime Robustness**: The rule seems to exploit a combination of power hour and SPY price pattern, which has plausible economic rationale (e.g. end-of-day trading volume surge). The pattern does not appear market-regime dependent.

6. **Go/No-go Decision**: Even though the profit factor is a bit below the ideal threshold (1.5), the overall pattern performance and rationale suggest the pattern is worth investigating further.
    - **DEcision: GO**.


**Pattern 33 Analysis:**

1. **Statistical Significance**: The t-statistic is high (13.88, p=0.00), the pattern is non-random.

2. **Expectancy Analysis**: Expectancy is slightly below our threshold (0.0198%), but it could turn unprofitable when transaction costs are considered. The Sharpe Ratio is also quite low (0.57), suggesting a rather low risk-adjusted return.

3. **Win Rate vs Profit Factor**: Win Rate is moderate (48.9%) but profit factor is low (1.18). This suggests that the pattern's winners aren't distinctly larger than its losers.

4. **Sample Size Validation**: High sample size of 150388 trades, suggesting that the pattern is not rare at all.

5. **Regime Robustness**: The condition involves high ATR and is during power hour, which could be reflecting traders' behavior at the end of the trading session combined with volatile market situations. It's a rule that could potentially hold up across regimes.

6. **Go/No-go Decision**: While there is a plausible economic rationale, the low expectancy and profit factor combined with high sensitivity to transaction costs suggest this pattern isn't practical for trading.
    - **Decision: NO-GO**.

Overall, Pattern 26 appears to have a sustainable edge, while Pattern 33 doesn't look promising for practical trading.