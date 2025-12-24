# L2 Scalping Feature Analysis Report

**Date**: 2025-12-24  
**Data**: 272,808 L2 records across 5 symbols (HAL, LUV, PFE, SLB, XOM) on Dec 19 & Dec 23, 2025

## Executive Summary

### Critical Finding: Commission Costs Still Dominate

At $2 round-trip commission, **no strategy is profitable at $5k-$15k position sizes** for 15-30 second holds in the latest sample.

Best 30s strategy: `extreme_obi_trend` (gross 1.14 bps)

| Position Size | Gross P&L/Trade | Net P&L/Trade |
|---------------|-----------------|---------------|
| $5,000 | $0.57 | **-$1.43** |
| $10,000 | $1.14 | **-$0.86** |
| $15,000 | $1.71 | **-$0.29** |
| $20,000 | $2.29 | **+$0.29** |

**Break-even position size: ~$17.5k (30s)**  
**15s break-even: ~$22.8k**

## Strategy Performance (30s Horizon)

| Strategy | Gross Return | Win Rate | Signals/Day |
|----------|--------------|----------|-------------|
| extreme_obi_trend | 1.14 bps | 41.2% | 9,031 |
| high_conviction | 1.11 bps | 42.0% | 5,478 |
| extreme_obi_07 | 0.93 bps | 42.3% | 6,349 |
| multi_obi_strong | 0.88 bps | 38.2% | 1,624 |
| extreme_obi_06 | 0.80 bps | 39.6% | 10,340 |

## Context Features as Regime Filters

Context features should be used for **awareness**, not signal generation:

### Trend Alignment
- **With trend**: 0.60 bps mean return, 13.6% win rate
- **Against trend**: 0.23 bps mean return, 10.7% win rate
- **Recommendation**: Prefer trading with 15-bar momentum direction

### VWAP Position (Support/Resistance)
- Favorable VWAP did **not** outperform in this sample (0.38 bps vs 0.47 bps)
- **Recommendation**: Treat VWAP as informational only

### Volume Regime
- High volume (>1.5x): 0.59 bps, 14.6% win rate
- Low volume (<0.5x): 0.25 bps, 5.9% win rate
- **Recommendation**: Prefer high-volume periods and avoid low-volume windows

### RSI Regime
- RSI extremes performed best (0.69 bps, 16.7% win rate)
- **Recommendation**: Experimental only; do not hard-gate without more data

## Recommendations for Profitability

### Option 1: Larger Position Sizes
- **Minimum ~$17.5k per trade** for 30s holds to break even on $2 commission
- 15s holds require **~$22.8k**
- Risk: Larger drawdowns on losing trades

### Option 2: Reduce Trade Frequency
- Extreme OBI thresholds reduce noise but remain cost-negative at $5k
- Use high conviction signals if size cannot be increased

### Option 3: Longer Hold Times
- 30s > 15s in this sample
- 600-900s holds show positive net P&L for the strict filter
- 60-300s holds remain net negative at $4k size

### Option 4: Lower-Cost Execution
- Sub-$1 round trip would materially reduce break-even size
- Most impactful lever for profitability

## Updated Signal Logic

```python
def should_trade(snapshot, context):
    # 1. High conviction L2 signal (OBI > 0.7)
    if abs(snapshot.obi_1) < 0.7:
        return False

    # 2. Context awareness (soft filters)
    with_trend = (
        (snapshot.obi_1 > 0 and context.mom_15 > 0) or
        (snapshot.obi_1 < 0 and context.mom_15 < 0)
    )
    high_volume = context.rel_vol > 1.5

    # RSI extremes are promising but unproven
    rsi_extreme = (context.rsi_14 >= 70) or (context.rsi_14 <= 30)

    # 3. Position sizing based on conviction
    if with_trend and high_volume:
        position_size = 20000
    elif with_trend or high_volume or rsi_extreme:
        position_size = 17500
    else:
        position_size = 10000

    return position_size >= 17500
```

## Key Insights

1. **L2 signals still show predictive power** (0.4-0.7 bps at 10-30s)
2. **Commission costs dominate**; break-even size increased to ~$17.5k
3. **High volume + trend alignment** provide the most consistent uplift
4. **RSI extremes show promise** but need more validation
5. **Position sizing is critical** to achieving net profitability

## Holding Period Sensitivity (Net P&L Positive Only)

Assumptions: $4k position size, $2 commission.

| Strategy | Horizon | Mean Return | Avg Net P&L | Trades |
|----------|---------|-------------|-------------|--------|
| baseline_obi_08 | 900s | 6.84 bps | +$0.73 | 4,682 |
| obi_08_relvol_rsi50 | 600s | 14.19 bps | +$3.67 | 173 |
| obi_08_relvol_rsi50 | 900s | 29.68 bps | +$9.87 | 159 |

## Leverage-Capped Results (3x Max, 900s Hold)

Assumptions: max gross exposure $30k, FIFO admission, $2 commission.

| Strategy | Position Size | Trades | Mean Return | Win Rate | Avg Net P&L | Total Net P&L |
|----------|---------------|--------|-------------|----------|-------------|---------------|
| obi_08_relvol_rsi50 | $2,000 | 78 | 8.15 bps | 61.5% | -$0.37 | -$28.87 |
| obi_08_relvol_rsi50 | $4,000 | 42 | 12.28 bps | 78.6% | +$2.91 | +$122.22 |

Rank-replace (score = rel_vol) at $4,000 also remains positive: 51 trades, +$88.98 total net P&L.

## Files Generated

- `analysis/output/analysis_results_20251224_122926.csv` - L2-only vs L2+context
- `analysis/output/cost_adjusted_analysis.csv` - Cost-aware results
- `analysis/output/strategy_comparison.csv` - Strategy comparison
- `analysis/output/context_regime_analysis.csv` - Regime filter results
- `analysis/ANALYSIS_REPORT.md` - This report
