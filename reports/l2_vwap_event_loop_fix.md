# L2 VWAP Trading Bug Fix - Event Loop Error

**Date:** 2026-01-31  
**Issue:** L2 VWAP generating signals but failing to execute trades  
**Root Cause:** Asyncio event loop conflict in order submission

## Problem

L2 VWAP service was generating valid trading signals but failing to execute orders with error:

```
[INFO] strategy: LONG signal: FCX @ 60.75, VWAP=61.08, L2=1.17157823927636
[ERROR] execution.order_manager: Failed to submit bracket order for FCX: This event loop is already running
```

This error occurred on **every signal** since the service restart at 23:41 PST on Jan 30.

## Root Cause Analysis

The `OrderManager.submit_bracket_order()` method was using `session.call()` to wrap `ib.placeOrder()` calls:

```python
# BROKEN CODE
parent_trade = self.session.call(
    self.session.ib.placeOrder, contract, parent, timeout=10
)
```

The `session.call()` method wraps functions in an async coroutine using `asyncio.run_coroutine_threadsafe()`. However, `ib.placeOrder()` from ib_insync is **already synchronous** when called from within a running event loop. Wrapping it again caused the "event loop is already running" error.

### Why L2 Scalping Worked

L2 scalping uses `qx_broker.ibkr.IBKROrderManager`, which also uses `session.call()` but was working. Investigation needed to determine if:
1. Different event loop context
2. Different ib_insync version behavior
3. L2 VWAP specific configuration issue

## Solution

Changed all `session.call()` wrapped IB API calls to direct calls:

```python
# FIXED CODE
parent_trade = self.session.ib.placeOrder(contract, parent)
```

### Files Modified

**`/home/jacobw/quantstack/l2_vwap_reversion/src/execution/order_manager.py`**

Changed 5 locations:
1. Line 120: `qualifyContracts()` in `submit_bracket_order()`
2. Line 136: `placeOrder()` for parent order
3. Line 154: `placeOrder()` for stop-loss order
4. Line 168: `placeOrder()` for take-profit order
5. Line 207: `qualifyContracts()` in `submit_market_order()`
6. Line 214: `placeOrder()` in `submit_market_order()`

## Testing

- Service restarted successfully at 00:10:08 PST on Jan 31
- No errors in startup logs
- Waiting for market open to verify signal execution

## Impact

**Before Fix:**
- 0 trades executed despite multiple valid signals
- Signals generated every 1-2 minutes for FCX (23:55-00:06)
- All signals failed with event loop error

**After Fix:**
- Service running cleanly
- Ready to execute on next signal

## Follow-up Actions

1. **Monitor Monday market open** - Verify L2 VWAP executes trades successfully
2. **Review qx-broker** - Investigate why `IBKROrderManager.place_order()` works with `session.call()` but L2 VWAP's direct usage fails
3. **Standardize order execution** - Consider using `IBKROrderManager` in L2 VWAP instead of custom implementation
4. **Add integration test** - Test order submission in event loop context

## Related Issues

- Position sizing bug (fixed earlier today) - L2 VWAP had 100x inflated positions
- Trade recording (fixed Jan 29) - Separate issue, not related to execution

## Lessons Learned

1. **Event loop context matters** - Wrapping synchronous ib_insync calls in async coroutines causes conflicts
2. **Test in production context** - This bug only manifested when running as a service with ib_insync event loop
3. **Monitor error logs** - The error was clear and actionable, but required log analysis to discover
