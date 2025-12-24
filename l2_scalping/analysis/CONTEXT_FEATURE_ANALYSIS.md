# L2 Scalping Context Feature Analysis

**Date**: 2025-12-24  
**Data**: 272,808 L2 records (HAL, LUV, PFE, SLB, XOM)  
**Forward Return**: 5-minute (300s)  
**Trading Days**: 2 (Dec 19 & Dec 23, 2025)

## Backtest Results Summary

### Strategy Performance (5-minute hold)

| Strategy | Trades | Win Rate | Mean Ret (bps) | Avg Gross P&L | Avg Net P&L | Total Net P&L |
|----------|--------|----------|----------------|---------------|-------------|---------------|
| **OBI>0.8 + rel_vol>2 + RSI>50** | 182 | 56.0% | 2.55 | $1.02 | **-$0.98** | **-$178.58** |

**Assumptions**: $10k account, 40% position size ($4k), $2 round-trip commission.  
**Break-even position size** for this strategy: **~$7.9k** (based on 2.55 bps mean return).

### Daily Breakdown (Strategy Trades)

| Date | Trades | Net P&L | Avg Net P&L |
|------|--------|---------|-------------|
| 2025-12-23 | 182 | -$178.58 | -$0.98 |

**Note**: The strict filter produced trades only on Dec 23 in the latest sample.

## L2 Signal Performance by Context Regime (10s baseline)

Baseline (OBI > 0.3): **0.42 bps**, 12.0% win rate

| Condition | Mean Ret (bps) | Win Rate | Signals |
|-----------|----------------|----------|---------|
| With trend | 0.60 | 13.6% | 79,719 |
| Against trend | 0.23 | 10.7% | 67,320 |
| High volume (>1.5x) | 0.59 | 14.6% | 25,817 |
| Low volume (<0.5x) | 0.25 | 5.9% | 31,845 |
| RSI extremes (>=70 or <=30) | 0.69 | 16.7% | 17,204 |
| VWAP favorable | 0.38 | 13.1% | 83,083 |
| VWAP unfavorable | 0.47 | 10.8% | 71,064 |

## Key Findings

1. **High volume remains the best filter** (+0.17 bps vs baseline)
2. **Trading with trend outperforms against trend** (+0.18 bps)
3. **RSI extremes show the strongest uplift**, but sample is smaller
4. **VWAP filters did not improve results** in this sample
5. **Low volume materially degrades performance**

## Recommended Context Filters (Updated)

```yaml
strategy:
  entry:
    obi_threshold: 0.8
    min_rel_volume: 2.0
    rsi_min: 50

  soft_filters:
    prefer_with_trend: true
    avoid_low_volume: true
    rsi_extremes: experimental
```

### Notes
- The 5-minute strategy still **fails after costs at $4k size** despite a 56% win rate.
- Break-even size is **~$7.9k** at 5-minute hold based on current mean return.
- Correlation/feature-importance tables from the prior report were **not rerun** on the expanded dataset.

## Holding Period Sensitivity (Net P&L Positive Only)

Assumptions: $4k position size, $2 commission.

| Strategy | Horizon | Mean Return | Avg Net P&L | Trades |
|----------|---------|-------------|-------------|--------|
| baseline_obi_08 | 900s | 6.84 bps | +$0.73 | 4,682 |
| obi_08_relvol_rsi50 | 600s | 14.19 bps | +$3.67 | 173 |
| obi_08_relvol_rsi50 | 900s | 29.68 bps | +$9.87 | 159 |

## Leverage-Capped Sensitivity (3x Max, 900s Hold)

Assumptions: max gross exposure $30k, FIFO admission, $2 commission.

| Position Size | Trades | Mean Return | Win Rate | Avg Net P&L | Total Net P&L |
|---------------|--------|-------------|----------|-------------|---------------|
| $2,000 | 78 | 8.15 bps | 61.5% | -$0.37 | -$28.87 |
| $4,000 | 42 | 12.28 bps | 78.6% | +$2.91 | +$122.22 |

Rank-replace (score = rel_vol) at $4,000: 51 trades, +$88.98 total net P&L.
