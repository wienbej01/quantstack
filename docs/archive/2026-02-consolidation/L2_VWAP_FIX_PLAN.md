# L2-VWAP-Reversion Fix Plan

**Date**: 2026-02-03  
**Status**: PENDING  
**Priority**: HIGH - System generating signals but failing to execute

## Issues Identified

### Issue 1: Missing `self.ib` attribute

**Error**: `'VWAPReversionSystem' object has no attribute 'ib'`

**Location**: `/home/jacobw/quantstack/l2_vwap_reversion/src/main.py` line 216

**Root Cause**: 
```python
for p in self.ib.positions():  # self.ib doesn't exist
```

**Fix**:
```python
for p in self.order_session.ib.positions():  # Use order_session.ib
```

---

### Issue 2: Event loop conflict in order submission

**Error**: `This event loop is already running`

**Location**: `/home/jacobw/quantstack/l2_vwap_reversion/src/execution/order_manager.py`

**Root Cause**: 
The `session.call()` method uses `asyncio.run_coroutine_threadsafe()` which works correctly.
However, the error suggests the call is being made from within an async context.

The bar callback `_on_bar()` is likely being called from within the ib_insync event loop,
and then trying to run another coroutine on the same loop.

**Fix Options**:
1. Use `nest_asyncio` to allow nested event loops
2. Use `call_soon_threadsafe` instead of `call` for order submission
3. Queue orders and process them in a separate thread

**Recommended Fix**: Add `nest_asyncio.apply()` at module start

---

## Files to Modify

1. `/home/jacobw/quantstack/l2_vwap_reversion/src/main.py`
   - Line 216: Change `self.ib` to `self.order_session.ib`
   - Add `import nest_asyncio; nest_asyncio.apply()` at top

## Testing

1. Apply fixes
2. Restart l2-vwap-reversion service
3. Watch for signal → order submission
4. Verify orders appear in IBKR
