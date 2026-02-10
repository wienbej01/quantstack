# Fill Communication Fix Plan

## Problem
IBKR sends fills (confirmed in API log), but `_on_exec_details` event callback not triggered for 80% of orders (4/5 failed on Jan 30).

**Evidence:**
- API log shows fills: HL @24.42, SLV @90.46/90.80, VZ @43.25
- Database shows: Only 1/5 orders has entry_fill_count=1
- Service logs: No "Fill:" messages for failed orders
- Root cause: Event handler timing/registration issue

## Solution: Multi-Layer Fill Detection

### 1. Keep Event Callback (Primary)
**Status:** Already implemented
- Works for ~20% of orders
- Zero latency when it works
- No changes needed

### 2. Add Polling Fallback (Secondary)
**Implementation:** Poll Trade object after order submission
```python
# After placing order, start polling for fills
asyncio.create_task(self._poll_for_fills(order_id, trade_obj, timeout=10))

async def _poll_for_fills(self, order_id, trade_obj, timeout):
    """Poll Trade object for fills if callback doesn't fire."""
    start = time.time()
    last_fill_count = 0
    
    while time.time() - start < timeout:
        await asyncio.sleep(0.5)  # Poll every 500ms
        
        # Check if callback already processed fills
        if order_id in self._fill_accumulator:
            return  # Callback worked, stop polling
        
        # Check Trade object for fills
        if trade_obj.fills and len(trade_obj.fills) > last_fill_count:
            for fill in trade_obj.fills[last_fill_count:]:
                self._process_fill(fill)  # Manually trigger fill processing
            last_fill_count = len(trade_obj.fills)
```

**Why this works:**
- ib_insync maintains Trade.fills list regardless of callbacks
- Polling catches fills that callbacks miss
- Stops polling once callback fires (no duplicate processing)

### 3. Add Fill Reconciliation (Tertiary)
**Implementation:** Periodic check for orders with missing fills
```python
# Run every 30 seconds
async def _reconcile_fills(self):
    """Check for orders that should have fills but don't."""
    for order_id, trade_info in self._active_trades.items():
        # Check if order is filled but we have no fill records
        trade_obj = self._trades.get(order_id)
        if trade_obj and trade_obj.orderStatus.status == "Filled":
            if order_id not in self._fill_accumulator:
                logger.warning(f"Reconciling missing fills for order {order_id}")
                for fill in trade_obj.fills:
                    self._process_fill(fill)
```

### 4. Improve Event Handler Attachment
**Implementation:** Attach handlers BEFORE connecting
```python
# In IBKRLiveAdapter.__init__
if self.session.is_connected():
    self.attach_handlers()  # Attach immediately if already connected

# Ensure handlers attached before any order placement
def place_order(self, ...):
    if not self._events_attached:
        self.attach_handlers()
    # ... rest of order placement
```

## Implementation Priority

### Phase 1: Polling Fallback (Highest Impact)
- File: `intraday_stack/src/execution/ibkr_live_adapter.py`
- Add `_poll_for_fills()` method
- Call after `place_order()` returns Trade object
- Estimated time: 30 minutes
- Expected fix rate: 95%+

### Phase 2: Fill Reconciliation (Safety Net)
- File: `intraday_stack/scripts/paper_trade.py`
- Add periodic reconciliation task
- Run every 30 seconds during market hours
- Estimated time: 20 minutes
- Expected fix rate: 99%+

### Phase 3: Handler Attachment Improvement (Preventive)
- File: `intraday_stack/src/execution/ibkr_live_adapter.py`
- Attach handlers earlier in lifecycle
- Add connection state checks
- Estimated time: 15 minutes
- Expected fix rate: 100%

## Testing Plan

1. **Unit test:** Mock Trade object with fills, verify polling detects them
2. **Integration test:** Place order, disconnect callback, verify polling catches fill
3. **Live test:** Run on paper account, monitor audit logs for fill detection method
4. **Validation:** Check entry_fill_count=1 for all trades in database

## Rollback Plan

If polling causes issues:
1. Add feature flag: `enable_fill_polling = False`
2. Revert to callback-only mode
3. Investigate ib_insync event loop issues

## Success Metrics

- **Before:** 20% fill detection rate (1/5 orders)
- **After Phase 1:** 95%+ fill detection rate
- **After Phase 2:** 99%+ fill detection rate
- **After Phase 3:** 100% fill detection rate

## Alternative: Switch to Synchronous Fill Query

If async polling proves complex, use synchronous approach:
```python
# After order placement
time.sleep(2)  # Wait for fill
trade_obj = self.session.ib.trades()[order_id]
if trade_obj.fills:
    for fill in trade_obj.fills:
        self._on_exec_details(trade_obj, fill)
```

Simpler but adds 2s latency per order.
