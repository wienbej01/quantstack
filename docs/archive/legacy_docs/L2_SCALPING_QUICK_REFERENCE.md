# L2 Scalping Quick Reference Card

## Signal Thresholds

| Signal | Long | Short |
|--------|------|-------|
| OBI Entry | > +0.3 | < -0.3 |
| OBI High Conviction | > +0.6 | < -0.6 |
| Hidden Liquidity | OBI_1 < -0.3 AND OBI_5 > 0.2 | OBI_1 > 0.3 AND OBI_5 < -0.2 |

## Expected Returns (5s forward, bps)

| Condition | HAL | PFE | LUV |
|-----------|-----|-----|-----|
| Extreme Buy (OBI > 0.6) | +17.6 | +18.7 | +13.3 |
| Extreme Sell (OBI < -0.6) | -14.2 | -21.7 | -19.7 |

## Symbol Rankings

1. **PFE** - Best correlation (+0.27), tightest spreads
2. **HAL** - High signal frequency, good correlation (+0.17)
3. **LUV** - Highest win rate (30.5%)

## Thin Book Thresholds (P10)

| Symbol | Bid | Ask |
|--------|-----|-----|
| HAL | 3,200 | 4,200 |
| PFE | 31,100 | 38,500 |
| LUV | 2,100 | 2,100 |

## Risk Parameters

- Max loss per trade: 10 bps
- Profit target: 15-20 bps
- Hold time: 5-15 seconds
- Max daily loss: 100 bps

## Key Files

- Features: `/home/jacobw/quantstack/data/l2_maximum/features_v2/`
- Signals: `/home/jacobw/quantstack/data/l2_maximum/exports/l2_signals.py`
- Full Doc: `/home/jacobw/quantstack/docs/L2_SCALPING_SYSTEM_FOUNDATION.md`
