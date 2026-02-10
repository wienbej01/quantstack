# Price Improvement Buffer Implementation
**Date**: 2026-01-23  
**Purpose**: Fix 0% fill rate on L2 scalping IOC orders

---

## Changes Made

### 1. Configuration (`l2_scalping/config/ibkr.yaml`)

**Added**:
```yaml
orders:
  use_ioc_for_scalping: true
  ioc_price_improvement_ticks: 1  # NEW: Add 1 tick for better fills
  tick_size: 0.01                 # NEW: Default tick size
```

**Purpose**: 
- `ioc_price_improvement_ticks`: Number of ticks to add/subtract from bid/ask
- `tick_size`: Size of one tick (typically $0.01 for most stocks)
- Set to 1 tick = $0.01 improvement per order

### 2. Entry Logic (`l2_scalping/src/main.py`)

**Modified Two Locations**:

#### Location 1: Primary Entry Logic (lines ~525-545)
```python
# Get price improvement settings for IOC orders
use_ioc = self.config["ibkr"]["orders"]["use_ioc_for_scalping"]
improvement_ticks = self.config["ibkr"]["orders"].get("ioc_price_improvement_ticks", 0)
tick_size = self.config["ibkr"]["orders"].get("tick_size", 0.01)
price_improvement = improvement_ticks * tick_size if use_ioc else 0.0

# Determine order side and price
if signal.signal_type.value > 0:  # Long
    side = OrderSide.BUY
    limit_price = snapshot.ask + price_improvement  # CHANGED: Added improvement
else:  # Short
    side = OrderSide.SELL
    limit_price = snapshot.bid - price_improvement  # CHANGED: Added improvement

# Log price improvement if applied
if price_improvement > 0:
    logger.debug(f"IOC price improvement: {price_improvement:.4f} ({improvement_ticks} ticks)")
```

#### Location 2: Rule-Based Entry Logic (lines ~665-690)
Same changes applied to second entry path (for rule-based signals).

#### Location 3: Order Logging (lines ~600)
```python
improvement_str = f" +{price_improvement:.4f}" if price_improvement > 0 else ""
logger.info(
    f"TRADE [{rule_name.value}]: {signal.symbol} {side.value} {quantity}@{limit_price:.4f}{improvement_str} "
    f"[stop={stop_loss_price:.4f}, target={profit_target_price:.4f}]"
)
```

**Purpose**: Show price improvement in logs for monitoring

---

## How It Works

### Before (0% Fill Rate)
```
Signal: BUY INTC
Ask: $55.00
Order: BUY @ $55.00 IOC
Result: Cancelled (ask moved or no liquidity)
```

### After (Expected 20-30% Fill Rate)
```
Signal: BUY INTC
Ask: $55.00
Improvement: +$0.01 (1 tick)
Order: BUY @ $55.01 IOC
Result: Filled (willing to pay above ask)
```

### For SELL Orders
```
Signal: SELL INTC
Bid: $54.00
Improvement: -$0.01 (1 tick)
Order: SELL @ $53.99 IOC
Result: Filled (willing to accept below bid)
```

---

## Expected Impact

### Fill Rate
- **Before**: 0% (0 fills out of 3,150 orders)
- **After**: 20-30% (600-900 fills out of 3,000 orders)

### Execution Cost
- **Per Fill**: $0.01 (1 tick)
- **Per 100 shares**: $1.00
- **Per 18 shares** (typical size): $0.18

### Trade-off Analysis
```
Before: 0 fills × $0 cost = $0 total cost, but NO TRADING
After:  600 fills × $0.18 cost = $108 total cost, but ACTUAL TRADING
```

**Net Effect**: Pay $108/day to actually execute trades vs. $0/day with no executions.

---

## Configuration Options

### Conservative (Current)
```yaml
ioc_price_improvement_ticks: 1  # 1 tick = $0.01
```
- Lower cost per fill
- Moderate fill rate (20-30%)

### Aggressive
```yaml
ioc_price_improvement_ticks: 2  # 2 ticks = $0.02
```
- Higher cost per fill
- Higher fill rate (40-60%)

### Disabled
```yaml
ioc_price_improvement_ticks: 0  # No improvement
```
- Back to 0% fill rate
- Not recommended

### Dynamic (Future Enhancement)
```python
# Adjust improvement based on spread
if spread < 0.02:  # Tight spread
    improvement_ticks = 1
else:  # Wide spread
    improvement_ticks = 2
```

---

## Monitoring

### Key Metrics to Track

1. **Fill Rate**
```bash
# Count orders placed vs filled
grep "TRADE \[" logs/scalping_system.log | wc -l  # Orders placed
grep "record_trade_entry" logs/scalping_system.log | wc -l  # Orders filled
```

2. **Execution Cost**
```bash
# Check price improvement in logs
grep "IOC price improvement" logs/scalping_system.log
```

3. **Database Records**
```sql
-- Check L2 scalping trades
SELECT COUNT(*), AVG(net_pnl) 
FROM trades 
WHERE system = 'l2-scalping' 
AND entry_time::date = CURRENT_DATE;
```

### Expected Log Output

**Order Placement**:
```
TRADE [bid_depth_obi]: INTC BUY 18@55.0100 +0.0100 [stop=54.9545, target=55.0925]
```

**Fill Detection**:
```
L2 Trade entry [bid_depth_obi]: INTC BUY 18@55.0100
Trade opened in shared store: abc123-def456
```

---

## Testing Plan

### Phase 1: Monitor First Session
- Run with `ioc_price_improvement_ticks: 1`
- Track fill rate throughout day
- Compare to previous 0% baseline

### Phase 2: Analyze Results
- Calculate actual fill rate
- Measure execution cost per fill
- Assess impact on P&L

### Phase 3: Optimize
- If fill rate < 20%: Increase to 2 ticks
- If fill rate > 50%: Consider reducing to 0.5 ticks (if supported)
- If execution cost too high: Reduce improvement or disable IOC

---

## Rollback Plan

If price improvement causes issues:

### Option 1: Disable Improvement
```yaml
ioc_price_improvement_ticks: 0
```

### Option 2: Disable IOC Entirely
```yaml
use_ioc_for_scalping: false
```
Orders will use DAY limit orders instead.

### Option 3: Revert Code
```bash
cd /home/jacobw/quantstack/l2_scalping
git diff src/main.py config/ibkr.yaml
git checkout src/main.py config/ibkr.yaml  # If needed
```

---

## Files Modified

1. `/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml`
   - Added `ioc_price_improvement_ticks: 1`
   - Added `tick_size: 0.01`

2. `/home/jacobw/quantstack/l2_scalping/src/main.py`
   - Added price improvement calculation (2 locations)
   - Added improvement to limit_price (BUY: +improvement, SELL: -improvement)
   - Added logging for price improvement

---

## Next Steps

1. **Test in next trading session** (Monday 2026-01-26)
2. **Monitor fill rates** throughout the day
3. **Check database** for actual trade records
4. **Analyze execution costs** vs. P&L
5. **Adjust improvement** based on results

---

## Success Criteria

### Minimum Success
- Fill rate > 10% (vs. 0% baseline)
- At least 1 trade recorded in database
- System runs without errors

### Target Success
- Fill rate 20-30%
- 600-900 fills per day
- Positive net P&L after execution costs

### Optimal Success
- Fill rate 30-50%
- Execution cost < 0.5 bps of trade value
- Consistent profitability

---

**Status**: ✅ Implementation complete  
**Ready for**: Next trading session  
**Risk**: Low (can disable with config change)
