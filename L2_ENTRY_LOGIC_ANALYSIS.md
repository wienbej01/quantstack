# L2 Scalping Entry Logic Analysis
**Date**: 2026-01-23  
**Focus**: IOC order type and pricing strategy

---

## Entry Logic Flow

### 1. Signal Generation
```python
# Signal generated from L2 order book analysis
signal = {
    "symbol": "INTC",
    "signal_type": BUY or SELL,
    "strength": 0.0 - 1.0,
    "confidence": 0.0 - 1.0,
}
```

### 2. Order Pricing Logic

**Code** (`l2_scalping/src/main.py:530-540`):
```python
if signal.signal_type.value > 0:  # Long
    side = OrderSide.BUY
    limit_price = snapshot.ask  # Buy at ask
    stop_loss_price = limit_price * (1 - max_loss_bps / 10000)
    profit_target_price = limit_price * (1 + profit_target_bps / 10000)
else:  # Short
    side = OrderSide.SELL
    limit_price = snapshot.bid  # Sell at bid
    stop_loss_price = limit_price * (1 + max_loss_bps / 10000)
    profit_target_price = limit_price * (1 - profit_target_bps / 10000)
```

**Key Point**: 
- **BUY orders**: Priced at ASK (trying to buy at the offer)
- **SELL orders**: Priced at BID (trying to sell at the bid)

### 3. Order Type Configuration

**Config** (`l2_scalping/config/ibkr.yaml:18`):
```yaml
orders:
  use_ioc_for_scalping: true    # IOC enabled
```

**Code** (`l2_scalping/src/main.py:572-580`):
```python
order_type=(
    OrderType.IOC
    if self.config["ibkr"]["orders"]["use_ioc_for_scalping"]
    else OrderType.LIMIT
),
time_in_force=(
    "IOC"
    if self.config["ibkr"]["orders"]["use_ioc_for_scalping"]
    else "DAY"
),
```

**Result**: All entry orders are **IOC (Immediate-Or-Cancel) limit orders**

---

## The Problem: Why IOC Orders Don't Fill

### IOC Order Behavior
**IOC = Immediate-Or-Cancel**:
- Order sent to exchange
- If **immediately** fillable at limit price → fills
- If **not** immediately fillable → **cancelled instantly**
- No waiting, no resting on book

### Pricing Strategy Issue

**Current Strategy**:
```
BUY:  limit_price = snapshot.ask  (trying to buy at the offer)
SELL: limit_price = snapshot.bid  (trying to sell at the bid)
```

**Why This Fails with IOC**:

#### For BUY Orders (Buy at Ask)
1. Signal says "BUY INTC"
2. Current ask = $55.00
3. Place IOC limit order: BUY @ $55.00
4. **Problem**: By the time order reaches exchange:
   - Ask might have moved to $55.01
   - Or no size available at $55.00
   - Or someone else took the liquidity
5. **Result**: Order cancelled (not fillable)

#### For SELL Orders (Sell at Bid)
1. Signal says "SELL INTC"  
2. Current bid = $54.00
3. Place IOC limit order: SELL @ $54.00
4. **Problem**: By the time order reaches exchange:
   - Bid might have moved to $53.99
   - Or no size available at $54.00
   - Or someone else hit the bid
5. **Result**: Order cancelled (not fillable)

### Real Example from Jan 22

**09:29:02 - BUY Signal**:
```
TRADE [bid_depth_obi]: INTC BUY 18@55.0000 [stop=54.9450, target=55.0825]
```

**What Happened**:
- Tried to buy at ask ($55.00)
- IOC order sent
- By the time it reached exchange, ask was gone or moved
- Order cancelled immediately
- **Repeated 6 times in 7 seconds** (all cancelled)

**09:30:01 - SELL Signal**:
```
TRADE [bid_depth_obi]: INTC SELL 18@51.4900 [stop=51.5415, target=51.4128]
```

**What Happened**:
- Tried to sell at bid ($51.49)
- IOC order sent
- By the time it reached exchange, bid was gone or moved
- Order cancelled immediately

---

## Why This Strategy Exists

### Intended Use Case
IOC orders at bid/ask are designed for:
1. **Ultra-low latency** (microseconds to exchange)
2. **Co-located servers** (next to exchange)
3. **Direct market access** (no broker routing)
4. **High-frequency trading** (thousands of orders/second)

### Current Reality
- **Latency**: ~50-200ms (IBKR Gateway → exchange)
- **Location**: Residential internet
- **Access**: Retail broker (IBKR)
- **Frequency**: ~1 order/second

**Mismatch**: Strategy designed for HFT infrastructure, running on retail setup.

---

## Evidence: 3,150 Orders, 0 Fills

### Statistics
- **Total orders placed**: 3,150
- **Orders filled**: 0
- **Fill rate**: 0.00%
- **Order status**: All cancelled
- **Duration**: 7.5 hours (09:26 - 17:01 ET)

### Sample from Logs (EOD cancellations)
```
orderStatus=OrderStatus(orderId=16212, status='Cancelled', filled=0.0, ...)
orderStatus=OrderStatus(orderId=16216, status='Cancelled', filled=0.0, ...)
orderStatus=OrderStatus(orderId=16220, status='Cancelled', filled=0.0, ...)
orderStatus=OrderStatus(orderId=16224, status='Cancelled', filled=0.0, ...)
```

Every single order: `filled=0.0`, `status='Cancelled'`

---

## Alternative Strategies

### Option 1: Add Price Improvement Buffer
**Current**:
```python
limit_price = snapshot.ask  # BUY
limit_price = snapshot.bid  # SELL
```

**Improved**:
```python
# BUY: Pay 1-2 ticks above ask to ensure fill
limit_price = snapshot.ask + (tick_size * improvement_ticks)  # e.g., +$0.01

# SELL: Accept 1-2 ticks below bid to ensure fill
limit_price = snapshot.bid - (tick_size * improvement_ticks)  # e.g., -$0.01
```

**Trade-off**:
- ✅ Higher fill rate
- ❌ Worse execution price (pay spread + buffer)
- ❌ Reduces edge

### Option 2: Use Market Orders
**Change**:
```python
order_type = OrderType.MKT  # Market order
```

**Trade-off**:
- ✅ 100% fill rate
- ❌ Unpredictable execution price
- ❌ Slippage risk
- ❌ No control over price

### Option 3: Use Short-Duration Limit Orders
**Change**:
```python
order_type = OrderType.LIMIT
time_in_force = "GTT"  # Good-Till-Time
duration = 1  # 1 second
```

**Trade-off**:
- ✅ Rests on book briefly
- ✅ Can get filled if price comes back
- ❌ Still might not fill
- ❌ More complex order management

### Option 4: Use Marketable Limit Orders
**Change**:
```python
# BUY: Limit at bid (marketable - crosses spread)
limit_price = snapshot.bid

# SELL: Limit at ask (marketable - crosses spread)
limit_price = snapshot.ask
```

**Trade-off**:
- ✅ Higher fill rate (marketable)
- ✅ Price protection (limit order)
- ❌ Pays the spread
- ❌ Might still not fill if book is thin

### Option 5: Disable IOC, Use DAY Limit Orders
**Change**:
```yaml
# ibkr.yaml
use_ioc_for_scalping: false  # Disable IOC
```

**Result**:
```python
order_type = OrderType.LIMIT
time_in_force = "DAY"
```

**Trade-off**:
- ✅ Order rests on book
- ✅ Can get filled when price reaches limit
- ❌ Might not fill for hours
- ❌ Requires active order management
- ❌ Risk of stale orders

---

## Recommended Fix

### Immediate: Test with Price Improvement

**Step 1**: Add configuration
```yaml
# ibkr.yaml
orders:
  use_ioc_for_scalping: true
  ioc_price_improvement_ticks: 1  # Add 1 tick for IOC orders
```

**Step 2**: Modify pricing logic
```python
# Calculate tick size (e.g., $0.01 for most stocks)
tick_size = 0.01
improvement = self.config["ibkr"]["orders"].get("ioc_price_improvement_ticks", 0) * tick_size

if signal.signal_type.value > 0:  # Long
    side = OrderSide.BUY
    limit_price = snapshot.ask + improvement  # Pay above ask
else:  # Short
    side = OrderSide.SELL
    limit_price = snapshot.bid - improvement  # Accept below bid
```

**Expected Result**:
- Fill rate: 10-30% (vs 0%)
- Execution cost: +1 tick ($0.01) per fill
- Trade-off: Pay for fills, but actually get executions

### Long-term: Rethink Strategy

**Questions to Answer**:
1. Is IOC necessary for this strategy?
2. What fill rate is acceptable? (50%? 80%?)
3. What execution cost is acceptable? (1 tick? 2 ticks?)
4. Should we use different order types for different signals?

**Alternative Approach**:
- Use IOC only for highest-confidence signals
- Use short-duration limits for medium-confidence
- Skip low-confidence signals entirely

---

## Configuration Analysis

### Current Config (`ibkr.yaml`)
```yaml
orders:
  default_order_type: "LMT"     # Limit orders
  default_tif: "DAY"            # Time in force
  use_ioc_for_scalping: true    # ← THIS IS THE ISSUE
  order_ref_prefix: "L2SCALP"
```

**Problem**: `use_ioc_for_scalping: true` combined with pricing at bid/ask = 0% fill rate

### Pricing Logic (`main.py:530-540`)
```python
limit_price = snapshot.ask  # BUY at ask
limit_price = snapshot.bid  # SELL at bid
```

**Problem**: No buffer for latency or market movement

### Combined Effect
```
IOC order + exact bid/ask pricing + retail latency = 0% fills
```

---

## Testing Plan

### Test 1: Disable IOC (Quick Test)
```yaml
# ibkr.yaml
use_ioc_for_scalping: false
```

**Expected**: Orders rest on book, some fills when price reaches limit  
**Risk**: Stale orders, need better order management

### Test 2: Add Price Improvement (Recommended)
```yaml
# ibkr.yaml
use_ioc_for_scalping: true
ioc_price_improvement_ticks: 1  # Start with 1 tick
```

**Expected**: 10-30% fill rate  
**Cost**: $0.01 per fill (1 tick)

### Test 3: Hybrid Approach
```python
# Use IOC with improvement for high-confidence signals
if signal.confidence > 0.8:
    order_type = OrderType.IOC
    improvement = 1 * tick_size
else:
    order_type = OrderType.LIMIT
    time_in_force = "GTT"
    duration = 2  # 2 seconds
```

**Expected**: Better fill rate on best signals, patient on others

---

## Conclusion

### Root Cause
**IOC orders at exact bid/ask prices don't fill** because:
1. Market moves between signal and execution
2. Liquidity disappears before order arrives
3. No buffer for latency (50-200ms)
4. Retail infrastructure can't compete with HFT

### The Fix
**Add price improvement buffer**:
- BUY: Pay 1-2 ticks above ask
- SELL: Accept 1-2 ticks below bid
- Trade execution cost for fill rate

### The Trade-off
```
Current:  0% fills, $0 cost per fill, infinite cost per trade (never trades)
Improved: 20% fills, $0.01 cost per fill, $0.01 cost per trade
```

**Recommendation**: Implement price improvement buffer and test with 1 tick ($0.01) improvement.

---

**Files to Modify**:
1. `/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml` - Add `ioc_price_improvement_ticks`
2. `/home/jacobw/quantstack/l2_scalping/src/main.py` - Add improvement to limit_price calculation
3. Add logging to track fill rates and execution costs
