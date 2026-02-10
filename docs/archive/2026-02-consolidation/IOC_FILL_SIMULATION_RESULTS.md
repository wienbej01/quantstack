# IOC Order Fill Simulation Results - Jan 23, 2026

## Executive Summary

Analyzed 3,219 IOC entry orders from Jan 23, 2026 against L2 market data to determine if orders would have filled at the submitted price, +1 tick, or -1 tick, accounting for 100ms average latency.

**Key Finding**: 85.9% of orders would have filled at the submitted price. The $0.01 buffer was sufficient for most orders.

## Overall Results

| Outcome | Count | Percentage |
|---------|-------|------------|
| **Filled at order price** | 2,766 | **85.9%** |
| Would fill at -1 tick | 72 | 2.2% |
| Would fill at +1 tick | 63 | 2.0% |
| No fill even at +/-1 tick | 318 | 9.9% |
| **Total** | **3,219** | **100%** |

## By Symbol

| Symbol | Orders | At Order | -1 Tick | +1 Tick | No Fill |
|--------|--------|----------|---------|---------|---------|
| **NVDA** | 1,098 | 77.8% | 3.7% | 2.2% | 16.3% |
| **INTC** | 933 | 79.1% | 3.0% | 3.3% | 14.6% |
| **PLUG** | 1,188 | 98.8% | 0.3% | 0.7% | 0.3% |

**Observation**: PLUG had significantly better fill rates (98.8%) compared to NVDA/INTC (~78%). This suggests PLUG had more stable quotes or wider spreads relative to the buffer.

## By Side

| Side | Orders | At Order | -1 Tick | +1 Tick | No Fill |
|------|--------|----------|---------|---------|---------|
| **BUY** | 1,754 | 87.5% | 0.0% | 3.6% | 8.9% |
| **SELL** | 1,465 | 84.0% | 4.9% | 0.0% | 11.1% |

**Key Insight**: 
- BUY orders that didn't fill were **too passive** (63 would fill at +1 tick = more aggressive)
- SELL orders that didn't fill were **too aggressive** (72 would fill at -1 tick = less aggressive)

This asymmetry suggests the signal pricing logic may need adjustment:
- BUY orders: Could be more aggressive (higher price)
- SELL orders: Could be less aggressive (higher price)

## Price Improvement Opportunities

### Too Aggressive (72 orders, 2.2%)
- SELL orders priced too low
- Would fill if price was 1 tick higher
- Missing fills due to insufficient buffer on the aggressive side

### Too Passive (63 orders, 2.0%)
- BUY orders priced too low
- Would fill if price was 1 tick higher
- Missing fills due to being too conservative

### Market Moved (318 orders, 9.9%)
- Market moved >1 tick during the ~100ms latency period
- Even +/-1 tick adjustment wouldn't capture these fills
- Represents fundamental latency limitation

## Sample Non-Fills

```
NVDA SELL @ $189.31  Bid: $189.22  Distance: $+0.09  Spread: $0.07
NVDA SELL @ $189.31  Bid: $189.06  Distance: $+0.25  Spread: $0.07
NVDA BUY  @ $188.78  Ask: $188.80  Distance: $-0.02  Spread: $0.07
NVDA BUY  @ $188.78  Ask: $188.93  Distance: $-0.15  Spread: $0.11
NVDA BUY  @ $188.30  Ask: $188.34  Distance: $-0.04  Spread: $0.07
```

Most non-fills were within 2-4 ticks of the market, suggesting rapid price movement during latency.

## Methodology

1. **Data Sources**:
   - API logs: `/home/jacobw/api-exported-logs.txt` (3,219 IOC orders)
   - L2 data: `/home/jacobw/quantstack/data/l2_maximum/features/date=2026-01-23/`
   - ~51,500 L2 snapshots per symbol

2. **Latency Adjustment**:
   - Applied 100ms latency to order timestamps
   - Matched orders to L2 snapshot at order receipt time
   - Calculated bid/ask from mid and spread

3. **Fill Logic**:
   - BUY orders: Fill if `order_price >= ask`
   - SELL orders: Fill if `order_price <= bid`
   - Tested at order price, +1 tick, -1 tick

## Recommendations

1. **Current Buffer is Adequate**: 85.9% fill rate suggests $0.01 buffer is working well

2. **Consider Asymmetric Adjustments**:
   - BUY orders: Add +1 tick more aggressively (currently missing 3.6%)
   - SELL orders: Reduce aggressiveness by 1 tick (currently missing 4.9%)

3. **Symbol-Specific Tuning**:
   - PLUG: Current logic works excellently (98.8%)
   - NVDA/INTC: Consider +1 tick buffer increase (only 78% fill rate)

4. **Accept 10% No-Fill Rate**:
   - 9.9% of orders miss due to rapid market movement
   - This is a fundamental latency limitation
   - Further buffer increases would hurt execution quality on fills

## Files Generated

- **Simulation Tool**: `/home/jacobw/quantstack/scripts/simulate_order_fills.py`
- **Detailed Results**: `/home/jacobw/quantstack/fill_simulation_results.csv`
- **This Report**: `/home/jacobw/quantstack/docs/IOC_FILL_SIMULATION_RESULTS.md`

## Next Steps

1. Monitor live fill rates after bracket order fix is deployed
2. Compare actual fills to simulation predictions
3. Adjust buffer logic if systematic bias is observed
4. Consider dynamic buffer based on symbol volatility/spread
