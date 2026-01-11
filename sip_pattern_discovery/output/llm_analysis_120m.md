# Pattern Analysis Report

**Target:** up_120m
**Horizon:** 120 minutes
**Patterns analyzed:** 20

---

# Discovered Patterns for Target: up_120m

Total patterns found: 105
Showing top 20 patterns

## Pattern 1
**Rule:** atr_14_bin == 4 AND is_power_hour_bin == True
**Lift:** 5.90x
**Support:** 2.30% (151449 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 2
**Rule:** ret_60m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 5.19x
**Support:** 2.59% (170720 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 3
**Rule:** ret_30m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 5.06x
**Support:** 2.65% (174667 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 4
**Rule:** price_vs_vwap_pct_bin == 4 AND is_power_hour_bin == True
**Lift:** 4.81x
**Support:** 2.65% (174195 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 5
**Rule:** ret_15m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 4.68x
**Support:** 2.72% (179210 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 6
**Rule:** ret_60m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 4.45x
**Support:** 2.47% (162456 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 7
**Rule:** ret_30m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 4.29x
**Support:** 2.63% (172880 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 8
**Rule:** price_vs_vwap_pct_bin == 0 AND is_power_hour_bin == True
**Lift:** 4.22x
**Support:** 2.64% (173429 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 9
**Rule:** ret_15m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 4.21x
**Support:** 2.73% (179373 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 10
**Rule:** ret_5m_bin == 3.0 AND is_power_hour_bin == True
**Lift:** 4.16x
**Support:** 2.91% (191517 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 11
**Rule:** atr_14_bin == 3 AND is_power_hour_bin == True
**Lift:** 3.92x
**Support:** 3.54% (233064 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 12
**Rule:** ret_5m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 3.88x
**Support:** 2.93% (192659 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 13
**Rule:** rvol_bin == 4 AND is_power_hour_bin == True
**Lift:** 3.69x
**Support:** 3.11% (204612 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 14
**Rule:** rvol_bin == 3 AND is_power_hour_bin == True
**Lift:** 3.68x
**Support:** 3.76% (247244 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 15
**Rule:** ret_30m_bin == 0.0 AND ret_60m_bin == 4.0
**Lift:** 3.60x
**Support:** 0.86% (56406 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 16
**Rule:** price_vs_session_avwap_pct_bin == 4 AND is_power_hour_bin == True
**Lift:** 3.51x
**Support:** 3.55% (233274 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 17
**Rule:** ret_15m_bin == 0.0 AND ret_30m_bin == 4.0
**Lift:** 3.43x
**Support:** 0.87% (57119 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 18
**Rule:** ret_5m_bin == 3.0 AND price_vs_vwap_pct_bin == 0
**Lift:** 3.33x
**Support:** 0.93% (61472 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 19
**Rule:** ret_60m_bin == 4.0 AND atr_14_bin == 4
**Lift:** 3.32x
**Support:** 6.53% (429488 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%

## Pattern 20
**Rule:** rvol_bin == 4 AND atr_14_bin == 4
**Lift:** 3.28x
**Support:** 6.18% (406787 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.69%


---

# LLM Analysis

## Pattern 1
**Market microstructure explanation**: During the power hour, the last hour of trading, and when the average true range (ATR) is high, stocks are more likely to push higher as large institutional investors typically execute orders. When ATR is high, it indicates higher volatility and potentially increased investor activity.
**Risk factors**: Times of low liquidity or sudden market downturns might invalidate this pattern. A decrease in volatility might also affect this pattern.
**Confidence rating**: High due to strong lift, good support, and clear market logic.
**Implementation notes**: As it focuses on high volatility periods during the power trading hour, ensure sufficient liquidity to minimize market impact. Be wary of market stress conditions where the pattern may not hold.

## Pattern 2
**Market microstructure explanation**: This suggests that if there has been a strong return in the last 60 minutes and it's the power hour, there could be continuing momentum.
**Risk factors**: Systemic market downturns, low liquidity, or breaking news can disrupt this pattern.
**Confidence rating**: Medium due to strong lift but the risk of momentum quickly reversing.
**Implementation notes**: Keep stop losses to protect from rapid reversals. Pay attention to risk management and do not rely solely on this pattern.

## Pattern 19
**Market microstructure explanation**: If returns over the past 60 minutes are strong and ATR is high, it potentially depicts a situation of significant upward momentum under increased volatility.
**Risk factors**: Risk of sudden reversal, calming of the market volatility or unexpected news events could invalidate this pattern.
**Confidence rating**: Medium due to higher support but the risk associated with high volatility trading.
**Implementation notes**: Execution might be more challenging due to high volatility. Utilize proper risk management, including stop-loss orders and position size controls.

In general, the patterns seem strong statistically but need to be tested and validated further, ideally in different market conditions. Trade execution needs to be handled carefully, considering the high volatility environment that these patterns tend to occur in. Finally, risk management becomes extra important due to the inherent risks associated with the proposed patterns, which leverage the market's momentum during high volatility periods.