# Pattern Analysis Report

**Target:** up_60m
**Horizon:** 60 minutes
**Patterns analyzed:** 20

---

# Discovered Patterns for Target: up_60m

Total patterns found: 109
Showing top 20 patterns

## Pattern 1
**Rule:** atr_14_bin == 4 AND is_power_hour_bin == True
**Lift:** 4.74x
**Support:** 2.30% (151449 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 2
**Rule:** ret_30m_bin == 0.0 AND ret_60m_bin == 4.0
**Lift:** 4.05x
**Support:** 0.86% (56406 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 3
**Rule:** ret_60m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 3.90x
**Support:** 2.59% (170720 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 4
**Rule:** ret_5m_bin == 3.0 AND price_vs_vwap_pct_bin == 0
**Lift:** 3.77x
**Support:** 0.93% (61472 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 5
**Rule:** ret_15m_bin == 0.0 AND ret_30m_bin == 4.0
**Lift:** 3.73x
**Support:** 0.87% (57119 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 6
**Rule:** atr_14_bin == 4 AND is_first_hour_bin == True
**Lift:** 3.61x
**Support:** 11.00% (723914 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 7
**Rule:** ret_5m_bin == 0.0 AND price_vs_vwap_pct_bin == 4
**Lift:** 3.60x
**Support:** 0.90% (59369 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 8
**Rule:** ret_60m_bin == 4.0 AND atr_14_bin == 4
**Lift:** 3.59x
**Support:** 6.53% (429488 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 9
**Rule:** ret_30m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 3.58x
**Support:** 2.65% (174667 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 10
**Rule:** rvol_bin == 4 AND is_first_hour_bin == True
**Lift:** 3.56x
**Support:** 4.52% (297494 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 11
**Rule:** ret_60m_bin == 4.0 AND price_vs_vwap_pct_bin == 0
**Lift:** 3.56x
**Support:** 1.42% (93750 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 12
**Rule:** ret_15m_bin == 4.0 AND ret_30m_bin == 0.0
**Lift:** 3.53x
**Support:** 0.90% (59024 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 13
**Rule:** rvol_bin == 4 AND atr_14_bin == 4
**Lift:** 3.46x
**Support:** 6.18% (406787 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 14
**Rule:** ret_15m_bin == 0.0 AND ret_60m_bin == 4.0
**Lift:** 3.39x
**Support:** 1.86% (122674 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 15
**Rule:** ret_5m_bin == 0.0 AND atr_14_bin == 4
**Lift:** 3.33x
**Support:** 5.53% (363667 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 16
**Rule:** ret_30m_bin == 4.0 AND atr_14_bin == 4
**Lift:** 3.32x
**Support:** 6.83% (449640 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 17
**Rule:** price_vs_vwap_pct_bin == 4 AND is_power_hour_bin == True
**Lift:** 3.28x
**Support:** 2.65% (174195 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 18
**Rule:** ret_5m_bin == 3.0 AND ret_15m_bin == 0.0
**Lift:** 3.28x
**Support:** 1.28% (84273 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 19
**Rule:** ret_30m_bin == 4.0 AND ret_60m_bin == 0.0
**Lift:** 3.27x
**Support:** 0.92% (60262 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%

## Pattern 20
**Rule:** price_vs_vwap_pct_bin == 0 AND atr_14_bin == 4
**Lift:** 3.26x
**Support:** 6.99% (460227 samples)
**P-value:** 0.00e+00
**Baseline rate:** 2.06%


---

# LLM Analysis

## Pattern 1
**Rule:** atr_14_bin == 4 AND is_power_hour_bin == True

1. **Market microstructure explanation:** This pattern suggests that during a high volatility period (atr_14_bin == 4), when trading in the power hour (the last hour of trading when volume is typically higher), the stock is likely to have positive 60-minute forward returns. The reasoning could be that when market volatility is high in power hour, it leads to increased buying activity which drives the price up.
2. **Risk factors:** Periods of low market volume or a changed market regime such as recession or a low volatility phase may invalidate this pattern.
3. **Confidence rating:** High - Given the high lift and support, this pattern appears to have significant predictive power.
4. **Implementation notes:** Transaction cost and slippage could be a concern due to higher volatility. 

## Pattern 2
**Rule:** ret_30m_bin == 0.0 AND ret_60m_bin == 4.0
1. **Market microstructure explanation:** Might suggest reversal - poor 30min returns followed by strong 60min returns. Investors may perceive the initial poor returns as an overreaction, causing a positive price correction.
2. **Risk factors:** If the fundamental conditions of the stock deteriorate, this pattern may not hold.
3. **Confidence rating:** Medium - The lift is significant, but the support is relatively low.
4. **Implementation notes:** Adequate liquidity management will be essential due to the potential for volatility in these scenarios.

## Pattern 3
**Rule:** ret_60m_bin == 4.0 AND is_power_hour_bin == True
1. **Market microstructure explanation:** This reinforces the idea that strong returns often occur in the power hour of trading. Market participants, after observing strong 60 minute returns, usually continue the buying in the expectation of further rise.
2. **Risk factors:** Outside of strong market hours, this pattern may become ineffective. Major news events may also disrupt the pattern.
3. **Confidence rating:** High - The lift is quite high, and the support is significant.
4. **Implementation notes:** As this pattern involves high return and power hour, both high volatility and volume scenario, one can consider higher size trades but should manage slippage.

The majority of the patterns seem viable, especially the ones with large support and lift. Patterns with rules that are understood based on market behaviours should be prioritized. Patterns that seem spurious and are difficult to provide a rational explanation for, should be handled with caution as they may be overfitted or coincidental.