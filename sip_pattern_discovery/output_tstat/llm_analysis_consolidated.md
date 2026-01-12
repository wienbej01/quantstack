# Consolidated Pattern Analysis Report

**Patterns analyzed:** 30
**Horizons:** 30m, 60m, 90m, 180m
**Directions:** LONG, SHORT

---

# Consolidated Pattern Analysis

Total patterns: 30 (top by t-stat)
Horizons: 30m, 60m, 90m, 180m
Directions: LONG, SHORT

## Power Hour Patterns (3-4 PM)

*1 patterns in this category*

### SHORT 30m: is_power_hour_bin == True
- T-stat: 25.7 | Expectancy: 0.011%
- Win Rate: 46.0% | Profit Factor: 1.22 | Sharpe: 0.65
- Samples: 392,051 observations

## First Hour Patterns (9:30-10:30 AM)

*16 patterns in this category*

### LONG 180m: ret_60m_bin == 4.0 AND is_first_hour_bin == True
- T-stat: 34.3 | Expectancy: 0.054%
- Win Rate: 52.6% | Profit Factor: 1.27 | Sharpe: 1.42
- Samples: 147,738 observations

### SHORT 90m: is_first_hour_bin == True
- T-stat: 32.2 | Expectancy: 0.019%
- Win Rate: 52.3% | Profit Factor: 1.21 | Sharpe: 1.09
- Samples: 219,937 observations

### SHORT 180m: is_first_hour_bin == True
- T-stat: 30.2 | Expectancy: 0.024%
- Win Rate: 52.1% | Profit Factor: 1.19 | Sharpe: 1.02
- Samples: 219,937 observations

### SHORT 60m: is_first_hour_bin == True
- T-stat: 29.8 | Expectancy: 0.015%
- Win Rate: 51.5% | Profit Factor: 1.19 | Sharpe: 1.01
- Samples: 219,937 observations

### LONG 180m: session_range_pct_bin == 4 AND is_first_hour_bin == True
- T-stat: 29.4 | Expectancy: 0.047%
- Win Rate: 52.2% | Profit Factor: 1.27 | Sharpe: 1.39
- Samples: 112,496 observations

### LONG 180m: rel_strength_60m_bin == 4.0 AND is_first_hour_bin == True
- T-stat: 28.2 | Expectancy: 0.050%
- Win Rate: 52.9% | Profit Factor: 1.27 | Sharpe: 1.36
- Samples: 108,333 observations

### SHORT 90m: price_vs_vwap_pct_bin == 4 AND is_first_hour_bin == True
- T-stat: 27.9 | Expectancy: 0.034%
- Win Rate: 54.4% | Profit Factor: 1.36 | Sharpe: 1.76
- Samples: 63,258 observations

### LONG 60m: is_first_hour_bin == True
- T-stat: 27.6 | Expectancy: 0.013%
- Win Rate: 50.1% | Profit Factor: 1.11 | Sharpe: 0.60
- Samples: 540,124 observations

### LONG 90m: is_first_hour_bin == True
- T-stat: 27.3 | Expectancy: 0.015%
- Win Rate: 50.5% | Profit Factor: 1.11 | Sharpe: 0.59
- Samples: 540,124 observations

### LONG 90m: ret_60m_bin == 4.0 AND is_first_hour_bin == True
- T-stat: 27.2 | Expectancy: 0.032%
- Win Rate: 51.6% | Profit Factor: 1.22 | Sharpe: 1.12
- Samples: 147,738 observations

### SHORT 60m: price_vs_vwap_pct_bin == 4 AND is_first_hour_bin == True
- T-stat: 26.6 | Expectancy: 0.027%
- Win Rate: 53.6% | Profit Factor: 1.34 | Sharpe: 1.68
- Samples: 63,258 observations

### SHORT 90m: ret_60m_bin == 4.0 AND is_first_hour_bin == True
- T-stat: 26.2 | Expectancy: 0.032%
- Win Rate: 54.4% | Profit Factor: 1.34 | Sharpe: 1.67
- Samples: 62,160 observations

### LONG 90m: rel_strength_60m_bin == 0.0 AND is_first_hour_bin == True
- T-stat: 26.1 | Expectancy: 0.023%
- Win Rate: 52.2% | Profit Factor: 1.24 | Sharpe: 1.25
- Samples: 109,421 observations

### SHORT 60m: ret_60m_bin == 4.0 AND is_first_hour_bin == True
- T-stat: 25.9 | Expectancy: 0.026%
- Win Rate: 53.4% | Profit Factor: 1.33 | Sharpe: 1.65
- Samples: 62,160 observations

### SHORT 90m: price_up_vol_weak_bin == True AND is_first_hour_bin == True
- T-stat: 25.9 | Expectancy: 0.040%
- Win Rate: 55.3% | Profit Factor: 1.50 | Sharpe: 2.38
- Samples: 29,897 observations

### LONG 60m: price_vs_vwap_pct_bin == 0 AND is_first_hour_bin == True
- T-stat: 25.7 | Expectancy: 0.026%
- Win Rate: 52.4% | Profit Factor: 1.21 | Sharpe: 1.06
- Samples: 147,913 observations

## Price vs VWAP Patterns

*1 patterns in this category*

### LONG 60m: price_vs_vwap_pct_bin == 0
- T-stat: 26.8 | Expectancy: 0.024%
- Win Rate: 51.8% | Profit Factor: 1.21 | Sharpe: 0.90
- Samples: 221,132 observations

## Volatility (ATR) Patterns

*4 patterns in this category*

### LONG 180m: atr_14_bin == 0
- T-stat: 49.0 | Expectancy: 0.018%
- Win Rate: 50.3% | Profit Factor: 1.24 | Sharpe: 1.11
- Samples: 494,261 observations

### LONG 180m: rvol_bin == 0 AND atr_14_bin == 0
- T-stat: 32.6 | Expectancy: 0.019%
- Win Rate: 50.5% | Profit Factor: 1.26 | Sharpe: 1.16
- Samples: 199,919 observations

### LONG 180m: rel_strength_60m_bin == 4.0 AND atr_14_bin == 0
- T-stat: 26.3 | Expectancy: 0.025%
- Win Rate: 54.0% | Profit Factor: 1.35 | Sharpe: 1.65
- Samples: 64,382 observations

### LONG 90m: rel_strength_60m_bin == 4.0 AND atr_14_bin == 0
- T-stat: 25.9 | Expectancy: 0.016%
- Win Rate: 51.8% | Profit Factor: 1.32 | Sharpe: 1.62
- Samples: 64,394 observations

## Momentum/Return Patterns

*2 patterns in this category*

### LONG 180m: ret_60m_bin == 4.0 AND session_range_pct_bin == 4
- T-stat: 31.3 | Expectancy: 0.063%
- Win Rate: 52.8% | Profit Factor: 1.34 | Sharpe: 1.66
- Samples: 89,409 observations

### LONG 180m: ret_60m_bin == 3.0 AND rel_strength_60m_bin == 4.0
- T-stat: 27.8 | Expectancy: 0.029%
- Win Rate: 54.5% | Profit Factor: 1.33 | Sharpe: 1.49
- Samples: 87,870 observations

## Other Patterns

*6 patterns in this category*

### LONG 180m: session_range_pct_bin == 4
- T-stat: 38.8 | Expectancy: 0.022%
- Win Rate: 51.2% | Profit Factor: 1.21 | Sharpe: 0.88
- Samples: 494,058 observations

### LONG 180m: rvol_bin == 0
- T-stat: 38.7 | Expectancy: 0.018%
- Win Rate: 50.6% | Profit Factor: 1.21 | Sharpe: 0.87
- Samples: 494,000 observations

### LONG 180m: rel_strength_60m_bin == 0.0 AND session_range_pct_bin == 4
- T-stat: 35.9 | Expectancy: 0.041%
- Win Rate: 54.9% | Profit Factor: 1.51 | Sharpe: 2.15
- Samples: 70,106 observations

### LONG 180m: rel_outperform_extreme_bin == True AND session_range_pct_bin == 0
- T-stat: 35.6 | Expectancy: 0.316%
- Win Rate: 80.9% | Profit Factor: 4.26 | Sharpe: 8.97
- Samples: 3,964 observations

### LONG 180m: session_range_pct_bin == 4
- T-stat: 27.9 | Expectancy: 0.032%
- Win Rate: 50.1% | Profit Factor: 1.19 | Sharpe: 0.94
- Samples: 220,627 observations

### LONG 180m: rel_strength_60m_bin == 4.0
- T-stat: 25.7 | Expectancy: 0.017%
- Win Rate: 52.7% | Profit Factor: 1.15 | Sharpe: 0.67
- Samples: 365,965 observations


---

# LLM Analysis

Based on the given information and approval criteria, the trading patterns can be analyzed as follows:

1. Power Hour Patterns:
   - Economic Rationale: The market often experiences increased volume in the last hour of trading, as traders close out positions, adjust portfolios, or chase the day's momentum. This could potentially provide an opportunity for a short strategy.
   - Best Pattern: SHORT 30m: is_power_hour_bin == True
   - Profitable after costs: Yes, as the expectancy is 0.011% and considering 1 bps slippage, it should yield a positive result.

2. First Hour Patterns:
   - Economic Rationale: The first hour of trading can be volatile due to opening reaction to news events and overnight market movements. Patterns during this period likely leverage this volatility.
   - Best Pattern: LONG 180m: ret_60m_bin == 4.0 AND is_first_hour_bin == True
   - Profitable after costs: Yes, the expectancy is 0.054%, and considering the trading costs, it should still be profitable.

3. Price vs VWAP Patterns:
   - Economic Rationale: VWAP is a common benchmark used by algorithmic traders and institutions to execute trades efficiently. Trading when the price deviates significantly from VWAP leverages this algorithmic trading behavior.
   - Best Pattern: LONG 60m: price_vs_vwap_pct_bin == 0
   - Profitable after costs: Yes, with an expectancy of 0.024%, the trading system still seems to be profitable after costs.

4. Volatility (ATR) Patterns:
   - Economic Rationale: Volatility is a key element for most trading systems. Trading at lower volatility periods could mean that prices are more stable, allowing for safer trades.
   - Best Pattern: LONG 180m: atr_14_bin == 0
   - Profitable after costs: Yes, the expectancy of 0.018% indicates that the trading protocol seems to be profitable after costs.

5. Momentum/Return Patterns:
   - Economic Rationale: Stocks showing strong momentum tend to continue in the same direction in the short term due to herd mentality and algorithmic trading.
   - Best Pattern: LONG 180m: ret_60m_bin == 4.0 AND session_range_pct_bin == 4
   - Profitable after costs: Yes, the high expectancy value of 0.063% suggests a positive outcome after costs.

The best economic rationale theme seems to be Momentum/Return Patterns, followed by First Hour Patterns. A recommended portfolio could include strategies from the Strong Momentum/Return Patterns, First Hour Patterns, and Volatility (ATR) Patterns to maintain economic diversity and exploit different market phenomena.

Two notable patterns that lack clear economic rationale despite having high t-stat are LONG 60m: is_first_hour_bin == True and LONG 90m: is_first_hour_bin == True from First Hour Patterns category. These patterns leverage the volatile first hour but do not include any additional parameters to provide a recognizable market behaviour. 

Further research and optimization could provide additional edges and insights into the profitability and sustainability of these trading patterns.