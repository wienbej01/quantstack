# L2 Scalping Feature Analysis Report

**Date**: 2025-12-20  
**Data**: 192,841 L2 records across 48 symbols (Dec 17-19, 2025)

## Executive Summary

### Critical Finding: Commission Costs Dominate

With $2 round-trip commission, **no strategy is profitable at $5k-$10k position sizes** for 15-30 second holds.

| Position Size | Best Strategy Return | Net P&L/Trade | Daily P&L |
|---------------|---------------------|---------------|-----------|
| $5,000 | 1.51 bps | **-$1.25** | -$8,968 |
| $10,000 | 1.51 bps | **-$0.49** | -$3,546 |
| $15,000 | 1.51 bps | **+$0.26** | +$1,876 |
| $20,000 | 1.51 bps | **+$1.01** | +$7,297 |

**Break-even position size: ~$13,300**

## Strategy Performance (30s Horizon)

| Strategy | Gross Return | Win Rate | Signals/Day |
|----------|-------------|----------|-------------|
| extreme_obi_07 (OBI > 0.7) | 1.51 bps | 43.9% | 7,195 |
| extreme_obi_highvol | 1.47 bps | 47.7% | 3,091 |
| extreme_obi_depth | 1.45 bps | 39.9% | 4,072 |
| extreme_obi_06 | 1.32 bps | 43.5% | 11,339 |
| extreme_obi_trend | 1.19 bps | 45.2% | 9,420 |

## Context Features as Regime Filters

Context features should be used for **awareness**, not signal generation:

### Trend Alignment
- **With trend**: Slightly better win rates
- **Against trend**: Lower win rates but still positive expectancy
- **Recommendation**: Prefer trading with 15-bar momentum direction

### VWAP Position (Support/Resistance)
- Buy signals below VWAP (support) perform marginally better
- Sell signals above VWAP (resistance) perform marginally better
- **Recommendation**: Use as soft filter, not hard requirement

### Volume Regime
- High volume (>1.5x) signals: 47.7% win rate (best)
- Normal volume: 43% win rate
- **Recommendation**: Prefer high-volume periods

## Recommendations for Profitability

### Option 1: Larger Position Sizes
- **Minimum $15,000 per trade** for profitability
- $20,000+ recommended for meaningful returns
- Risk: Larger drawdowns on losing trades

### Option 2: Reduce Trade Frequency
- Only take top 10% of signals (OBI > 0.8)
- Fewer trades = lower total commission
- May improve signal quality

### Option 3: Longer Hold Times
- Current analysis limited to 30s
- 60-120s holds may capture larger moves
- Requires additional analysis

### Option 4: Lower-Cost Execution
- IBKR Pro: ~$0.35-$1.00 per trade
- Reduces break-even to ~$5,000 position
- Most impactful change

## Updated Signal Logic

```python
def should_trade(snapshot, context):
    # 1. High conviction L2 signal (OBI > 0.7)
    if abs(snapshot.obi_1) < 0.7:
        return False
    
    # 2. Context awareness (soft filters)
    # Prefer trading with trend
    with_trend = (
        (snapshot.obi_1 > 0 and context.mom_15 > 0) or
        (snapshot.obi_1 < 0 and context.mom_15 < 0)
    )
    
    # Prefer high volume periods
    high_volume = context.rel_vol > 1.2
    
    # 3. Position sizing based on conviction
    if with_trend and high_volume:
        position_size = 20000  # High conviction
    elif with_trend or high_volume:
        position_size = 15000  # Medium conviction
    else:
        position_size = 10000  # Lower conviction (may skip)
    
    return position_size >= 15000  # Only trade if profitable
```

## Key Insights

1. **L2 signals have genuine predictive power** (1.5 bps at 30s)
2. **Commission costs are the primary obstacle** to profitability
3. **Context features provide marginal improvement** (~0.1-0.2 bps)
4. **Win rates of 44-48%** are achievable with high-conviction signals
5. **Position sizing is critical** - need $15k+ for profitability

## Files Generated

- `analysis/output/cost_adjusted_analysis.csv` - Full results
- `analysis/cost_adjusted_analysis.py` - Analysis script
- `analysis/ANALYSIS_REPORT.md` - This report
