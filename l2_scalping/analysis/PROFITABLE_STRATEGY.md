# L2 Scalping Candidate Strategy

**Updated**: 2025-12-24  
**Status**: ⚠️ Candidate only (not profitable after costs at $4k size on expanded sample)

## Strategy: OBI > 0.8 + rel_vol > 2.0 + RSI > 50

### Entry Criteria
```yaml
strategy:
  entry:
    obi_threshold: 0.8
    min_rel_volume: 2.0
    rsi_min: 50

  hard_gates:
    block_vol_expansion: true
    block_bb_squeeze: true

  position:
    size_pct: 0.40
    hold_time_seconds: 300
```

## Backtest Results (Dec 19 & Dec 23, 2025)

| Metric | Value |
|--------|-------|
| Trades | 182 |
| Win Rate | 56.0% |
| Mean Return | 2.55 bps |
| Avg Gross P&L/Trade | $1.02 |
| Avg Net P&L/Trade | **-$0.98** |
| Total Net P&L | **-$178.58** |

**Assumptions**: $10k account, 40% position size ($4k), $2 round-trip commission.  
**Note**: All trades occurred on Dec 23 in this sample.

## Interpretation

- The strategy shows **positive gross edge**, but **net results are negative** at $4k size.
- Break-even position size is **~$7.9k** given the current mean return.
- Hard-gate benefits were **not revalidated** on the expanded dataset.

## Holding Period Upside

At longer holds, net P&L turns positive for this filter:

| Horizon | Mean Return | Avg Net P&L | Trades |
|---------|-------------|-------------|--------|
| 600s | 14.19 bps | +$3.67 | 173 |
| 900s | 29.68 bps | +$9.87 | 159 |

## Leverage-Capped Results (3x Max, 900s Hold)

Assumptions: max gross exposure $30k, FIFO admission, $2 commission.

| Position Size | Trades | Mean Return | Win Rate | Avg Net P&L | Total Net P&L |
|---------------|--------|-------------|----------|-------------|---------------|
| $2,000 | 78 | 8.15 bps | 61.5% | -$0.37 | -$28.87 |
| $4,000 | 42 | 12.28 bps | 78.6% | +$2.91 | +$122.22 |

Rank-replace (score = rel_vol) at $4,000: 51 trades, +$88.98 total net P&L.

## Next Validation Steps

1. Re-test hard gates on the expanded sample
2. Evaluate 10-15k position sizes for net profitability
3. Compare RSI extremes vs RSI>50 filters
