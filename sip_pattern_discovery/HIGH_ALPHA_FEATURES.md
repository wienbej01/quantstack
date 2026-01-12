# High-Alpha Event-Based Pattern Discovery

## Overview

Upgraded from state-based features to event-based signals for actionable alpha generation. Focus on cross-ticker relative strength and volume-price divergence as primary alpha sources.

## Feature Hierarchy

### Tier 1: Cross-Ticker Relative Strength (HIGHEST ALPHA)
- `rel_underperform_extreme` - Stock underperforming SPY by >1% → mean reversion opportunity
- `rel_outperform_extreme` - Stock outperforming SPY by >1% → momentum continuation
- `rel_strength_60m` - Continuous relative strength measure

**Why high alpha**: Less crowded than absolute technicals, exploits cross-asset momentum effects.

### Tier 2: Volume-Price Divergence (HIGH ALPHA)
- `price_up_vol_weak` - Price up but RVOL < 0.7 → weak rally, likely reversal
- `price_down_vol_weak` - Price down but RVOL < 0.7 → weak selling, likely bounce
- `price_up_vol_strong` - Price up with RVOL > 1.5 → strong rally, continuation
- `price_down_vol_strong` - Price down with RVOL > 1.5 → strong selling, continuation

**Why high alpha**: Fundamental market microstructure, volume confirms price moves.

### Tier 3: Session Range Events (MEDIUM ALPHA)
- `at_session_high` - Price at >95% of session range → mean reversion
- `at_session_low` - Price at <5% of session range → mean reversion
- `new_session_high` - Breaking session high → breakout continuation
- `new_session_low` - Breaking session low → breakdown continuation

**Why medium alpha**: Well-known but still effective, clear support/resistance levels.

### Tier 4: VWAP Events (MEDIUM ALPHA)
- `vwap_cross_up` - Price crosses above VWAP → institutional buying
- `vwap_cross_down` - Price crosses below VWAP → institutional selling
- `avwap_cross_up` - Price crosses above session AVWAP
- `avwap_cross_down` - Price crosses below session AVWAP

**Why medium alpha**: Institutional reference point but widely known.

## State vs Event Features

### State Features (OLD - Low Alpha)
```python
spy_above_sma20 = True    # True for thousands of consecutive bars
is_power_hour = True      # True for 60 bars per day
price_vs_vwap_pct > 0     # True for extended periods
```
**Problems**: Not actionable entry signals, heavily correlated samples, low alpha.

### Event Features (NEW - High Alpha)
```python
rel_underperform_extreme = True   # True for 1 bar when condition met
vwap_cross_up = True             # True for 1 bar when cross happens
new_session_high = True          # True for 1 bar when breakout occurs
```
**Benefits**: Actual entry triggers, independent samples, higher alpha potential.

## Sample Size Analysis

### With State Features (OLD)
- 6.5M bars total
- `spy_above_sma20` true for ~4M bars (60% of time)
- But only ~50 independent regime periods
- **Effective sample size**: Much smaller than reported

### With Event Features (NEW)
- 6 months × 63 symbols × ~10 events/day = ~80,000 event samples
- Per regime (4-way): ~20,000 samples
- Per pattern (5% hit rate): ~1,000 independent samples
- **Effective sample size**: Matches reported size

## Expected Pattern Examples

```
"rel_underperform_extreme == True AND price_down_vol_weak == True"
→ "Stock underperforming SPY by >1% on weak volume = LONG (mean reversion)"

"new_session_high == True AND price_up_vol_strong == True"  
→ "Breaking session high on strong volume = LONG (breakout continuation)"

"at_session_high == True AND rel_outperform_extreme == True"
→ "At session high after outperforming SPY = SHORT (exhaustion)"
```

## Implementation Details

### Feature Computation
- **Cross-ticker**: Merge SPY returns, compute relative strength
- **Volume-price**: Compare price direction vs relative volume
- **Session range**: Track running high/low, compute position percentile
- **Events**: Detect state changes (crosses, breakouts, extremes)

### Pattern Discovery
- **Regime segmentation**: Bull/bear × high/low vol as data filters
- **Feature discretization**: State features binned, event features binary
- **Statistical validation**: t-stat ≥ 3.0, expectancy ≥ 0.01%, min 30 samples
- **Economic filtering**: Prioritize patterns with clear microstructure rationale

### LLM Analysis
- **Consolidated report**: Single themed analysis vs 8 separate files
- **Cross-horizon comparison**: Which timeframe optimal per pattern type?
- **Portfolio construction**: Recommend 3-5 pattern combination
- **Alpha assessment**: Rank themes by expected profitability

## Usage

```bash
cd ~/quantstack/sip_pattern_discovery

# Clear cache (new features)
rm -f output_tstat/cached_*.parquet

# Run high-alpha discovery
python run_long_short_discovery.py \
  --start-date 2024-07-01 \
  --end-date 2024-12-31 \
  --min-t-stat 3.0 \
  --min-expectancy 0.01 \
  --min-trades 30 \
  --horizons 30,60,90,180
```

## Key Advantages

1. **Actionable Signals**: Event features are actual entry triggers
2. **Higher Alpha**: Cross-ticker and volume-price less crowded than simple technicals
3. **Statistical Validity**: Independent event samples vs correlated state observations
4. **Economic Rationale**: Each feature exploits specific market microstructure
5. **Regime Awareness**: Bull/bear × high/low vol segmentation
6. **Consolidated Analysis**: Single themed report for portfolio construction

## Future Enhancements

If current features don't produce sufficient alpha:
- **Fair Value Gaps (FVG)**: Price imbalances where price moved too fast
- **Order Blocks**: Zones of institutional accumulation/distribution  
- **Liquidity Sweeps**: Stop hunts before reversals
- **Sector rotation**: Cross-sector relative strength
- **Earnings proximity**: Event-driven patterns around announcements
