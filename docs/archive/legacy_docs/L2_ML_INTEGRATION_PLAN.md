# L2 Data ML Integration Plan

## Current State

**Data Collected:**
- 3.85MB, ~3,128 L2 snapshots
- 17 symbols, 3 collection runs
- 20 computed microstructure features
- 100% depth availability

**Current Limitations:**
- Sample size too small for ML (need 50K+ records)
- Weak standalone predictive signal (correlations ±0.03)
- Limited time coverage (opening hour only)

## Collection Strategy

### Phase 1: Data Accumulation (Weeks 1-4)

**Target:** 50,000+ L2 records

**Collection Schedule:**
```
Windows (ET):
- 09:30-10:30  Opening volatility
- 11:30-12:30  Pre-lunch consolidation
- 14:00-15:00  Afternoon momentum
- 15:00-16:00  Power hour

Symbols:
- 3 CORE: HAL, PFE, LUV (always)
- 3 ROTATING: From daily SIP

Expected: ~1,440 records/day × 30 days = 43,200 records
```

### Phase 2: Feature Engineering (Week 4+)

**L2 Features to Compute:**

1. **Order Book Imbalance (OBI)**
   - `obi_1, obi_3, obi_5, obi_10` - Multi-level imbalance
   - Already computed, weak standalone signal

2. **Microprice Features**
   - `microprice` - Volume-weighted fair value
   - `micro_off` - Deviation from mid
   - Useful for entry timing

3. **Depth Features**
   - `depth_imb_k` - Total depth imbalance
   - `pressure_k` - Liquidity pressure
   - Better signal at 30s horizon

4. **Time Dynamics**
   - `d_mid_5s, d_mid_30s` - Price momentum
   - `d_obi1_5s, d_obi1_30s` - OBI momentum
   - Capture regime transitions

5. **NEW: Cross-Symbol Features**
   - `sector_obi` - Sector-wide order flow
   - `relative_pressure` - vs universe average
   - `correlation_regime` - L2 correlation state

### Phase 3: ML Model Integration (Week 5+)

**Integration Approach:**

L2 features should AUGMENT, not replace, existing cross-sectional features.

```python
# Current: 11 cross-sectional features
cross_features = [
    'cross_rank_ret', 'cross_rank_vol', 'sector_momentum',
    'cross_dispersion', 'market_breadth', 'up_down_ratio',
    'rel_strength_5', 'rel_strength_10', 'rel_strength_20',
    'market_ret_5', 'market_ret_10'
]

# Add: 8 L2 microstructure features
l2_features = [
    'obi_10',           # Deep book imbalance
    'micro_off',        # Microprice deviation
    'depth_imb_k',      # Total depth imbalance
    'pressure_k',       # Liquidity pressure
    'd_mid_30s',        # 30s price momentum
    'd_obi1_30s',       # 30s OBI momentum
    'spread_zscore',    # Spread vs recent average
    'depth_ratio',      # Bid/ask depth ratio
]

# Combined: 19 features
all_features = cross_features + l2_features
```

**Model Architecture:**

```
Option A: Feature Augmentation (Recommended)
- Add L2 features to existing regime-aware models
- Retrain with combined feature set
- Minimal architecture change

Option B: Ensemble Approach
- Separate L2-only model for entry timing
- Combine with cross-sectional model
- More complex but potentially better

Option C: Hierarchical Model
- Cross-sectional model for direction
- L2 model for entry/exit timing
- Best for execution optimization
```

## Use Cases for L2 Data

### 1. Entry Timing Optimization
**Problem:** Current system enters at market, may get poor fills
**Solution:** Use microprice deviation to time entries

```python
def should_enter_now(l2_features: dict, direction: str) -> bool:
    """Use L2 to optimize entry timing."""
    micro_off = l2_features['micro_off']
    obi = l2_features['obi_1']
    
    if direction == 'long':
        # Enter when microprice below mid (favorable)
        # and order flow not strongly against us
        return micro_off < 0 and obi > -0.3
    else:
        return micro_off > 0 and obi < 0.3
```

### 2. Position Sizing by Liquidity
**Problem:** Fixed 100 share positions regardless of liquidity
**Solution:** Scale position by available depth

```python
def get_position_size(l2_features: dict, base_size: int = 100) -> int:
    """Scale position by available liquidity."""
    depth_bid = l2_features['depth_bid_k']
    depth_ask = l2_features['depth_ask_k']
    
    # Don't take more than 10% of visible liquidity
    max_by_liquidity = min(depth_bid, depth_ask) * 0.1
    
    return min(base_size, int(max_by_liquidity))
```

### 3. Regime Enhancement
**Problem:** Regime detection uses only price/volatility
**Solution:** Add L2 regime indicators

```python
def detect_l2_regime(l2_features: dict) -> str:
    """Detect market microstructure regime."""
    spread = l2_features['spread']
    pressure = l2_features['pressure_k']
    obi_momentum = l2_features['d_obi1_30s']
    
    if spread > 0.03:
        return 'illiquid'  # Wide spreads, reduce size
    elif abs(pressure) > 200:
        return 'imbalanced'  # Strong directional flow
    elif abs(obi_momentum) > 0.5:
        return 'transitioning'  # Regime change
    else:
        return 'normal'
```

### 4. Stop Loss Optimization
**Problem:** Fixed 2% stops may be too tight/loose
**Solution:** ATR + L2 depth-based stops

```python
def get_dynamic_stop(price: float, l2_features: dict, atr: float) -> float:
    """Calculate stop based on ATR and L2 depth."""
    spread = l2_features['spread']
    depth_imb = l2_features['depth_imb_k']
    
    # Base stop: 2 ATR
    base_stop_pct = 2 * atr / price
    
    # Adjust for spread (wider spread = wider stop)
    spread_adj = spread / price
    
    # Adjust for depth imbalance (imbalanced = wider stop)
    imb_adj = abs(depth_imb) * 0.01
    
    stop_pct = base_stop_pct + spread_adj + imb_adj
    
    return price * (1 - stop_pct)
```

## Data Quality Monitoring

```python
# Daily quality check
def check_l2_quality(date_str: str) -> dict:
    """Check L2 data quality for a date."""
    return {
        'depth_rate': ...,      # Target: >85%
        'avg_spread': ...,      # Target: <0.02
        'records_collected': ...,  # Target: >1000/day
        'symbols_covered': ...,    # Target: 6
        'time_coverage': ...,      # Target: 4 windows
    }
```

## Timeline

| Week | Milestone | Records Target |
|------|-----------|----------------|
| 1 | Expand collection windows | 10,000 |
| 2 | Stabilize symbol selection | 20,000 |
| 3 | Add cross-symbol features | 35,000 |
| 4 | Begin ML integration | 50,000 |
| 5 | A/B test L2-augmented model | 65,000 |
| 6+ | Production deployment | 80,000+ |

## Success Metrics

1. **Data Quality**
   - Depth rate >85%
   - Spread <0.02 average
   - >1,000 records/day

2. **ML Performance**
   - L2-augmented model improves win rate by >2%
   - Entry timing reduces slippage by >0.5 bps
   - Position sizing reduces max drawdown

3. **Operational**
   - Collection runs without intervention
   - Storage growth <100MB/month
   - Feature computation <1s latency
