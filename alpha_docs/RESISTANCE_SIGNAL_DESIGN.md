# Support/Resistance Detection Rule - Design Document

**Objective:** Identify AAA-probability trades at institutional accumulation/distribution zones  
**Target:** 5-20 trades/day (not 50-100)  
**Expected Alpha:** +12 bps per trade @ 300s (from analysis)

---

## Core Concept

**Resistance Level = Institutional Distribution Zone**
- Price touches level multiple times
- Large ask orders appear consistently (30%+ of touches)
- When price returns to level → SHORT signal
- **Alpha: +12.10 bps @ 300s** (31k events in backtest)

**Support Level = DO NOT TRADE**
- Large bid orders at support FAIL (-2.93 bps)
- Suggests "catching falling knife"
- **Skip support levels entirely**

---

## AAA-Probability Criteria

### Level Qualification (Strict)

1. **Minimum touches:** ≥20 (not 10)
   - Ensures statistical significance
   - Filters out random price clusters

2. **Large order consistency:** ≥50% (not 30%)
   - At least half of touches have large orders
   - Indicates persistent institutional interest

3. **Recent activity:** ≥3 touches in last 60 minutes
   - Level must be "hot" (active today)
   - Stale levels from yesterday don't count

4. **Price clustering:** Touches within ±0.5% of level
   - Tighter clustering = stronger level
   - Loose clusters are noise

5. **Volume confirmation:** Avg volume at level ≥2× symbol average
   - High volume = institutional activity
   - Low volume = retail noise

### Signal Qualification (Strict)

1. **Large order present NOW:** 99th percentile depth
   - Not just historical - must see large order at this touch
   - Confirms institutions are active

2. **Imbalance confirmation:** Depth imbalance confirms direction
   - For resistance: depth_imbalance < -0.2 (ask-heavy)
   - Strong selling pressure

3. **Price action:** Approaching from below (for resistance)
   - Not already bouncing off level
   - Want to catch the rejection

4. **No recent signal:** Cooldown ≥300 seconds (5 min)
   - One trade per level per 5 minutes max
   - Prevents overtrading same level

5. **Time-of-day filter:** Only closing session (15:30-16:00)
   - Analysis shows 2× stronger signal during close
   - Reduces false signals

---

## Implementation Design

### Data Structure

```python
class ResistanceLevel:
    price: float                    # Level price
    touches: list[Touch]            # Historical touches
    large_order_ratio: float        # % touches with large orders
    avg_volume: float               # Average volume at level
    last_touch_time: float          # Most recent touch
    last_signal_time: float         # Last time we traded this level
    
class Touch:
    timestamp: float
    price: float
    depth_ask: float
    volume: float
    had_large_order: bool
```

### Level Detection Algorithm

```python
def detect_resistance_levels(symbol: str, lookback_hours: int = 4) -> list[ResistanceLevel]:
    """
    Detect resistance levels from recent price action.
    
    Returns only AAA-quality levels (strict criteria).
    """
    # 1. Get price history (last 4 hours)
    price_history = get_price_history(symbol, hours=4)
    
    # 2. Cluster prices into levels (±0.5% tolerance)
    levels = cluster_prices(price_history, tolerance=0.005)
    
    # 3. Filter by touch count (≥20)
    levels = [l for l in levels if len(l.touches) >= 20]
    
    # 4. Filter by large order ratio (≥50%)
    levels = [l for l in levels if l.large_order_ratio >= 0.5]
    
    # 5. Filter by recent activity (≥3 touches in last 60 min)
    levels = [l for l in levels if count_recent_touches(l, minutes=60) >= 3]
    
    # 6. Filter by volume (≥2× average)
    avg_vol = get_symbol_avg_volume(symbol)
    levels = [l for l in levels if l.avg_volume >= 2 * avg_vol]
    
    return levels  # Typically 0-3 levels per symbol
```

### Signal Generation

```python
def generate_resistance_signal(
    symbol: str,
    current_price: float,
    depth_ask: float,
    depth_imbalance: float,
    timestamp: float
) -> Optional[RuleSignal]:
    """
    Generate signal when price approaches resistance level.
    
    Returns signal only if ALL AAA criteria met.
    """
    # 1. Get qualified resistance levels
    levels = detect_resistance_levels(symbol)
    if not levels:
        return None
    
    # 2. Find level being approached (within 0.2% below)
    level = find_approaching_level(levels, current_price, tolerance=0.002)
    if not level:
        return None
    
    # 3. Check cooldown (5 min since last signal)
    if timestamp - level.last_signal_time < 300:
        return None
    
    # 4. Check time-of-day (closing session only)
    hour = get_hour_et(timestamp)
    if not (15.5 <= hour < 16.0):  # 15:30-16:00
        return None
    
    # 5. Check large order present NOW (99th percentile)
    threshold = get_percentile_threshold(symbol, 99)
    if depth_ask < threshold:
        return None
    
    # 6. Check imbalance confirmation (ask-heavy)
    if depth_imbalance >= -0.2:  # Not enough selling pressure
        return None
    
    # 7. Check price action (approaching from below)
    if current_price >= level.price:  # Already at/above level
        return None
    
    # All criteria met - generate AAA signal
    return RuleSignal(
        rule_name=RuleName.RESISTANCE_REJECTION,
        direction=-1,  # SHORT
        strength=1.0,  # Maximum confidence
        confidence=0.90,  # AAA quality
        reason=f"resistance@{level.price:.2f} ({len(level.touches)} touches, {level.large_order_ratio:.0%} large orders)"
    )
```

---

## Expected Signal Frequency

### Calculation

**Per symbol:**
- Qualified levels: 0-3 per symbol (strict criteria)
- Touches per level: ~5-10 per day
- Signal rate: ~50% of touches (other criteria filter out rest)
- **Signals per symbol per day: 2-5**

**System-wide (17 symbols):**
- Total signals: 2-5 × 17 = **34-85 per day**
- With time-of-day filter (closing only): **÷4 = 8-21 per day**
- With cooldown and other filters: **5-15 per day**

**Target achieved:** 5-20 AAA trades/day ✓

---

## Risk Management

### Position Sizing
```python
# AAA signals get larger size (2× normal)
if signal.confidence >= 0.90:
    base_size = calculate_position_size(...)
    size = base_size * 2.0  # Double size for AAA
```

### Exit Strategy
```python
# Tighter stops for resistance trades
profit_target: 20 bps  # Higher target (+12 bps expected)
stop_loss: 8 bps       # Tighter stop (level should hold)
max_hold: 300 seconds  # Standard 5-min hold
```

### Failure Mode
```python
# If level breaks (price goes above resistance)
if current_price > level.price + 0.005:  # 0.5% above
    exit_immediately()  # Level failed, cut loss
```

---

## Configuration

```yaml
resistance_signal:
  enabled: true
  
  # Level qualification (strict)
  min_touches: 20              # Minimum touches to qualify
  min_large_order_ratio: 0.50  # 50%+ touches with large orders
  min_recent_touches: 3        # In last 60 minutes
  min_volume_multiple: 2.0     # 2× average volume
  price_tolerance: 0.005       # ±0.5% clustering
  
  # Signal qualification (strict)
  approach_tolerance: 0.002    # Within 0.2% below level
  min_imbalance: -0.2          # Ask-heavy book required
  cooldown_sec: 300            # 5 min between signals per level
  
  # Time-of-day filter
  tod_filter: "closing"        # Only 15:30-16:00
  
  # Risk management
  confidence: 0.90             # AAA quality
  size_multiplier: 2.0         # 2× normal size
  profit_target_bps: 20        # Higher target
  stop_loss_bps: 8             # Tighter stop
```

---

## Monitoring & Validation

### Key Metrics to Track

1. **Level quality:**
   - How many levels qualify per symbol?
   - What's the average touch count?
   - What's the large order ratio distribution?

2. **Signal quality:**
   - Win rate (target: ≥70%)
   - Average P&L (target: +12 bps)
   - Sharpe ratio (target: ≥3)

3. **Frequency:**
   - Signals per day (target: 5-20)
   - Signals per symbol (target: 0-2)
   - False positive rate (target: <30%)

4. **Level persistence:**
   - How long do levels stay valid?
   - Do levels from yesterday still work today?
   - When do levels "break"?

### Alerts

```python
# Alert if signal frequency too high
if signals_today > 30:
    alert("Resistance signal frequency too high - check criteria")

# Alert if win rate drops
if win_rate < 0.60:
    alert("Resistance signal quality degraded - review levels")
```

---

## Phased Rollout

### Phase 1: Detection Only (Week 1)
- Implement level detection
- Log qualified levels (no trading)
- Validate level quality manually
- **Goal:** Confirm 0-3 levels per symbol

### Phase 2: Signal Generation (Week 2)
- Implement signal logic
- Log signals (no trading)
- Validate signal quality
- **Goal:** Confirm 5-20 signals/day

### Phase 3: Paper Trading (Week 3-4)
- Enable trading with small size (0.5× normal)
- Monitor win rate and P&L
- Tune criteria if needed
- **Goal:** Validate +12 bps expectancy

### Phase 4: Production (Month 2)
- Enable full size (2× normal for AAA)
- Monitor capacity and slippage
- Scale to more symbols if successful
- **Goal:** 5-20 AAA trades/day, +12 bps avg

---

## Success Criteria

**Must achieve ALL of these:**

1. ✅ Signal frequency: 5-20 per day (not 50-100)
2. ✅ Win rate: ≥70% (vs 50% for size signal)
3. ✅ Average P&L: ≥+10 bps (target +12 bps)
4. ✅ Sharpe ratio: ≥3 (vs 2 for size signal)
5. ✅ False positive rate: <30%

**If any criterion fails:**
- Tighten criteria (increase thresholds)
- Add additional filters
- Reduce signal frequency further

---

## Comparison: Size Signal vs Resistance Signal

| Metric | Size Signal | Resistance Signal |
|--------|-------------|-------------------|
| **Frequency** | 50-100/day | 5-20/day |
| **Expectancy** | +6.75 bps | +12.10 bps |
| **Win Rate** | ~55% | ~70% (target) |
| **Confidence** | 0.70 | 0.90 (AAA) |
| **Position Size** | 1× | 2× |
| **Criteria** | 1 (99th pct) | 7 (strict) |
| **Time Filter** | None | Closing only |

**Strategy:** 
- Size signal = high frequency, moderate quality
- Resistance signal = low frequency, AAA quality
- **Complementary, not competing**

---

## Next Steps

1. **Implement level detection** (Phase 1)
   - Add `ResistanceLevel` class to pattern_rules.py
   - Implement clustering algorithm
   - Log qualified levels for review

2. **Validate level quality** (manual review)
   - Check if levels make sense visually
   - Verify large order ratio calculation
   - Confirm touch count accuracy

3. **Implement signal generation** (Phase 2)
   - Add `generate_resistance_signal()` method
   - Integrate with main.py
   - Log signals (no trading yet)

4. **Paper trade** (Phase 3)
   - Enable with 0.5× size
   - Monitor for 1-2 weeks
   - Tune criteria based on results

**Timeline:** 3-4 weeks to production (conservative)

**Risk:** Low - paper trading with strict criteria, can disable anytime
