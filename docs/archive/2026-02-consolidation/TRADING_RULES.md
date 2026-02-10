# L2 Scalping System - Trading Rules Summary

**Last Updated:** January 21, 2026

---

## Active Trading Rules

### 1. OBI Momentum (Original)
**Status:** Production  
**Rule ID:** `obi_momentum`

**Signal:** Order Book Imbalance (OBI) exceeds threshold
- Entry: `obi_1 > 0.8` (raised from 0.3 after analysis)
- Direction: OBI > 0 → LONG, OBI < 0 → SHORT

**Performance:** Baseline strategy, validated in production

---

### 2. OBI Depth Combo
**Status:** Production  
**Rule ID:** `obi_depth_combo`  
**Lift:** 3.00×

**Signal:** OBI momentum + high depth
- Entry: `d_obi_1_30s > 0.2 AND depth_ask > 25k`
- Direction: Positive delta → LONG, Negative → SHORT

**Performance:** Strongest pattern rule from L2 analysis

---

### 3. Bid Depth + OBI
**Status:** Production  
**Rule ID:** `bid_depth_obi`  
**Lift:** 2.59×

**Signal:** Large bid depth + OBI change
- Entry: `depth_bid > 25k AND d_obi_1_15s > 0.1`
- Direction: LONG

**Performance:** Good secondary signal

---

### 4. High OBI + Depth
**Status:** Production  
**Rule ID:** `high_obi_depth`  
**Lift:** 2.29×

**Signal:** High OBI + large depth
- Entry: `obi_1 > 0.1 AND depth_ask > 30k`
- Direction: LONG

**Performance:** Moderate lift, high frequency

---

### 5. Large Order Size (NEW)
**Status:** Integrated, pending validation  
**Rule ID:** `large_order_size`

**Signal:** Depth exceeds 90th percentile (dynamic per symbol)
- Entry: `depth_bid >= 90th_pct` → LONG
- Entry: `depth_ask >= 90th_pct` → SHORT

**Performance (preliminary):**
- Aggregated t-stat: +41.9 (bid), -36.7 (ask)
- Expectancy @ 300s: +1.56 bps (bid), -1.73 bps (ask)
- 69k+ signals over 7 days

**Unique features:**
- Dynamic threshold (adapts to each symbol)
- 3-phase warmup (price-based → percentile → floor)
- Detects informed institutional flow

See: [SIZE_SIGNAL_ALPHA.md](SIZE_SIGNAL_ALPHA.md)

---

## Context Gates (Hard Filters)

All rules are blocked when:
- **Vol expansion:** -1.54 bps penalty (CRITICAL)
- **BB squeeze:** -0.88 bps penalty (CRITICAL)

**Impact:** Doubles profit ($201 → $402), win rate 58% → 85%

---

## Exit Mechanism

**All rules use bracket orders:**
- Stop loss: 10 bps
- Profit target: 15 bps
- Max hold: 600 seconds (safety backstop)

**Scheduled exit:** 300 seconds (5 min) default hold time

---

## Rule Priority

Rules fire independently. First valid signal per symbol is taken:
1. OBI Momentum (if confidence > 0.3)
2. Pattern rules (OBI Depth Combo, Bid Depth OBI, High OBI Depth)
3. Size Signal (if enabled)

**Cooldown:** 30 seconds between size signals per symbol

---

## Configuration

**File:** `config/strategy.yaml`

```yaml
# Original OBI rule
obi_entry_threshold: 0.8
obi_extreme_threshold: 0.9

# Pattern rules
pattern_rules:
  rule1_enabled: true  # OBI Depth Combo
  rule2_enabled: true  # Bid Depth OBI
  rule3_enabled: true  # High OBI Depth

# Size signal (NEW)
size_signal:
  enabled: true
  percentile: 90
  min_depth_k: 10
  warmup_depth_k: 25
  warmup_samples: 120
  lookback: 300
  cooldown_sec: 30

# Context gates
context_gates:
  hard:
    block_vol_expansion: true
    block_bb_squeeze: true
```

---

## Performance Tracking

**Trade Journal:** `data/trade_journal.db`

Each trade records:
- `rule_name` - Which rule generated the signal
- `signal_id` - Unique ID for correlation
- `signal_strength` - 0.0-1.0
- `signal_confidence` - 0.0-1.0
- `features` - Full snapshot + context at decision time
- `thresholds` - Rule parameters used

**Analysis:** Can attribute P&L to each rule independently

---

## Next Steps

1. **Validate size signal** - Complete statistical analysis
2. **Tune thresholds** - Optimize percentile, warmup multipliers
3. **Monitor rule attribution** - Track P&L by rule_name
4. **Consider rule weighting** - Combine signals vs first-wins
