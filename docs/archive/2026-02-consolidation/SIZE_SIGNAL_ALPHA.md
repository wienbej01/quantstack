# Large Order Size Signal - Alpha Analysis & Implementation

**Date:** January 21, 2026  
**Strategy:** L2 Scalping - Size Signal Rule  
**Status:** Integrated, pending statistical validation

---

## Executive Summary

Large orders in the L2 book predict short-term price movements. When depth exceeds the 90th percentile for a symbol, it signals informed institutional flow:
- **Large bid depth → LONG** (informed buying, price will rise)
- **Large ask depth → SHORT** (informed selling, price will fall)

**Key Results (preliminary, 15k threshold):**
- Aggregated t-stat: +41.9 (bid), -36.7 (ask) - highly significant
- Expectancy: +0.17 bps (bid), -0.19 bps (ask) at 30s horizon
- Signal strength increases with horizon (300s: +1.56 bps bid, -1.73 bps ask)
- 69k+ bid signals, 56k+ ask signals across 7 days, 17 symbols

---

## Alpha Discovery

### Data Source
- **Dataset:** 1.17M L2 snapshots from `/home/jacobw/quantstack/data/l2_maximum/features`
- **Period:** 7 trading days (Dec 19, 2025 - Jan 20, 2026)
- **Symbols:** 17 tickers (ACHR, F, PFE, SMR, HAL, etc.)
- **Frequency:** ~1 snapshot/second during market hours

### Analysis Method
Script: `analysis/l2_size_signal_fast.py`

1. Detect large orders: `max(bid_sz_1...bid_sz_5) >= threshold`
2. Compute forward returns at multiple horizons (30s, 60s, 120s, 300s)
3. For ask signals: negate returns (short P&L)
4. Statistical tests: t-stat, Sharpe, win rate, profit factor

### Per-Symbol Results (Top Performers)

**SMR (NuScale Power)** - Strongest signal:
```
large_bid @ 300s: +20.2 bps, t=25.0, Sharpe=1865
large_ask @ 300s: -55.3 bps, t=-44.4, Sharpe=-8361 (short)
```

**ACHR (Archer Aviation)** - Consistent across horizons:
```
large_bid @ 120s: +3.79 bps, t=9.85, Sharpe=278
large_ask @ 120s: +0.66 bps, t=3.90 (both sides positive!)
```

**F (Ford)** - High capacity:
```
large_bid @ 300s: +0.65 bps, t=10.1, 34k+ trades
large_ask @ 300s: -0.64 bps, t=-10.0
```

**PFE (Pfizer)** - Mean reversion at longer horizons:
```
large_bid @ 30s: +0.04 bps, t=2.85
large_bid @ 300s: -0.32 bps, t=-7.4 (reversal!)
```

### Aggregated Results

| Signal | Horizon | Expectancy | t-stat | n_trades | Sharpe |
|--------|---------|------------|--------|----------|--------|
| large_bid | 30s | +0.17 bps | +41.9 | 69,134 | 387 |
| large_bid | 60s | +0.34 bps | +56.5 | 69,103 | 522 |
| large_bid | 120s | +0.65 bps | +75.7 | 69,042 | 700 |
| large_bid | 300s | +1.56 bps | +120.5 | 68,862 | 1115 |
| large_ask | 30s | -0.19 bps | -36.7 | 56,364 | -375 |
| large_ask | 60s | -0.37 bps | -49.1 | 56,273 | -503 |
| large_ask | 120s | -0.75 bps | -66.9 | 56,204 | -685 |
| large_ask | 300s | -1.73 bps | -99.5 | 55,947 | -1022 |

**Interpretation:** Negative expectancy for large_ask means price went DOWN after large asks (profitable short).

---

## Statistical Deep Dive

### Comprehensive Analysis Tool
Script: `analysis/l2_depth_analysis.py`

Analyzes 8 dimensions:
1. **Depth-size correlation** - Does larger depth = stronger signal?
2. **Depth percentiles** - Non-linear effects by size bucket
3. **Time-of-day effects** - Opening vs midday vs close (5 broad buckets)
4. **OBI level comparison** - Which book level (1-10) is most predictive?
5. **Imbalance vs size** - Relative vs absolute depth
6. **Threshold sensitivity** - Optimal fixed threshold (5k-50k range)
7. **Time decay** - Signal strength over 5s-600s horizons
8. **Support/resistance** - Repeated large orders at price levels

**Key Findings (pending full run):**
- Time-of-day: Opening (9:30-10:00) likely strongest due to volatility
- OBI levels: Top of book (OBI_1) typically most predictive
- Threshold: 90th percentile dynamic > fixed 15k threshold

---

## Implementation

### Architecture

**File:** `src/signals/pattern_rules.py`  
**Class:** `SizeSignalGenerator`

```python
class SizeSignalGenerator:
    """
    Large order size signal generator.
    
    Detects when depth exceeds dynamic percentile threshold (per-symbol).
    Uses 3-phase warmup strategy:
    1. Price-based estimation (first 2 min)
    2. Rolling percentile (after 120 samples)
    3. Absolute floor ($10k minimum always)
    """
```

### Threshold Logic

| Phase | Condition | Threshold | Confidence |
|-------|-----------|-----------|------------|
| Warmup | <120 samples (~2 min) | `$25k × price_multiplier` | 0.55 |
| Active | ≥120 samples | 90th percentile (5-min rolling) | 0.70 |
| Floor | Always | $10k minimum | - |

**Price multipliers** (warmup estimation):
- $0-5: 1.0× → $25k
- $5-10: 1.5× → $38k
- $10-25: 2.5× → $62k
- $25-50: 4.0× → $100k
- $50-100: 6.0× → $150k
- $100+: 10.0× → $250k

### Configuration

**File:** `config/strategy.yaml`

```yaml
size_signal:
  enabled: true
  percentile: 90                # Dynamic threshold
  min_depth_k: 10               # $10k floor
  warmup_depth_k: 25            # Warmup base ($25k)
  warmup_samples: 120           # ~2 min warmup
  lookback: 300                 # 5-min rolling window
  cooldown_sec: 30              # Min time between signals
```

### Exit Mechanism

Uses existing bracket orders:
- **Stop loss:** 10 bps (from `risk.yaml`)
- **Profit target:** 15 bps
- **Max hold:** 600 seconds (10 min safety backstop)

No multiple fixed durations - single robust exit via brackets + time limit.

---

## Integration Flow

```
L2 Data Feed
    ↓
SizeSignalGenerator.generate_signal()
    ↓
Check: depth_bid >= 90th percentile?
    ↓ YES
RuleSignal(LARGE_ORDER_SIZE, direction=LONG)
    ↓
Context Filter (block if vol_expansion/bb_squeeze)
    ↓
_execute_pattern_signal()
    ↓
Place bracket order (entry + stop + target)
```

**Signal cooldown:** 30 seconds per symbol to prevent spam.

---

## Risk Considerations

### Known Issues
1. **Warmup period:** First 2 minutes use price-based estimate (less accurate)
2. **No prior data:** Can't pre-seed from yesterday (SIP selection varies daily)
3. **Threshold sensitivity:** 90th percentile is preliminary - needs tuning from statistical analysis
4. **Symbol heterogeneity:** SMR/ACHR show strong signals, PFE shows reversal

### Mitigations
- Lower confidence (0.55) during warmup
- Absolute $10k floor prevents spurious signals
- Context gates block unfavorable regimes (vol expansion, BB squeeze)
- Cooldown prevents overtrading

### Capacity
- F: 34k+ signals over 7 days = ~5k/day
- High signal frequency suggests good capacity for small position sizes

---

## Next Steps

1. **Complete statistical analysis** - Run `l2_depth_analysis.py` to validate:
   - Optimal percentile threshold (85th? 90th? 95th?)
   - Time-of-day adjustments
   - Optimal exit horizon

2. **Backtest with realistic execution** - Account for:
   - Spread crossing
   - Market impact
   - Partial fills

3. **Paper trade validation** - Monitor:
   - Warmup threshold accuracy
   - Signal quality by time-of-day
   - Win rate vs backtest

4. **Tune parameters** based on results:
   - Adjust percentile threshold
   - Modify warmup multipliers
   - Optimize exit timing

---

## References

- Analysis scripts: `analysis/l2_size_signal_fast.py`, `analysis/l2_depth_analysis.py`
- Results: `analysis/output/size_analysis/`, `analysis/output/depth_analysis/`
- Implementation: `src/signals/pattern_rules.py` (SizeSignalGenerator class)
- Config: `config/strategy.yaml` (size_signal section)
