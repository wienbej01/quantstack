# L2 VWAP Mean Reversion - Strategy Design

## Research Basis

Source: `/home/jacobw/quantresearch/projects/l2_vwap_spy_corr/research/analysis_summary.md`

### Key Findings

1. **L2 filters drive the edge** - SPY overlays do not show consistent incremental benefit
2. **Entry spread is the most robust explanatory variable** in L2 spread_off variant
3. **spread_off variant** outperforms baseline with expectancy 15.32 vs 9.62

### Performance Summary

| Variant | Expectancy | Win Rate | Avg Duration |
|---------|------------|----------|--------------|
| Baseline (no L2) | 9.62 | 61.4% | 26.0m |
| L2 spread_off | 15.32 | 67.5% | 25.1m |
| L2 spread_on | 28.69 | 70.5% | 13.6m |

Note: spread_on has insufficient sample size for reliable statistics.

## Strategy Parameters

### VWAP Calculation

```
VWAP_t = sum(typical_price * volume) / sum(volume)
typical_price = (high + low + close) / 3
```

Reset at market open (09:30 ET).

### Entry Conditions

Evaluated on bar close:

- **Long**: `close <= VWAP * 0.995` AND `l2_ratio >= 1.165`
- **Short**: `close >= VWAP * 1.005` AND `l2_ratio <= 0.858`

Where:
- `l2_ratio = depth_bid / depth_ask` (level 1)

### Exit Conditions

Evaluated each bar close:

| Exit Type | Long | Short |
|-----------|------|-------|
| Mean Reversion | `close >= VWAP` | `close <= VWAP` |
| Take Profit | `close >= entry * 1.005` | `close <= entry * 0.995` |
| Stop Loss | `close <= entry * 0.9925` | `close >= entry * 1.0075` |
| Forced Exit | `time >= 15:55 ET` | `time >= 15:55 ET` |

### Execution Model

Next-bar execution with 1-tick adverse slippage:

- **Entry (Long)**: `next_open + tick`
- **Entry (Short)**: `next_open - tick`
- **Exit (Long)**: `next_open - tick`
- **Exit (Short)**: `next_open + tick`

Default tick size: 0.01

### Risk Parameters

- Position size: 100 shares
- Max positions: 1 (one at a time)
- Transaction costs: 1 bp per side

### Timing

- Entry window: 09:35-15:30 ET
- Forced exit: 15:55 ET
- Timezone: America/New_York

## L2 Filter Rationale

The L2 depth ratio filter identifies order book imbalance:

- **Long (ratio >= 1.165)**: More bid depth than ask depth suggests buying pressure
- **Short (ratio <= 0.858)**: More ask depth than bid depth suggests selling pressure

This filter improved win rate from 61.4% to 67.5% in backtesting.

## Data Sources

### L2 Features

Path: `/home/jacobw/quantstack/data/l2_maximum/features/date=YYYY-MM-DD/symbol=XXX/`

Columns used:
- `depth_bid` or `depth_bid_1`
- `depth_ask` or `depth_ask_1`

### Universe

Path: `/home/jacobw/quantstack/data/nyse_gold_tickers.txt`

~150 NYSE gold tickers, limited to 50 for paper trading.

## Implementation Notes

1. **Bar aggregation**: IBKR provides 5-second bars, aggregated to 1-minute
2. **L2 data alignment**: Features loaded from parquet, matched by timestamp
3. **Position tracking**: Single position at a time, tracked in Strategy class
4. **Order execution**: Market orders via IBKR paper trading account
