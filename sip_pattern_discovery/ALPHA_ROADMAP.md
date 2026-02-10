# Building a Positive Alpha System: A Practical Roadmap

**Date:** 2026-01-19  
**Context:** Post-mortem of pattern discovery system + available resources  
**Goal:** Design a system that can generate sustainable alpha

---

## Your Key Advantage: Level 2 Data

**This changes everything.**

The previous system failed because it used:
- Public price data (crowded)
- Standard technical indicators (arbitraged away)
- Data mining without theory (overfitting)

**Level 2 order book data is where real alpha lives because:**
1. It's harder to process (most traders can't)
2. It reveals supply/demand BEFORE price moves
3. It shows institutional activity (information asymmetry)
4. It's less crowded than price-based signals

---

## The New Approach: Theory-First, Data-Second

### Core Principle

**Old approach:** "What patterns exist in the data?" → Overfitting  
**New approach:** "What economic mechanism should cause predictable price moves?" → Testable hypothesis

### Three Hypotheses Worth Testing

#### Hypothesis 1: Order Flow Imbalance

**Theory:** When buy orders significantly exceed sell orders, price will rise (and vice versa).

**Why it should work:**
- Causal mechanism: Supply/demand economics
- Information advantage: Level 2 shows imbalance BEFORE price moves
- Less crowded: Most retail traders use price, not order flow

**Testable prediction:** Stocks with book_imbalance > 0.3 will have positive returns over next 5-15 minutes.

#### Hypothesis 2: Institutional Footprints

**Theory:** Large players leave detectable traces in the order book. Following them captures their information edge.

**Why it should work:**
- Causal mechanism: Institutions have research/information
- Information advantage: Can detect large orders, sweeps, icebergs
- Timing: Can act before full execution completes

**Testable prediction:** Stocks with detected large orders will continue in that direction for 15-30 minutes.

#### Hypothesis 3: Liquidity Vacuums

**Theory:** When market makers suddenly pull liquidity, price overshoots and then mean-reverts.

**Why it should work:**
- Causal mechanism: Temporary mispricing due to panic/uncertainty
- Information advantage: Can detect liquidity withdrawal in real-time
- Mean reversion: Price returns to fair value

**Testable prediction:** Sudden depth drops (>50%) followed by price spike will revert within 10 minutes.

---

## Feature Engineering: Level 2 Signals

### Order Book Features

```python
# Book imbalance (most important)
book_imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
# Range: -1 (all asks) to +1 (all bids)
# Signal: > 0.3 bullish, < -0.3 bearish

# Spread (liquidity indicator)
spread_pct = (best_ask - best_bid) / mid_price * 100
# Tight spread = liquid, wide spread = illiquid/uncertain

# Book depth ratio (support vs resistance)
depth_ratio = sum(bid_depth_levels_1_5) / sum(ask_depth_levels_1_5)
# > 1.5 = strong support, < 0.67 = strong resistance

# Book slope (how quickly depth drops off)
book_slope = depth_level_1 / depth_level_5
# Steep slope = thin book, vulnerable to moves
```

### Order Flow Features

```python
# Trade imbalance (actual executed flow)
trade_imbalance = (buy_volume - sell_volume) / total_volume
# Classify trades by aggressor (trade at ask = buy, trade at bid = sell)

# Large order detection
large_order_threshold = rolling_avg_order_size * 3
large_orders = orders.where(size > large_order_threshold)

# Sweep detection (taking multiple levels)
sweep = price_moved_multiple_levels AND high_volume AND short_time

# Aggressive ratio
aggressive_ratio = market_orders / total_orders
# High = urgency, low = patience
```

### Microstructure Features

```python
# Quote activity (changes per second)
quote_intensity = quote_changes / time_window
# High = active trading, low = quiet

# Cancel ratio (HFT indicator)
cancel_ratio = cancelled_orders / total_orders
# High = HFT activity, potential manipulation

# Time between trades
trade_interval = mean(time_between_trades)
# Short = urgent, long = patient
```

---

## Validation Framework: No More Overfitting

### 1. Walk-Forward Validation (Required)

```
Period 1: Train Jan-Mar, Validate Apr
Period 2: Train Feb-Apr, Validate May
Period 3: Train Mar-May, Validate Jun
...continue rolling...

REQUIREMENT: Strategy must be profitable in >70% of validation periods
```

### 2. Regime Stratification (Required)

Test separately in:
- Bull market (SPY > 20 SMA)
- Bear market (SPY < 20 SMA)
- High volatility (VIX > 20)
- Low volatility (VIX < 20)

**REQUIREMENT:** Strategy must work in at least 2 of 4 regimes

### 3. Statistical Thresholds (Strict)

| Metric | Minimum | Target |
|--------|---------|--------|
| Sharpe Ratio (OOS) | > 0.75 | > 1.5 |
| Win Rate | > 52% | > 55% |
| Profit Factor | > 1.2 | > 1.5 |
| t-statistic | > 2.0 | > 3.0 |
| Min Trades (validation) | 500 | 1000 |

### 4. Execution Simulation (Critical)

```python
# Use actual Level 2 data for realistic fills
def simulate_execution(order, book_snapshot):
    if order.type == 'market':
        # Walk the book, calculate actual fill price
        fill_price = walk_book(book_snapshot, order.size, order.side)
        slippage = abs(fill_price - mid_price) / mid_price
    
    # Add latency (50-100ms for retail)
    execution_delay = random.uniform(0.05, 0.1)
    
    # Check if order would have been filled
    # (price may have moved during delay)
    
    return fill_price, slippage, execution_delay
```

---

## Strategy Templates

### Strategy A: Order Flow Momentum

**Hypothesis:** Strong order flow imbalance predicts short-term direction

```yaml
Entry Conditions:
  - book_imbalance > 0.35 (strong bid pressure)
  - trade_imbalance > 0.25 (confirming flow)
  - spread < 0.05% (liquid enough to trade)
  - no_large_ask_wall (no obvious resistance)

Entry: Market order (speed matters)
Position Size: 1-2% of capital

Exit Conditions:
  - Target: +0.4% profit
  - Stop: -0.25% loss
  - Time: 10 minutes max
  - Signal: book_imbalance reverses to < 0

Risk/Reward: 1.6:1
Expected Win Rate: 55%+
Expected Sharpe: 1.0-1.5
```

**Why this should work:**
- Causal: Imbalance = more buyers than sellers
- Timing: See it before price moves
- Edge: Processing Level 2 in real-time

### Strategy B: Whale Following

**Hypothesis:** Large institutional orders signal informed trading

```yaml
Entry Conditions:
  - large_order_detected (> 5x average size)
  - order_direction matches recent_flow
  - stock_is_in_play (high relative volume)
  - not_near_resistance (room to run)

Entry: Market order within 30 seconds of detection
Position Size: 1% of capital

Exit Conditions:
  - Target: +0.8% profit
  - Stop: -0.4% loss
  - Time: 30 minutes max
  - Signal: large order completes or reverses

Risk/Reward: 2:1
Expected Win Rate: 50%+
Expected Sharpe: 0.8-1.2
```

**Why this should work:**
- Causal: Institutions have information edge
- Timing: Can detect before full execution
- Risk: Institutions can be wrong (hence lower win rate)

### Strategy C: Liquidity Fade

**Hypothesis:** Sudden liquidity withdrawal causes temporary mispricing

```yaml
Entry Conditions:
  - depth_drop > 50% on one side (sudden withdrawal)
  - price_spike in opposite direction (overreaction)
  - spread_widened (uncertainty)
  - no_news_catalyst (not fundamental)

Entry: Limit order at mean-reversion level
Position Size: 0.5-1% of capital (higher risk)

Exit Conditions:
  - Target: +0.3% profit (quick scalp)
  - Stop: -0.3% loss (tight)
  - Time: 5 minutes max
  - Signal: depth returns to normal

Risk/Reward: 1:1
Expected Win Rate: 60%+
Expected Sharpe: 1.0-1.5
```

**Why this should work:**
- Causal: Panic creates mispricing
- Timing: Can detect in real-time
- Risk: Sometimes liquidity leaves for good reason

---

## Paper Trading Protocol

### Phase 1: Signal Validation (Week 1-4)

**Goal:** Verify signals fire correctly and match backtest

```
Daily Tasks:
1. Run live signal generation
2. Log all signals (don't trade yet)
3. Track what WOULD have happened
4. Compare to backtest expectations

Success Criteria:
- Signal frequency matches backtest (±20%)
- Signal quality matches backtest (similar win rate)
- No obvious bugs or data issues
```

### Phase 2: Paper Execution (Week 5-12)

**Goal:** Test execution quality and real-world performance

```
Daily Tasks:
1. Execute all signals in IBKR paper account
2. Log entry price, exit price, slippage
3. Track P&L vs theoretical P&L
4. Note any execution issues

Success Criteria:
- Actual Sharpe > 0.75 (minimum viable)
- Slippage < 0.05% per trade
- No systematic execution problems
- Performance consistent across weeks
```

### Phase 3: Stress Testing (Week 13-16)

**Goal:** Test behavior in adverse conditions

```
Monitor For:
- High volatility days (VIX spikes)
- News events (earnings, Fed)
- Low liquidity periods (lunch, close)
- Regime changes (trend reversals)

Success Criteria:
- No catastrophic losses on any single day
- Strategy degrades gracefully (not blows up)
- Clear understanding of when NOT to trade
```

### Go/No-Go Decision

After 16 weeks of paper trading:

| Metric | No-Go | Proceed with Caution | Go |
|--------|-------|---------------------|-----|
| Sharpe | < 0.5 | 0.5 - 1.0 | > 1.0 |
| Max Drawdown | > 15% | 10-15% | < 10% |
| Win Rate | < 48% | 48-52% | > 52% |
| Profit Factor | < 1.0 | 1.0-1.2 | > 1.2 |
| Execution Quality | Poor | Acceptable | Good |

**If No-Go:** Return to research, revise hypothesis  
**If Caution:** Extend paper trading 4 more weeks  
**If Go:** Proceed to small live trading

---

## Live Trading: Scaling Protocol

### Stage 1: Micro Live (Month 1-2)

```
Position Size: 10% of intended (e.g., $100 if target is $1000)
Goal: Validate execution in real market
Monitor: Slippage, fills, market impact
```

### Stage 2: Small Live (Month 3-4)

```
Position Size: 25% of intended
Goal: Build confidence, refine execution
Monitor: P&L consistency, drawdowns
```

### Stage 3: Medium Live (Month 5-6)

```
Position Size: 50% of intended
Goal: Test capacity constraints
Monitor: Market impact, fill rates
```

### Stage 4: Full Live (Month 7+)

```
Position Size: 100% of intended
Goal: Steady state operation
Monitor: Continuous performance tracking
```

### Kill Switches

**Automatic halt if:**
- Daily loss > 3% of capital
- Weekly loss > 7% of capital
- Monthly loss > 12% of capital
- 5 consecutive losing days
- Sharpe drops below 0.5 for 30 days

---

## Risk Management Framework

### Position Sizing

```python
def calculate_position_size(signal_strength, volatility, capital):
    base_size = capital * 0.02  # 2% base
    
    # Adjust for signal strength (0.5 to 1.5x)
    strength_multiplier = 0.5 + signal_strength
    
    # Adjust for volatility (inverse relationship)
    vol_multiplier = baseline_vol / current_vol
    vol_multiplier = max(0.5, min(1.5, vol_multiplier))
    
    position_size = base_size * strength_multiplier * vol_multiplier
    
    # Hard cap at 3% of capital
    return min(position_size, capital * 0.03)
```

### Portfolio Constraints

```yaml
Max Single Position: 3% of capital
Max Total Exposure: 15% of capital
Max Correlated Positions: 2 (same sector/signal)
Max Daily Trades: 20 (avoid overtrading)
```

### Stop Loss Rules

```yaml
Hard Stop: -0.5% per position (no exceptions)
Time Stop: Exit if no profit after max_hold_time
Trailing Stop: Lock in 50% of gains after +0.3%
Portfolio Stop: Halt all trading if daily loss > 2%
```

---

## Technology Stack

### Data Pipeline

```
Level 2 Feed (IBKR) → Feature Calculator → Signal Generator → Order Manager
                              ↓
                      Historical DB (for research)
```

### Key Components

```python
# 1. Real-time feature calculator
class Level2FeatureEngine:
    def update(self, book_snapshot, trade):
        self.book_imbalance = self.calc_book_imbalance(book_snapshot)
        self.trade_imbalance = self.calc_trade_imbalance(trade)
        self.spread = self.calc_spread(book_snapshot)
        # ... other features

# 2. Signal generator
class SignalGenerator:
    def check_signals(self, features):
        signals = []
        if self.order_flow_signal(features):
            signals.append(('ORDER_FLOW', features.symbol, 'LONG'))
        if self.whale_signal(features):
            signals.append(('WHALE', features.symbol, 'LONG'))
        return signals

# 3. Order manager
class OrderManager:
    def execute(self, signal):
        # Check risk limits
        if not self.risk_check(signal):
            return None
        
        # Submit order via IBKR
        order = self.create_order(signal)
        self.ibkr.submit(order)
        
        # Track for exit management
        self.open_positions.append(order)
```

### Monitoring Dashboard

Track in real-time:
- Open positions and P&L
- Signal frequency and quality
- Execution metrics (slippage, fill rate)
- Risk metrics (exposure, drawdown)
- Strategy performance by type

---

## Expected Outcomes

### Realistic Expectations

| Metric | Conservative | Target | Optimistic |
|--------|--------------|--------|------------|
| Annual Return | 15% | 30% | 50% |
| Sharpe Ratio | 1.0 | 1.5 | 2.0 |
| Max Drawdown | 12% | 8% | 5% |
| Win Rate | 52% | 55% | 58% |
| Trades/Day | 5 | 10 | 15 |

### What Success Looks Like

**Month 1-3:** Paper trading, refining signals, learning execution  
**Month 4-6:** Small live, building confidence, modest profits  
**Month 7-12:** Scaling up, consistent performance, Sharpe > 1.0  
**Year 2+:** Steady state, continuous improvement, adding strategies

### What Failure Looks Like

- Paper trading Sharpe < 0.5 after 3 months → Hypothesis is wrong
- Live execution much worse than paper → Execution model is wrong
- Performance degrades over time → Alpha is decaying
- Large drawdowns → Risk management is wrong

**Failure is information.** Use it to improve.

---

## Summary: The Path Forward

### Phase 1: Research (Weeks 1-4)
1. Build Level 2 feature engine
2. Implement three strategy hypotheses
3. Backtest with walk-forward validation
4. Require Sharpe > 0.75 in validation

### Phase 2: Paper Trading (Weeks 5-16)
1. Deploy to IBKR paper account
2. Track execution quality
3. Compare to backtest
4. Stress test in adverse conditions

### Phase 3: Live Trading (Months 5+)
1. Start with 10% size
2. Scale gradually over 6 months
3. Monitor continuously
4. Adapt and improve

### Key Differences from Previous System

| Aspect | Old System | New System |
|--------|------------|------------|
| Data | Price only | Level 2 order book |
| Approach | Data mining | Hypothesis testing |
| Validation | Single holdout | Walk-forward + regime |
| Execution | Assumed perfect | Simulated realistic |
| Testing | Backtest only | Paper trade 3+ months |
| Scaling | All at once | Gradual over 6 months |

### The Bottom Line

**Level 2 data is your edge.** Most traders can't process it. Use it to:
1. See order flow before price moves
2. Detect institutional activity
3. Identify liquidity imbalances

**Theory-first approach prevents overfitting.** Start with:
1. Economic hypothesis (why should this work?)
2. Testable prediction (what should we observe?)
3. Rigorous validation (does it actually work?)

**Paper trading is non-negotiable.** Backtest ≠ reality. You must:
1. Validate signals fire correctly
2. Test execution quality
3. Experience real market conditions

**Alpha is hard but possible.** Expect:
1. Many failed hypotheses
2. Modest returns (Sharpe 1-2, not 10)
3. Continuous adaptation required
4. Gradual scaling over months

**This is the path to sustainable alpha.**
