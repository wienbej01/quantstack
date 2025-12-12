# Root Cause Analysis Report - December 12, 2025

## Executive Summary

The ML trading system shows inconsistent performance due to multiple structural issues. While the system achieved +$13k total PnL, it had extreme volatility (87% drawdown) and only 54% profitable months.

## Critical Finding: Data Timezone Inconsistency

### The Problem
- Gold data has **INCONSISTENT timezones** across symbols
- Large caps (AAPL, TSLA, NVDA): UTC timestamps (13:30-20:00 UTC = 9:30-16:00 ET)
- Small caps (CPRX, AMSC, etc.): Mixed timestamps (some ET, some UTC)

### Refined Understanding
The feature builder's hour filter (`hour < 16`) keeps:
- Hours 9-15 from the raw timestamps
- For UTC data: hours 13-15 UTC = 9:30-12:00 ET (MORNING)
- For ET data: hours 9-15 ET = full day

The hour distribution in features shows:
```
Hour 9-12:  10,799 rows (0.8%)   - Sparse ET data
Hour 13-15: 1,307,799 rows (99.2%) - Mix of UTC morning + ET afternoon
```

### The Real Issue
The `hour` feature in the model uses RAW timestamps without timezone normalization:
- Hour 13 could mean 9:00 AM ET (UTC data) OR 1:00 PM ET (ET data)
- Model cannot learn consistent time-of-day patterns
- Label rates vary 10x between actual morning (13.22%) and afternoon (1.33%)

### Impact
- Model trained on mixed timezone data with inconsistent hour features
- Time-of-day patterns are corrupted
- Cannot reliably filter for morning-only trading

## Root Causes Summary

| Issue | Priority | Impact |
|-------|----------|--------|
| Timezone inconsistency | CRITICAL | Model trained on wrong time period |
| Raw price features | HIGH | Price drift causes model degradation |
| ICT implementation | MEDIUM | Features not predictive |
| VPA normalization | MEDIUM | Extreme values distort model |
| Time-stratified models | MEDIUM | Single model averages conflicting patterns |
| Regime detection | LOW | SIP provides volatility but not direction |

## Detailed Findings

### 1. Raw Price Features (24 features)
- `close`, `high`, `low`, `open`, `vwap`, `atr`, `high_5`, `low_5`, etc.
- 2023 mean close: $81.00 → 2025 mean close: $160.14 (0.9σ drift)

### 2. ICT Feature Effectiveness
| Feature | Occurrence | Lift (2023) | Lift (2025) |
|---------|------------|-------------|-------------|
| order_block_bull | 0.70% | 3.95x | 2.93x |
| fvg_down | 15.20% | 2.01x | - |
| displacement_up | 2.86% | 2.65x | - |
| liquidity_grab_low | 8.72% | 0.81x | 0.99x |

**Key Issue**: Liquidity grab features show NO predictive power (lift ~1.0x)

### 3. VPA Feature Correlations
| Feature | Corr with Long Label |
|---------|---------------------|
| volume_ratio_20 | +0.061 |
| volume_momentum | +0.034 |
| pressure_ratio | +0.007 |
| pv_divergence | -0.034 |

**Key Issue**: `pressure_ratio` has extreme values (mean ~10,000)

### 4. SIP Filter Analysis
- Avg gap: 3.90% (vs 2% minimum)
- Avg ATR: $4.24 (vs $0.70 minimum)
- Gap direction: 52% UP, 48% DOWN (balanced)

**Implication**: SIP provides volatility filter but NOT directional regime filter

## Recommendations

### Phase 1: Data Fix (REQUIRED FIRST)
1. Normalize all timestamps to ET before feature engineering
2. Rebuild features with consistent timezone handling
3. Ensure morning data (9:30-12:00 ET) is properly captured

### Phase 2: Feature Cleanup
1. Remove raw price features (keep only ratios/percentages)
2. Normalize extreme values (cap pressure_ratio)
3. Add proper time-of-day features

### Phase 3: Model Improvement
1. Train time-stratified models (morning vs afternoon)
2. Focus trading on morning hours (9:30-12:00 ET)
3. Validate on known good periods before deployment

### Phase 4: ICT Enhancement
1. Add kill zone detection (9:30-10:30 ET, 14:00-15:00 ET)
2. Implement premium/discount zones
3. Add multi-bar pattern detection for FVG/OB
4. Consider higher timeframe context (5m, 15m aggregates)

## Missing Data (Not Available)
- L2 order book data
- Bid-ask spread
- Tick-level data for delta analysis

## Next Steps
1. Fix timezone handling in `build_intraday_features_rolling.py`
2. Run quick validation on timezone-fixed data
3. Rebuild full feature set
4. Retrain and validate models


---

## Final Summary

### Critical Issues (in priority order)

| # | Issue | Priority | Root Cause | Fix |
|---|-------|----------|------------|-----|
| 1 | Timezone inconsistency | CRITICAL | Mixed UTC/ET in gold data | Normalize to ET |
| 2 | Raw price features | HIGH | 24 features with price drift | Remove, use ratios |
| 3 | ICT implementation | MEDIUM | Simplified single-bar | Multi-bar patterns |
| 4 | VPA normalization | MEDIUM | Extreme values | Cap/log transform |
| 5 | Time stratification | MEDIUM | Single model for all hours | Morning/afternoon models |

### Key Metrics

- Label rate morning: **13.22%** vs afternoon: **1.33%** (10x difference)
- Price drift: $81 (2023) → $160 (2025) = **0.9σ**
- Order block lift: 3.95x (2023) → 2.93x (2025) = **26% decline**
- Liquidity grab lift: **~1.0x** (not predictive)

### Implementation Order

1. **Phase 1**: Fix timezone handling (REQUIRED FIRST)
2. **Phase 2**: Remove raw price features
3. **Phase 3**: Train time-stratified models
4. **Phase 4**: Enhance ICT features

### Not Possible Without L2 Data
- Delta/cumulative delta
- Absorption detection
- Order flow imbalance
- Bid-ask spread analysis

---
*Analysis completed: December 12, 2025*
