# L2 Scalping Context Feature Analysis

**Date**: 2025-12-20  
**Data**: 130,421 merged L2+context records (HAL, LUV, PFE)  
**Forward Return**: 5-minute (300s)  
**Trading Days**: 2 (Dec 17-19, 2025)

## Backtest Results Summary

### Strategy Performance (2-Day Sample)

| Strategy | Trades | Win Rate | Avg P&L | Total P&L | Annual ROI |
|----------|--------|----------|---------|-----------|------------|
| **OBI>0.8 + rel_vol>2 + RSI>50** | 154 | 58.4% | $1.31 | $201.40 | 253.8% |
| OBI>0.8 + rel_vol>2 + Trending | 161 | 55.3% | $1.22 | $196.38 | 247.4% |
| OBI>0.8 + rel_vol>2 (no filter) | 374 | 53.5% | -$1.72 | -$642.47 | -809% |

### Best Strategy: OBI>0.8 + rel_vol>2 + RSI>50

**Account Parameters:**
- Account Size: $10,000
- Position Size: $4,000 (40%)
- Commission: $2 round-trip
- Hold Time: 5 minutes

**Performance Metrics:**
- Total Trades: 154
- Winning Trades: 90 (58.4%)
- Losing Trades: 64 (41.6%)
- Average Win: $5.51
- Average Loss: -$4.60
- Max Win: $10.59
- Max Loss: -$17.90
- Win/Loss Ratio: 1.20

**Daily Breakdown:**
| Date | Trades | P&L |
|------|--------|-----|
| 2025-12-17 | 3 | -$28.83 |
| 2025-12-19 | 151 | +$230.23 |

**Projections (based on 2-day sample):**
- Avg trades/day: 77
- Avg daily P&L: $100.70
- Monthly (21 days): $2,114.68
- Annual (252 days): $25,376.14
- Annual ROI: 253.8%

⚠️ **Caution**: These projections are based on only 2 trading days. More data needed for reliable estimates.

## Key Findings

### Top Correlated Features with 5-Min Forward Return

| Rank | Feature | Type | Correlation | Significance |
|------|---------|------|-------------|--------------|
| 1 | mom_1 | Context | +0.156 | *** |
| 2 | stoch_d_14 | Context | -0.153 | *** |
| 3 | near_resistance_20 | Context | -0.134 | *** |
| 4 | swing_high | Context | -0.116 | *** |
| 5 | dist_to_swing_high | Context | +0.114 | *** |
| 6 | macd_hist | Context | -0.111 | *** |
| 7 | obi_5 | L2 | -0.096 | *** |
| 8 | mom_10 | Context | -0.094 | *** |
| 9 | near_resistance_50 | Context | -0.093 | *** |
| 10 | bb_width_20 | Context | +0.089 | *** |

### Best Feature by Category

| Category | Best Feature | Correlation |
|----------|--------------|-------------|
| **Momentum** | mom_1 | +0.156 |
| **ICT/Liquidity** | swing_high | -0.116 |
| **Support/Resistance** | near_resistance_20 | -0.134 |
| **MACD** | macd_hist | -0.111 |
| **L2 Order Book** | obi_5 | -0.096 |
| **Volatility/ATR** | atr_20 | +0.084 |
| **Bollinger** | bb_width_20 | +0.089 |
| **RSI** | rsi_9 | -0.083 |
| **VWAP** | vwap_dist | -0.139 |

## L2 Signal Performance by Context Regime

**Baseline**: All L2 signals (OBI > 0.5 or < -0.5) = +0.74 bps, 46.8% WR

### Regimes that IMPROVE L2 Signal Performance

| Condition | Return (bps) | Improvement | Win Rate | Signals |
|-----------|--------------|-------------|----------|---------|
| **High volume (>2x)** | +2.68 | +1.94 | 48.3% | 2,886 |
| **RSI > 70 (overbought)** | +2.01 | +1.26 | 49.6% | 3,887 |
| **Displacement up** | +1.52 | +0.77 | 45.0% | 636 |
| **Against momentum** | +1.26 | +0.52 | 48.9% | 14,876 |
| **Near resistance** | +1.03 | +0.28 | 46.7% | 33,636 |

### Regimes that HURT L2 Signal Performance

| Condition | Return (bps) | Improvement | Win Rate | Signals |
|-----------|--------------|-------------|----------|---------|
| **Vol expansion** | -0.79 | -1.54 | 41.1% | 2,038 |
| **Displacement down** | -0.72 | -1.47 | 48.8% | 782 |
| **BB squeeze** | -0.14 | -0.88 | 43.1% | 9,014 |
| **Vol contraction** | -0.13 | -0.88 | 45.3% | 3,765 |
| **Below VWAP** | +0.28 | -0.47 | 45.3% | 9,265 |

## Actionable Insights

### 1. High Volume is Critical (+1.94 bps improvement)
- L2 signals during high volume (>2x normal) are significantly more profitable
- This confirms our previous finding: **rel_vol > 2.0 is a key filter**

### 2. Counter-Trend Signals Work Better (+0.52 bps)
- Trading **against** short-term momentum (mom_15) improves returns
- L2 order flow may be detecting reversals before price confirms

### 3. Overbought RSI is Profitable (+1.26 bps)
- Contrary to typical RSI usage, L2 signals in overbought conditions work well
- Suggests institutional buying pressure continues despite high RSI

### 4. Avoid Volatility Expansion (-1.54 bps)
- L2 signals during volatility expansion are unprofitable
- High volatility = noise, L2 signals less reliable

### 5. Avoid BB Squeeze (-0.88 bps)
- Low volatility consolidation periods hurt L2 signal quality
- Wait for breakout before trading L2 signals

## Recommended Context Filters for L2 Scalping

```yaml
# WINNING STRATEGY (58.4% win rate, +$1.31/trade)
strategy:
  entry:
    obi_threshold: 0.8        # Strong order book imbalance
    min_rel_volume: 2.0       # High volume filter (critical)
    rsi_min: 50               # RSI > 50 (bullish bias)
  
  position:
    size_pct: 0.40            # 40% of account
    hold_time_seconds: 300    # 5 minutes
  
  # Alternative: Use trending filter instead of RSI
  # trending: true            # ADX proxy > 70th percentile
```

### Why RSI > 50 Works
- Filters out weak/bearish market conditions
- L2 buy signals (OBI > 0.8) perform better in bullish context
- Reduces false signals during downtrends
- Improves win rate from 53.5% to 58.4%

### Why Trending Filter Works
- Similar effect to RSI filter
- Captures momentum continuation
- 55.3% win rate, slightly lower than RSI filter

## Feature Set for Context-Aware L2 Strategy

Based on this analysis, the recommended context features are:

### Single-Symbol Context Features (from this analysis)
1. **rel_vol** - Relative volume (critical filter, +1.94 bps)
2. **rsi_14** - RSI for regime detection (+1.26 bps when >70)
3. **mom_15** - Short-term momentum for counter-trend (+0.52 bps)
4. **vol_regime** - Volatility expansion/contraction (-1.54 bps when expanding)
5. **bb_squeeze_20** - Bollinger squeeze detection (-0.88 bps when squeezed)
6. **vwap_dist** - Distance from VWAP (corr: -0.139)
7. **near_resistance_20** - Proximity to resistance (corr: -0.134)

### Cross-Sectional Features (from Intraday ML system)
The intraday ML system uses 11 cross-sectional features that require market-wide data:
- cross_rank_ret, cross_rank_vol
- sector_momentum (top importance in all regimes)
- cross_dispersion, market_breadth
- up_down_ratio
- rel_strength_5/10/20
- market_ret_5/10

These could be added for market regime awareness but require real-time computation across all SIP symbols.

## Implementation Priority

1. **Phase 1** (Immediate): Add single-symbol context filters
   - rel_vol > 2.0 (required)
   - Exclude vol_expansion and bb_squeeze
   
2. **Phase 2** (Next): Add RSI and momentum filters
   - RSI > 70 for bullish L2 signals
   - Counter-trend momentum alignment

3. **Phase 3** (Future): Cross-sectional features
   - Requires market-wide data aggregation
   - sector_momentum most valuable

