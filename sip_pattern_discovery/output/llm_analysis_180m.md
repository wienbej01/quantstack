# Pattern Analysis Report

**Target:** up_180m
**Horizon:** 180 minutes
**Patterns analyzed:** 20

---

# Discovered Patterns for Target: up_180m

Total patterns found: 87
Showing top 20 patterns

## Pattern 1
**Rule:** atr_14_bin == 4 AND is_power_hour_bin == True
**Lift:** 5.86x
**Support:** 2.30% (151449 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 2
**Rule:** ret_60m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 5.40x
**Support:** 2.59% (170720 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 3
**Rule:** ret_30m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 5.17x
**Support:** 2.65% (174667 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 4
**Rule:** price_vs_vwap_pct_bin == 4 AND is_power_hour_bin == True
**Lift:** 5.01x
**Support:** 2.65% (174195 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 5
**Rule:** ret_60m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 4.93x
**Support:** 2.47% (162456 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 6
**Rule:** ret_15m_bin == 4.0 AND is_power_hour_bin == True
**Lift:** 4.86x
**Support:** 2.72% (179210 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 7
**Rule:** ret_30m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 4.78x
**Support:** 2.63% (172880 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 8
**Rule:** price_vs_vwap_pct_bin == 0 AND is_power_hour_bin == True
**Lift:** 4.69x
**Support:** 2.64% (173429 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 9
**Rule:** ret_15m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 4.61x
**Support:** 2.73% (179373 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 10
**Rule:** ret_5m_bin == 3.0 AND is_power_hour_bin == True
**Lift:** 4.48x
**Support:** 2.91% (191517 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 11
**Rule:** ret_5m_bin == 0.0 AND is_power_hour_bin == True
**Lift:** 4.41x
**Support:** 2.93% (192659 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 12
**Rule:** atr_14_bin == 3 AND is_power_hour_bin == True
**Lift:** 4.35x
**Support:** 3.54% (233064 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 13
**Rule:** rvol_bin == 4 AND is_power_hour_bin == True
**Lift:** 4.16x
**Support:** 3.11% (204612 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 14
**Rule:** price_vs_session_avwap_pct_bin == 4 AND is_power_hour_bin == True
**Lift:** 4.16x
**Support:** 3.55% (233274 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 15
**Rule:** rvol_bin == 3 AND is_power_hour_bin == True
**Lift:** 4.02x
**Support:** 3.76% (247244 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 16
**Rule:** price_vs_session_avwap_pct_bin == 0 AND is_power_hour_bin == True
**Lift:** 3.72x
**Support:** 3.05% (200760 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 17
**Rule:** rvol_bin == 2 AND is_power_hour_bin == True
**Lift:** 3.69x
**Support:** 3.46% (227441 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 18
**Rule:** is_first_hour_bin == False AND is_power_hour_bin == True
**Lift:** 3.47x
**Support:** 15.26% (1003939 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 19
**Rule:** is_power_hour_bin == True
**Lift:** 3.47x
**Support:** 15.26% (1003939 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%

## Pattern 20
**Rule:** price_vs_session_avwap_pct_bin == 2 AND is_power_hour_bin == True
**Lift:** 3.30x
**Support:** 2.74% (180145 samples)
**P-value:** 0.00e+00
**Baseline rate:** 1.73%


---

# LLM Analysis

## Pattern 1
**Market microstructure explanation**: High average true range (ATR) during the power hour (last hour of the trading session) might indicate strong volatility, which could forecast movements in the next 180 minutes. 

**Risk factors**: If overall market volatility decreases or the power hour stops being a period of high-volume trading, this pattern could become invalid.

**Confidence rating**: High - Given the high lift, low p-value, and logical coherence. 

**Implementation notes**: Traders should balance potential returns against costs, such as bid-ask spread and potential slippage in periods of high volatility.

## Pattern 2 
**Market microstructure explanation**: Large returns over the last 60 minutes during the power hour might drive momentum trading and predict higher returns in the next 180 minutes.

**Risk factors**: Risk lies in an unexpected news event or significant market reversal. In these cases, trend-following strategies based on recent returns could underperform.

**Confidence rating**: High - Provided there is high lift, low p-value, and a strong theoretical underpinning in momentum trading.

**Implementation notes**: Ensure that enough liquidity exists when following this pattern to avoid excessive slippage.

## Pattern 15 
**Market microstructure explanation**: High relative volume during the power hour may signal large institutional trading activities, potentially driving price movement in the next 180 minutes.

**Risk factors**: If market dynamics shift, such as a decrease in institutional trading during the power hour, this pattern may become less predictive.

**Confidence rating**: High - Given the high lift, low p-value, and a reasonable connection with trading volume and future price moves.

**Implementation notes**: Have strategies to manage the potential impact on trading cost due to higher trading volume. 

Based on these insights, I would recommend Patterns 1, 2, and 15 to be developed into a fully systematic trading strategy for backtesting. We should be aware that all strategies will have periods of underperformance and therefore, risk management preparations should be in place for those periods.