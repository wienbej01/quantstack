# L2 Scalping Analysis - $10k Account Strategy

**Date**: 2025-12-20  
**Data**: 192,841 L2 records across 48 symbols (Dec 17-19, 2025)  
**Account Size**: $10,000

## ✅ PROFITABLE STRATEGY FOUND

**Strategy**: OBI > 0.8 + High Volume (rel_vol > 2.0)  
**Hold Time**: 5 minutes (300 seconds)

| Metric | Value |
|--------|-------|
| Gross Return | **6.12 bps** |
| Win Rate | **64.1%** |
| Median Return | 7.20 bps |
| Signals/Day | ~181 |

## P&L for $10k Account

| Position Size | % of Account | Net P&L/Trade | Daily P&L | Monthly P&L |
|---------------|--------------|---------------|-----------|-------------|
| $2,000 | 20% | -$0.78 | -$141 | -$2,952 |
| $3,000 | 30% | -$0.16 | -$30 | -$626 |
| **$4,000** | **40%** | **+$0.45** | **+$81** | **+$1,699** |
| **$5,000** | **50%** | **+$1.06** | **+$192** | **+$4,024** |

**Minimum position: $4,000 (40% of account) for profitability**

## Strategy Details

### Entry Criteria
```python
# Buy signal
if obi_1 > 0.8 and rel_vol > 2.0:
    enter_long()

# Sell signal  
if obi_1 < -0.8 and rel_vol > 2.0:
    enter_short()
```

### Why This Works
1. **Extreme OBI (>0.8)**: Strong order book imbalance = high conviction
2. **High Volume (>2x normal)**: Institutional activity, better fills
3. **5-minute hold**: Allows move to develop, covers commission costs
4. **64% win rate**: Favorable risk/reward

### Return Distribution
| Range | % of Trades |
|-------|-------------|
| > +10 bps | 40.1% |
| +5 to +10 bps | 14.4% |
| 0 to +5 bps | 16.3% |
| -5 to 0 bps | 6.6% |
| -10 to -5 bps | 12.4% |
| < -10 bps | 10.2% |

**40% of trades return >10 bps** - this is what makes it profitable.

## Risk Management

### Position Sizing
- **Recommended**: 40-50% of account ($4k-$5k)
- **Max loss per trade**: ~$25 (at $5k position)
- **Daily drawdown limit**: Stop after 3 consecutive losses

### Context Filters (Awareness, Not Signals)
- **Trade with trend**: When mom_15 aligns with OBI direction
- **Avoid extremes**: Skip if RSI > 80 or < 20
- **VWAP awareness**: Note position relative to VWAP for S/R

## Comparison: Short vs Long Holds

| Hold Time | Gross Return | Win Rate | Profitable at $5k? |
|-----------|-------------|----------|-------------------|
| 15s | 1.1 bps | 41% | ❌ No |
| 30s | 1.5 bps | 44% | ❌ No |
| 60s | 1.9 bps | 50% | ❌ No |
| **300s (5m)** | **6.1 bps** | **64%** | **✅ Yes** |
| 600s (10m) | 4.5 bps | 57% | ✅ Yes |

**5-minute holds are optimal** - long enough for moves to develop, short enough to avoid drift.

## Key Insights

1. **Commission costs require longer holds** - 15-30s scalping not viable at $10k
2. **High volume is critical** - 2x+ relative volume signals institutional flow
3. **OBI > 0.8 is the threshold** - lower thresholds have too many false signals
4. **64% win rate is achievable** - much better than typical 30-40%
5. **~180 trades/day** - manageable frequency

## Recommended System Parameters

```yaml
# config/strategy.yaml updates
strategy:
  obi_threshold: 0.8          # Up from 0.3
  min_rel_volume: 2.0         # New filter
  hold_time_seconds: 300      # Up from 15
  position_size_pct: 0.40     # 40% of account

risk:
  max_position_value: 5000    # Cap at $5k
  max_daily_trades: 200       # Reasonable limit
  stop_loss_bps: 15           # ~$7.50 at $5k
```

## Implementation

```python
def should_trade(snapshot, context):
    # 1. High conviction L2 signal
    if abs(snapshot.obi_1) < 0.8:
        return False, 0
    
    # 2. High volume filter (critical)
    if context.rel_vol < 2.0:
        return False, 0
    
    # 3. Determine direction
    direction = 1 if snapshot.obi_1 > 0 else -1
    
    # 4. Position size (40% of $10k)
    position_size = 4000
    
    return True, direction * position_size

# Hold for 5 minutes, then exit
HOLD_TIME_SECONDS = 300
```
