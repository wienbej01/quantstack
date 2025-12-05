# Critical Findings - System Audit
**Date:** December 5, 2025  
**Status:** 🚨 SYSTEM BROKEN - DO NOT USE FOR TRADING

---

## TL;DR

**The backtest engine does NOT implement stop loss or take profit monitoring.**

All your trades are running without risk management. The 0% win rate is because:
1. Winners never close at take profit (it's not checked)
2. Losers never close at stop loss (it's not checked)  
3. Everything exits at timeout or EOD close
4. Commission ($0.70) dominates small moves

**This is not a parameter problem. This is a missing feature.**

---

## Specific Code Issues

### Issue 1: Stop/Target Set But Never Used

**File:** `extensions/intraday_ml/backtest.py` (lines 476-491)

```python
# Code SETS stop_loss and take_profit on order object:
if "stop_loss_pct" in order and pd.notna(order["stop_loss_pct"]):
    if side == OrderSide.BUY:
        stop_loss_price = current_close * (1 - order["stop_loss_pct"])
    else:
        stop_loss_price = current_close * (1 + order["stop_loss_pct"])
    order_obj.stop_loss = stop_loss_price  # ← Sets attribute

if "take_profit_pct" in order and pd.notna(order["take_profit_pct"]):
    if side == OrderSide.BUY:
        take_profit_price = current_close * (1 + order["take_profit_pct"])
    else:
        take_profit_price = current_close * (1 - order["take_profit_pct"])
    order_obj.take_profit = take_profit_price  # ← Sets attribute
```

**Problem:** Order class has NO `stop_loss` or `take_profit` attributes (see order.py line 48-70)

---

### Issue 2: Engine Never Checks Positions

**File:** `qx-backtest/src/qx_backtest/engine.py` (lines 291-350)

```python
def run(self, data: pd.DataFrame, strategy_func: Any) -> BacktestResult:
    for processed_bars, (timestamp, group) in enumerate(data.groupby("ts")):
        # Update portfolio
        # Call strategy
        strategy_func(self, bar_dict)
        
        # Process pending orders
        self._process_pending_orders(group)
        
        # ← NO CODE HERE TO CHECK POSITIONS AGAINST STOPS/TARGETS
        
        # Record state
        self._record_portfolio_state()
```

**What's missing:**
```python
# Should exist but doesn't:
def _check_position_exits(self, bar_data):
    """Check if any positions should exit due to stop/target."""
    for symbol, position in self.portfolio.positions.items():
        if hasattr(position, 'stop_loss'):
            if bar_data['low'] <= position.stop_loss:
                # Generate stop exit order
        if hasattr(position, 'take_profit'):
            if bar_data['high'] >= position.take_profit:
                # Generate target exit order
```

---

### Issue 3: No Risk Metrics Recorded

**File:** `qx-backtest/src/qx_backtest/fill.py` (lines 10-50)

```python
@dataclass
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    timestamp: int
    commission: float = 0.0
    fees: dict[str, float] = field(default_factory=dict)
    # ← NO stop_dist_ps field
    # ← NO slippage_est field
    # ← NO r_multiple field
    # ← NO exit_reason field
```

**Result:** All these show as 0.0 in output

---

### Issue 4: Slippage Calculated But Not Recorded

**File:** `qx-backtest/src/qx_backtest/fill.py` (lines 150-165)

```python
def _get_fill_price(self, order: Order, bar_data: dict[str, Any]) -> float | None:
    if order.order_type == OrderType.MARKET:
        base_price = close_price
        slippage_factor = 1 + (self.slippage_bps / 10000)  # ← Calculated
        
        if order.side == OrderSide.BUY:
            return base_price * slippage_factor  # ← Applied to price
        else:
            return base_price / slippage_factor
```

**Problem:** Slippage applied to price but not recorded separately in Fill object

---

## What Actually Happens to Your Trades

### Entry (Works Correctly)
1. Policy generates order with stop_loss_pct and take_profit_pct
2. Order submitted to engine
3. Engine fills order at market price + slippage
4. Position opened

### During Hold (BROKEN)
1. Engine processes each bar
2. Calls strategy function
3. Processes pending orders
4. **NEVER checks if position should exit at stop/target**
5. Position continues to next bar

### Exit (Only 3 Ways)
1. **Timeout:** Policy generates exit order after X minutes
2. **EOD Close:** Force flat at 15:59:59 ET
3. **Manual:** Policy decides to exit for other reason

**Missing:** Stop hit, Target hit

---

## Evidence from Your Data

### From Fills DataFrame
```
stop_dist_ps    0.0  ← Should be $0.108 (1.0 ATR)
fees            0.0  ← Should have commission breakdown
slippage_est    0.0  ← Should be ~5 bps
r_multiple      0.0  ← Should be calculated from exit
```

### From Matched Trades
```
Duration: 94% exit at 20 minutes  ← Timeout, not stop
PnL: -$0.70 average              ← Commission + small loss
Win rate: 0.3%                   ← No targets being hit
```

### From Test Output
```
Sharpe: -207  ← Negative because all trades lose
Trades: 3     ← Very few because most rejected
Win rate: 0%  ← No take profits triggering
```

---

## Why This Explains Everything

### 0% Win Rate
- Take profit NEVER triggers
- Winners turn into losers as price reverses
- Only exit is timeout or EOD

### All Trades Lose $0.70
- Commission: $0.70 (2 × $0.35)
- Small adverse move before timeout
- No stop to limit loss
- No target to lock profit

### 94% Exit at 20 Minutes
- Policy timeout at 20 min (early_cut)
- Not stop loss (which doesn't work)
- Explains clustering

### Removing Timeout Didn't Help
- Still no stops or targets
- Just longer hold times
- Still 0% win rate

---

## Gradient of Certainty Over Time

**Your observation is correct.** Here's why:

### Time 0-10 minutes
- Entry executed
- Small slippage applied
- Position slightly underwater (-$0.35 commission)

### Time 10-20 minutes
- Price moves randomly
- No stop protection
- No target capture
- Adverse selection accumulates

### Time 20+ minutes
- Timeout triggers OR
- Price has reversed against you
- Exit at loss
- Commission + adverse move = -$0.70

**The longer you hold without stops/targets, the worse it gets.**

---

## What Needs to Be Built

### 1. Add Stop/Target to Order Class
```python
@dataclass
class Order:
    # ... existing fields ...
    stop_loss: float | None = None
    take_profit: float | None = None
```

### 2. Transfer to Position on Fill
```python
def _apply_fill(self, fill, order):
    # ... existing code ...
    if hasattr(order, 'stop_loss'):
        position.stop_loss = order.stop_loss
    if hasattr(order, 'take_profit'):
        position.take_profit = order.take_profit
```

### 3. Check Positions Every Bar
```python
def _check_position_exits(self, bar_data):
    for symbol, position in self.portfolio.positions.items():
        # Check stop
        if position.stop_loss and bar_data['low'] <= position.stop_loss:
            self._generate_stop_exit(symbol, position, bar_data)
        
        # Check target
        if position.take_profit and bar_data['high'] >= position.take_profit:
            self._generate_target_exit(symbol, position, bar_data)
```

### 4. Record Exit Reason
```python
@dataclass
class Fill:
    # ... existing fields ...
    exit_reason: str | None = None  # stop_hit, target_hit, timeout, eod
    stop_dist_ps: float = 0.0
    slippage_est: float = 0.0
```

### 5. Calculate R-Multiple
```python
def _calculate_r_multiple(entry_price, exit_price, stop_distance, side):
    if side == 'LONG':
        return (exit_price - entry_price) / stop_distance
    else:
        return (entry_price - exit_price) / stop_distance
```

---

## Validation Plan

### Step 1: Unit Test
```python
def test_stop_loss_triggers():
    # Create position with stop
    # Feed bar where low < stop
    # Assert exit order generated
```

### Step 2: Single Trade Test
```python
# Entry: $18.00 LONG
# Stop: $17.90 (1.0 ATR)
# Target: $18.20 (2.0 R)
# Feed bars: $18.00 → $17.85 (should hit stop)
# Assert: Exit at $17.90, exit_reason='stop_hit'
```

### Step 3: Integration Test
```python
# Run full backtest with 10 trades
# Verify mix of stop_hit, target_hit, timeout
# Validate R-multiples calculated correctly
```

---

## Timeline Estimate

### Phase 1: Core Implementation (8 hours)
- Add stop/target to Order class (1 hour)
- Add position monitoring to engine (3 hours)
- Add exit reason tracking (2 hours)
- Add R-multiple calculation (2 hours)

### Phase 2: Testing (4 hours)
- Unit tests (2 hours)
- Integration tests (2 hours)

### Phase 3: Validation (4 hours)
- Single trade manual verification (1 hour)
- Re-run test suite (1 hour)
- Re-run your backtest (2 hours)

**Total: 16 hours to working system**

---

## Immediate Actions

### DO NOT:
- Run more backtests (results invalid)
- Optimize parameters (system broken)
- Trust any previous results (all wrong)

### DO:
1. Acknowledge system is broken
2. Decide: Fix it or use different system
3. If fixing: Allocate 16 hours development time
4. If not fixing: Find alternative backtest engine

---

## Alternative: Use Existing Solution

### Option A: Backtrader
- Mature backtest engine
- Built-in stop/target support
- Position monitoring included
- 2-4 hours to integrate

### Option B: Zipline
- Quantopian's engine
- Full risk management
- Well documented
- 4-8 hours to integrate

### Option C: VectorBT
- Fast vectorized backtesting
- Stop/target support
- Good for parameter sweeps
- 2-4 hours to integrate

---

## Bottom Line

**Your system does not implement basic trading logic:**
- ❌ No stop loss monitoring
- ❌ No take profit monitoring
- ❌ No position risk management
- ❌ No exit reason tracking
- ❌ No R-multiple calculation

**All results to date are invalid.**

**Decision required:**
1. Invest 16 hours to fix current system, OR
2. Invest 4-8 hours to integrate proven solution

**Cannot proceed with strategy optimization until this is resolved.**

---

**Status:** Awaiting decision on path forward  
**Blocker:** Core trading logic not implemented  
**Risk:** High - system cannot be used for live trading
