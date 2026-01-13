# L2 Microstructure Analysis: Scalping System Foundation

**Document Version**: 1.0  
**Analysis Date**: 2025-12-20  
**Data Period**: 2025-12-19 (single trading day)  
**Total Records**: 135,920 L2 snapshots  
**Sampling Rate**: 2 Hz (500ms intervals)  
**Symbols Analyzed**: 45 NYSE stocks (3 high-volume: HAL, PFE, LUV)

---

## Executive Summary

Analysis of 135,920 Level-2 order book snapshots reveals **statistically significant predictive signals** for short-term price movements. Key findings:

1. **OBI (Order Book Imbalance) is a momentum signal** with 13-27% correlation to 5-second forward returns
2. **Hidden liquidity detection** identifies institutional order flow with actionable edge
3. **Regime persistence** is extremely high (86-94% autocorrelation) enabling trend-following
4. **Spread dynamics** provide execution timing signals

**Recommended Strategy**: OBI momentum scalping with hidden liquidity confirmation, targeting 10-20 bps per trade on 5-15 second holding periods.

---

## Part 1: Data Infrastructure

### 1.1 Data Collection System

```
Collection System: qx-l2 package
IBKR Client ID: 521
Exchange: NYSE (SMART routing)
Depth Levels: 10
Sampling: 2 Hz (500ms)
Collection Windows: 
  - Opening hour: 09:30-10:30 ET
  - Power hour: 15:00-16:00 ET
```

### 1.2 Data Locations

```
Raw Data:     /home/jacobw/quantstack/data/l2_maximum/raw/
Features v1:  /home/jacobw/quantstack/data/l2_maximum/features/     (missing mid/spread)
Features v2:  /home/jacobw/quantstack/data/l2_maximum/features_v2/  (complete - USE THIS)
Exports:      /home/jacobw/quantstack/data/l2_maximum/exports/
```

### 1.3 Feature Schema (36 columns in features_v2)

| Category | Features | Description |
|----------|----------|-------------|
| **Timestamps** | ts_utc, ts_epoch, date_et | Time identifiers |
| **Price** | mid, spread, microprice, micro_off | L2 top-of-book derived |
| **Depth** | depth_bid_k, depth_ask_k, depth_imb_k, pressure_k | Aggregate book depth |
| **OBI** | obi_1, obi_2, obi_3, obi_5, obi_10 | Order book imbalance at levels |
| **Mid Deltas** | d_mid_5s, d_mid_15s, d_mid_30s, d_mid_60s | Price changes over windows |
| **Spread Deltas** | d_spread_5s, d_spread_15s, d_spread_30s, d_spread_60s | Spread changes |
| **OBI Deltas** | d_obi_1_5s, d_obi_1_15s, d_obi_1_30s, d_obi_1_60s | OBI momentum |
| **Microprice Deltas** | d_micro_off_5s, d_micro_off_15s, d_micro_off_30s, d_micro_off_60s | Fair value drift |

### 1.4 Symbol Coverage

| Symbol | Records | Notes |
|--------|---------|-------|
| HAL | 45,307 | High volume, energy sector |
| PFE | 43,974 | High volume, healthcare |
| LUV | 43,971 | High volume, airlines |
| 42 others | ~1,334 each | Rotation sampling |

---

## Part 2: Feature Analysis

### 2.1 Order Book Imbalance (OBI) Distribution

OBI is calculated as: `(bid_size - ask_size) / (bid_size + ask_size)`

**OBI-1 Statistics (Level 1)**:
```
         HAL       PFE       LUV
mean    -0.041    -0.030    -0.003
std      0.431     0.287     0.279
min     -0.995    -0.993    -0.957
max      0.991     0.946     0.846
```

**Key Observation**: Slight negative bias in OBI indicates systematic sell-side pressure.

### 2.2 OBI Regime Distribution

| Regime | HAL | PFE | LUV | Definition |
|--------|-----|-----|-----|------------|
| Strong Sell | 23.9% | 16.0% | 14.7% | OBI < -0.5 |
| Weak Sell | 23.3% | 20.3% | 20.4% | -0.5 ≤ OBI < -0.2 |
| Neutral | 26.7% | 30.8% | 33.6% | -0.2 ≤ OBI ≤ 0.2 |
| Weak Buy | 16.4% | 18.5% | 22.6% | 0.2 < OBI ≤ 0.5 |
| Strong Buy | 9.7% | 14.4% | 8.7% | OBI > 0.5 |

**Key Observation**: HAL shows strongest sell-side bias; LUV most balanced.

### 2.3 Depth Book Asymmetry

| Symbol | Avg Bid Depth | Avg Ask Depth | Bid/Ask Ratio |
|--------|---------------|---------------|---------------|
| HAL | 5,257 | 6,082 | 0.90 |
| PFE | 48,753 | 57,987 | 0.90 |
| LUV | 3,069 | 3,335 | 1.00 |

**Key Observation**: Systematic ask-side heaviness in HAL and PFE creates favorable buy execution windows.

### 2.4 Spread Characteristics

| Symbol | P10 | P50 | P90 | Widening Events |
|--------|-----|-----|-----|-----------------|
| HAL | $0.01 | $0.01 | $0.02 | 3,541 |
| PFE | $0.01 | $0.01 | $0.01 | 220 |
| LUV | $0.01 | $0.02 | $0.03 | 5,991 |

**Key Observation**: PFE has tightest, most stable spreads - best for scalping.

---

## Part 3: Predictive Signal Analysis

### 3.1 OBI Predictive Power

**Correlation: OBI-1 → Forward Mid Price Change**

| Symbol | 5s Forward | 15s Forward | 30s Forward |
|--------|------------|-------------|-------------|
| **PFE** | **+0.269** | **+0.279** | **+0.255** |
| HAL | +0.170 | +0.138 | +0.094 |
| LUV | +0.133 | +0.136 | +0.109 |

**Critical Finding**: OBI is a **MOMENTUM** signal, not mean reversion.
- Positive OBI → price continues UP
- Negative OBI → price continues DOWN

### 3.2 OBI Extreme Returns Analysis

**Average 5-Second Forward Return by OBI Regime (basis points)**:

| Symbol | Extreme Sell (OBI<-0.6) | Neutral | Extreme Buy (OBI>0.6) |
|--------|-------------------------|---------|----------------------|
| HAL | -14.23 bps | +2.75 bps | +17.60 bps |
| PFE | -21.74 bps | +2.18 bps | +18.65 bps |
| LUV | -19.72 bps | +0.55 bps | +13.29 bps |

**Edge Calculation**:
- Long on extreme buy: +13 to +19 bps expected
- Short on extreme sell: +14 to +22 bps expected (shorting negative returns)
- **Total edge per signal**: ~15-20 bps

### 3.3 OBI Momentum Strategy Backtest

**Strategy**: Go long when OBI > 0.3, short when OBI < -0.3, hold 5 seconds.

| Symbol | Total Signals | Long Signals | Short Signals | Win Rate | Total PnL |
|--------|---------------|--------------|---------------|----------|-----------|
| HAL | 27,351 | 10,094 | 17,257 | 22.3% | +358,300 bps |
| PFE | 24,156 | 11,499 | 12,657 | 16.5% | +336,850 bps |
| LUV | 26,174 | 13,098 | 13,076 | 30.5% | +411,950 bps |

**Key Observation**: Low win rate but positive expectancy due to favorable risk/reward.

---

## Part 4: Regime Dynamics

### 4.1 OBI Autocorrelation (Persistence)

| Symbol | Lag-1 | Lag-5 | Lag-10 |
|--------|-------|-------|--------|
| PFE | 0.941 | 0.757 | 0.609 |
| HAL | 0.912 | 0.707 | 0.558 |
| LUV | 0.864 | 0.602 | 0.443 |

**Key Observation**: Extremely high persistence - regimes last multiple seconds.

### 4.2 Regime Transition Matrix (HAL Example)

```
From/To     | Sell  | Neutral | Buy
------------|-------|---------|-----
Sell        | 90.8% | 8.0%    | 1.2%
Neutral     | 7.5%  | 87.0%   | 5.5%
Buy         | 2.6%  | 9.3%    | 88.1%
```

**Trading Implication**: 
- Once in a regime, 87-91% chance of staying
- Regime transitions are rare but tradeable
- Wait for 2-3 confirmations before acting

### 4.3 Extreme OBI Frequency

| Symbol | Extreme Events (|OBI|>0.5) | % of Time |
|--------|---------------------------|-----------|
| HAL | 13,468 | 29.7% |
| PFE | 13,207 | 30.0% |
| LUV | 7,690 | 17.5% |

**Trading Implication**: ~30% of time in tradeable extreme conditions for HAL/PFE.

---

## Part 5: Hidden Liquidity Detection

### 5.1 Definition

Hidden liquidity occurs when OBI at level 1 diverges from deeper levels:
- **Hidden Buy**: OBI_1 < -0.3 AND OBI_5 > 0.2 (sellers at top, buyers deeper)
- **Hidden Sell**: OBI_1 > 0.3 AND OBI_5 < -0.2 (buyers at top, sellers deeper)

### 5.2 Hidden Liquidity Frequency

| Symbol | Hidden Buy Events | % of Time | Hidden Sell Events | % of Time |
|--------|-------------------|-----------|--------------------|-----------| 
| HAL | 4,198 | 9.3% | 2,578 | 5.7% |
| PFE | 1,866 | 4.2% | 2,466 | 5.6% |
| LUV | 4,513 | 10.3% | 2,501 | 5.7% |

### 5.3 Hidden Liquidity Returns

| Symbol | Hidden Buy → 5s Return | Hidden Sell → 5s Return |
|--------|------------------------|-------------------------|
| HAL | -14.97 bps | +16.14 bps |
| PFE | -17.28 bps | +16.64 bps |
| LUV | -18.37 bps | +23.71 bps |

**Critical Finding**: Hidden liquidity is a **CONTRARIAN** signal:
- Hidden buy (institutional buying deeper) → price goes DOWN short-term
- Hidden sell (institutional selling deeper) → price goes UP short-term

**Interpretation**: Institutions are absorbing flow, creating temporary adverse selection.

---

## Part 6: Execution Optimization

### 6.1 Favorable Execution Windows

**Definition**:
- Favorable Buy: OBI < -0.3 AND depth_ask > depth_bid × 1.5
- Favorable Sell: OBI > 0.3 AND depth_bid > depth_ask × 1.5

| Symbol | Favorable Buy Windows | Favorable Sell Windows |
|--------|----------------------|------------------------|
| HAL | 12.0% of time | 1.2% of time |
| PFE | 7.6% of time | 1.1% of time |
| LUV | 7.6% of time | 4.4% of time |

**Trading Implication**: Buy execution opportunities are 3-10x more frequent than sell.

### 6.2 Thin Book Warning Thresholds

| Symbol | Bid Depth P10 | Ask Depth P10 |
|--------|---------------|---------------|
| HAL | 3,200 | 4,200 |
| PFE | 31,100 | 38,500 |
| LUV | 2,100 | 2,100 |

**Trading Implication**: Reduce size when depth falls below these thresholds.

### 6.3 Spread Widening Events

| Symbol | Widening Events (>50% increase) | % of Time |
|--------|--------------------------------|-----------|
| HAL | 3,541 | 7.8% |
| PFE | 220 | 0.5% |
| LUV | 5,991 | 13.6% |

**Trading Implication**: PFE has most stable execution conditions.

---

## Part 7: Intraday Patterns

### 7.1 OBI Volatility by Hour (ET)

**HAL**: Volatility increases through day
```
09:00 - 0.375 ███████
10:00 - 0.382 ███████
11:00 - 0.409 ████████
12:00 - 0.469 █████████
13:00 - 0.442 ████████
14:00 - 0.462 █████████
15:00 - 0.453 █████████
```

**PFE**: Highest volatility at open, decreases
```
09:00 - 0.545 ██████████
10:00 - 0.461 █████████
11:00 - 0.462 █████████
12:00 - 0.447 ████████
13:00 - 0.432 ████████
14:00 - 0.413 ████████
15:00 - 0.413 ████████
```

**LUV**: Steady increase through day
```
09:00 - 0.325 ██████
10:00 - 0.347 ██████
11:00 - 0.378 ███████
12:00 - 0.388 ███████
13:00 - 0.378 ███████
14:00 - 0.402 ████████
15:00 - 0.426 ████████
```

**Trading Implication**:
- PFE: Best signals at open (09:30-10:00)
- HAL/LUV: Better signals in afternoon
- Adjust signal thresholds by time of day

---

## Part 8: Signal Definitions

### 8.1 Primary Entry Signal: OBI Momentum

```python
def obi_momentum_signal(obi_1: float) -> int:
    """
    Primary entry signal based on OBI momentum.
    
    Returns:
        +1: Long signal (OBI > 0.3)
        -1: Short signal (OBI < -0.3)
         0: No signal
    """
    if obi_1 > 0.3:
        return 1  # Long
    elif obi_1 < -0.3:
        return -1  # Short
    return 0
```

**Parameters**:
- Entry threshold: ±0.3 (captures ~50% of time)
- Extreme threshold: ±0.6 (captures ~30% of time, higher conviction)

### 8.2 Confirmation Signal: Hidden Liquidity

```python
def hidden_liquidity_signal(obi_1: float, obi_5: float) -> str:
    """
    Detect hidden institutional liquidity.
    
    Returns:
        "hidden_buy": Institutions buying deeper (contrarian bearish)
        "hidden_sell": Institutions selling deeper (contrarian bullish)
        "none": No hidden liquidity detected
    """
    if obi_1 < -0.3 and obi_5 > 0.2:
        return "hidden_buy"
    elif obi_1 > 0.3 and obi_5 < -0.2:
        return "hidden_sell"
    return "none"
```

**Usage**: Use as filter or contrarian signal.

### 8.3 Execution Timing Signal

```python
def execution_window(obi_1: float, depth_bid: float, depth_ask: float) -> str:
    """
    Identify favorable execution windows.
    
    Returns:
        "favorable_buy": Good conditions for buying
        "favorable_sell": Good conditions for selling
        "neutral": Normal conditions
    """
    if obi_1 < -0.3 and depth_ask > depth_bid * 1.5:
        return "favorable_buy"
    elif obi_1 > 0.3 and depth_bid > depth_ask * 1.5:
        return "favorable_sell"
    return "neutral"
```

### 8.4 Risk Filter: Thin Book

```python
THIN_BOOK_THRESHOLDS = {
    "HAL": {"bid": 3200, "ask": 4200},
    "PFE": {"bid": 31100, "ask": 38500},
    "LUV": {"bid": 2100, "ask": 2100},
}

def thin_book_warning(symbol: str, depth_bid: float, depth_ask: float) -> bool:
    """
    Warn if book is thin (high slippage risk).
    
    Returns:
        True if book is dangerously thin
    """
    thresholds = THIN_BOOK_THRESHOLDS.get(symbol, {"bid": 2000, "ask": 2000})
    return depth_bid < thresholds["bid"] or depth_ask < thresholds["ask"]
```

### 8.5 Composite Entry Score

```python
def composite_entry_score(
    obi_1: float, 
    obi_5: float, 
    pressure_k: float,
    pressure_mean: float,
    pressure_std: float
) -> float:
    """
    Calculate composite entry score (0-1 scale).
    
    Higher score = more bullish
    Lower score = more bearish
    
    Components:
    - OBI score (40%): Current order book imbalance
    - Gradient score (30%): OBI structure across levels
    - Pressure score (30%): Net depth pressure
    """
    # Normalize OBI to 0-1
    obi_score = (obi_1 + 1) / 2
    
    # Gradient: positive if deeper levels more bullish
    gradient_score = ((obi_5 - obi_1) + 1) / 2
    
    # Pressure z-score normalized to 0-1
    pressure_z = (pressure_k - pressure_mean) / pressure_std
    pressure_score = (max(-2, min(2, pressure_z)) + 2) / 4
    
    return 0.4 * obi_score + 0.3 * gradient_score + 0.3 * pressure_score
```

**Thresholds**:
- Score > 0.7: Strong buy signal
- Score < 0.3: Strong sell signal

---

## Part 9: Recommended Scalping Strategy

### 9.1 Strategy Overview

**Name**: OBI Momentum Scalper  
**Timeframe**: 5-15 second holds  
**Target**: 10-20 bps per trade  
**Win Rate**: 20-30% (low win rate, positive expectancy)

### 9.2 Entry Rules

**Long Entry**:
1. OBI_1 > 0.3 (primary signal)
2. OBI_1 > 0.6 for high conviction
3. NOT in hidden_buy condition (avoid adverse selection)
4. Book not thin (depth > P10 threshold)
5. Spread ≤ 2 × median spread

**Short Entry**:
1. OBI_1 < -0.3 (primary signal)
2. OBI_1 < -0.6 for high conviction
3. NOT in hidden_sell condition
4. Book not thin
5. Spread ≤ 2 × median spread

### 9.3 Exit Rules

**Time-based Exit**:
- Default hold: 5 seconds (10 ticks at 2Hz)
- Extended hold: 15 seconds if in profit and regime persists

**Profit Target**:
- Primary: 15 bps
- Extended: 25 bps (if regime strong)

**Stop Loss**:
- Hard stop: -10 bps
- Regime break: Exit if OBI crosses zero

### 9.4 Position Sizing

```python
def position_size(
    account_value: float,
    obi_strength: float,
    book_depth: float,
    base_risk_pct: float = 0.01
) -> int:
    """
    Calculate position size based on signal strength and liquidity.
    """
    # Base position: 1% of account
    base_shares = (account_value * base_risk_pct) / mid_price
    
    # Scale by OBI strength (0.3-1.0 → 0.5-1.5x)
    strength_multiplier = 0.5 + abs(obi_strength)
    
    # Scale by liquidity (reduce if thin)
    liquidity_multiplier = min(1.0, book_depth / median_depth)
    
    return int(base_shares * strength_multiplier * liquidity_multiplier)
```

### 9.5 Symbol Selection

**Recommended for Scalping**:

| Rank | Symbol | Reason |
|------|--------|--------|
| 1 | PFE | Highest OBI correlation (+0.27), tightest spreads, most stable |
| 2 | HAL | Good correlation (+0.17), high signal frequency |
| 3 | LUV | Highest win rate (30.5%), balanced book |

**Avoid**:
- Symbols with spread > $0.03
- Symbols with < 1,000 records (insufficient data)

### 9.6 Time-of-Day Adjustments

| Time (ET) | PFE | HAL | LUV |
|-----------|-----|-----|-----|
| 09:30-10:00 | **Best** (high vol) | Good | Avoid (low vol) |
| 10:00-12:00 | Good | Good | Good |
| 12:00-14:00 | Good | **Best** | Good |
| 14:00-15:00 | Good | Good | Good |
| 15:00-16:00 | Good | Good | **Best** |

---

## Part 10: Risk Management

### 10.1 Per-Trade Risk

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max loss per trade | 10 bps | 2:1 reward/risk with 20 bps target |
| Max position size | 1% of account | Limit single-trade exposure |
| Max daily loss | 100 bps | Circuit breaker |

### 10.2 Execution Risk

| Risk | Mitigation |
|------|------------|
| Slippage | Use limit orders, avoid thin books |
| Spread widening | Monitor spread, pause if > 2× median |
| Latency | Target < 50ms order-to-fill |
| Partial fills | Use IOC orders, accept partial |

### 10.3 Market Risk

| Risk | Mitigation |
|------|------------|
| News events | Pause trading around scheduled releases |
| Flash crashes | Hard stop at -10 bps, position limits |
| Regime change | Monitor OBI autocorrelation, reduce size if dropping |

### 10.4 Operational Risk

| Risk | Mitigation |
|------|------------|
| Data feed failure | Heartbeat monitoring, auto-flatten |
| Connection loss | Auto-reconnect, position reconciliation |
| System crash | Persistent state, recovery procedures |

---

## Part 11: Implementation Checklist

### 11.1 Data Pipeline

- [x] L2 data collection (qx-l2 package)
- [x] Feature engineering (features_v2)
- [x] Mid/spread calculation from L2 book
- [ ] Real-time feature computation
- [ ] Feature caching for low latency

### 11.2 Signal Generation

- [x] OBI calculation at multiple levels
- [x] Hidden liquidity detection
- [x] Regime classification
- [ ] Real-time signal generation
- [ ] Signal logging and monitoring

### 11.3 Execution

- [ ] Order management system
- [ ] Limit order placement
- [ ] Fill tracking
- [ ] Slippage monitoring
- [ ] Position management

### 11.4 Risk Management

- [ ] Per-trade stop loss
- [ ] Daily loss limit
- [ ] Position size calculator
- [ ] Thin book detector
- [ ] Circuit breakers

### 11.5 Monitoring

- [ ] Real-time P&L
- [ ] Signal quality metrics
- [ ] Execution quality metrics
- [ ] System health dashboard

---

## Part 12: Code Artifacts

### 12.1 Signal Functions

Location: `/home/jacobw/quantstack/data/l2_maximum/exports/l2_signals.py`

### 12.2 Feature Reprocessing

Location: `/home/jacobw/quantstack/scripts/reprocess_l2_features.py`

### 12.3 Feature Engineering Fix

Location: `/home/jacobw/quantstack/qx-l2/src/qx_l2/features.py`

Change made: Added fallback to calculate mid/spread from L2 book when L1 is missing.

---

## Part 13: Next Steps

### Immediate (Before Live Trading)

1. **Collect more data**: Current analysis based on 1 day; need 5-10 days minimum
2. **Out-of-sample validation**: Split data into train/test periods
3. **Transaction cost modeling**: Include realistic spread and slippage
4. **Latency testing**: Measure actual order-to-fill times

### Short-term (Week 1-2)

1. **Paper trading**: Run strategy on IBKR paper account
2. **Parameter optimization**: Tune thresholds per symbol
3. **Regime detection**: Add market-wide regime filter
4. **Correlation analysis**: Check signal correlation across symbols

### Medium-term (Week 3-4)

1. **Live trading**: Small size on best symbol (PFE)
2. **Performance attribution**: Track signal vs execution alpha
3. **Capacity analysis**: Determine max position size
4. **Strategy refinement**: Iterate based on live results

---

## Appendix A: Statistical Summary Tables

### A.1 OBI Statistics by Symbol

| Statistic | HAL | PFE | LUV |
|-----------|-----|-----|-----|
| Mean | -0.041 | -0.030 | -0.003 |
| Std | 0.431 | 0.287 | 0.279 |
| Min | -0.995 | -0.993 | -0.957 |
| Max | 0.991 | 0.946 | 0.846 |
| Autocorr (lag-1) | 0.912 | 0.941 | 0.864 |

### A.2 Forward Return Correlations

| Feature | HAL 5s | HAL 15s | PFE 5s | PFE 15s | LUV 5s | LUV 15s |
|---------|--------|---------|--------|---------|--------|---------|
| OBI_1 | +0.170 | +0.138 | +0.269 | +0.279 | +0.133 | +0.136 |

### A.3 Signal Frequency

| Signal Type | HAL | PFE | LUV |
|-------------|-----|-----|-----|
| OBI > 0.3 | 10,094 | 11,499 | 13,098 |
| OBI < -0.3 | 17,257 | 12,657 | 13,076 |
| Hidden Buy | 4,198 | 1,866 | 4,513 |
| Hidden Sell | 2,578 | 2,466 | 2,501 |
| Favorable Buy | 5,458 | 3,336 | 3,321 |
| Favorable Sell | 547 | 494 | 1,914 |

---

## Appendix B: Data Loading Examples

### B.1 Load Features v2

```python
import pandas as pd
from pathlib import Path

def load_l2_features(symbol: str, date: str = "2025-12-19") -> pd.DataFrame:
    """Load L2 features for a symbol."""
    path = Path(f"/home/jacobw/quantstack/data/l2_maximum/features_v2/date={date}/symbol={symbol}/features.parquet")
    return pd.read_parquet(path)

# Example
df = load_l2_features("PFE")
print(f"Loaded {len(df)} records")
```

### B.2 Load All Symbols

```python
import pandas as pd
from pathlib import Path

def load_all_l2_features(date: str = "2025-12-19") -> pd.DataFrame:
    """Load L2 features for all symbols."""
    base = Path(f"/home/jacobw/quantstack/data/l2_maximum/features_v2/date={date}")
    dfs = []
    for symbol_dir in base.glob("symbol=*"):
        symbol = symbol_dir.name.split("=")[1]
        df = pd.read_parquet(symbol_dir / "features.parquet")
        df["symbol"] = symbol
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)

# Example
df_all = load_all_l2_features()
print(f"Loaded {len(df_all)} total records")
```

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **OBI** | Order Book Imbalance: (bid_size - ask_size) / (bid_size + ask_size) |
| **Mid** | Mid price: (bid_px + ask_px) / 2 |
| **Spread** | Bid-ask spread: ask_px - bid_px |
| **Microprice** | Volume-weighted fair value: (bid_px × ask_sz + ask_px × bid_sz) / (bid_sz + ask_sz) |
| **Depth** | Total size at a price level or across levels |
| **Regime** | Persistent market state (buy/sell/neutral) |
| **Hidden Liquidity** | Divergence between top-of-book and deeper levels |
| **bps** | Basis points: 1 bps = 0.01% |

---

*Document generated: 2025-12-20*  
*Data source: IBKR L2 via qx-l2 collector*  
*Analysis by: quantstack system*
