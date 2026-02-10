# Sprint Plan: Fix Order Auto-Cancel Bug

**Date**: 2026-01-29  
**Priority**: CRITICAL  
**Impact**: Positions not closing at EOD, overnight risk exposure

## Problem Summary

Positions accumulated throughout the day (T: 630 shares SHORT, SBUX: 126 shares SHORT) and failed to close because:
1. OCA (stop/target) orders were being auto-cancelled by the system
2. EOD market orders were also being cancelled
3. System entered a cancel-retry loop that prevented any exits

## Root Cause Hypothesis

**User's Theory**: Exit orders are being recalculated and replaced when fill price differs from expected entry price, causing cancellations.

**Current Flow** (BROKEN):
1. Calculate expected entry price (ask/bid)
2. Place entry order with stop/target based on expected price
3. On fill: Recalculate stop/target based on actual fill price
4. Cancel old OCA orders and place new ones
5. Max hold timer triggers → cancels OCA orders again
6. Infinite cancel loop

**Desired Flow** (USER REQUEST):
1. Calculate expected entry price
2. Place MARKET entry order (no stop/target yet)
3. On fill: Calculate stop/target based on ACTUAL fill price
4. Place stop/target orders
5. All orders as MARKET type

## Investigation Tasks

### Task 1: Trace Exit Order Lifecycle
**File**: `l2_scalping/src/main.py`

- [ ] Find all locations where OCA orders are placed
  - Search for `place_oca_exit_orders`
  - Document line numbers and conditions
  
- [ ] Find all locations where OCA orders are cancelled
  - Search for `cancel_order` with OCA context
  - Document triggers: max hold, recalculation, force exit
  
- [ ] Trace `exit_price_source` config usage
  - Find where it's read from config
  - Document "fill" vs "signal" behavior
  - Current setting: likely "fill"

### Task 2: Analyze Exit Price Source Logic
**File**: `l2_scalping/src/main.py` lines ~940-1000

- [ ] Read entry fill handler code
  - Check if OCA orders placed immediately on entry
  - Check if they're based on expected vs actual price
  
- [ ] Check for OCA order replacement logic
  - Look for code that cancels and replaces OCA orders
  - Verify if this happens on every fill update
  
- [ ] Document current behavior:
  ```
  exit_price_source = "fill":
    - When are OCA orders first placed?
    - Are they recalculated after fill?
    - What triggers replacement?
  ```

### Task 3: Review Max Hold Time Logic
**File**: `l2_scalping/src/main.py` lines 1145-1180

- [ ] Current behavior (ALREADY IDENTIFIED):
  ```python
  if hold_time >= max_hold:
      # Cancels ALL exit orders including working OCA orders
      for exit_id in position.get("exit_order_ids", []):
          self.order_manager.cancel_order(exit_id)
      # Places new market order
  ```

- [ ] Verify max_hold_seconds config value
  - Check `config/strategy.yaml`
  - Current: 600 seconds (10 minutes)
  
- [ ] Check why positions held for 23,000+ seconds
  - Were they accumulating from multiple entries?
  - Was max hold check not running?

### Task 4: Check Config Settings
**Files**: `l2_scalping/config/*.yaml`

- [ ] Read `ibkr.yaml`:
  - `entry_order_type`: Should be "MKT"
  - `exit_price_source`: Check current value
  
- [ ] Read `strategy.yaml`:
  - `max_hold_seconds`: Current value
  - `default_hold_seconds`: Current value
  
- [ ] Document bracket order settings:
  - Are bracket orders enabled?
  - Are they using fill price or signal price?

## Implementation Tasks

### Task 5: Implement User's Desired Flow
**Goal**: All market orders, stop/target calculated from actual fill

- [ ] Modify entry order placement:
  ```python
  # Remove stop_loss_price and profit_target_price from entry OrderRequest
  order_request = OrderRequest(
      symbol=symbol,
      side=side,
      quantity=quantity,
      price=None,  # Market order
      order_type=OrderType.MKT,
      time_in_force=None,
      # NO stop_loss_price or profit_target_price here
  )
  ```

- [ ] Modify fill handler to place OCA orders AFTER fill:
  ```python
  # On entry fill:
  if fill_event and not position.get("exit_order_ids"):
      # Calculate stop/target from ACTUAL fill price
      stop_loss_price = calculate_stop(fill_price, side)
      profit_target_price = calculate_target(fill_price, side)
      
      # Place OCA orders as MARKET orders (not limit/stop)
      # Or keep as limit/stop but DON'T recalculate
      exit_ids = place_oca_exit_orders(...)
      position["exit_order_ids"] = exit_ids
      position["exit_order_time"] = time.time()
  ```

- [ ] Remove OCA order recalculation logic:
  - Find any code that replaces OCA orders
  - Remove or disable it
  - OCA orders should be "set and forget"

### Task 6: Fix Max Hold Time Logic
**Goal**: Don't cancel working OCA orders

- [ ] Implement grace period for OCA orders:
  ```python
  if hold_time >= max_hold:
      if position.get("exit_order_ids"):
          exit_order_age = current_time - position.get("exit_order_time", entry_time)
          if exit_order_age < 60:  # 60 second grace period
              logger.info(f"Max hold exceeded but exit orders working")
              continue  # Don't cancel
          else:
              logger.warning(f"Exit orders stale, forcing market exit")
              force_exit = True
      else:
          force_exit = True
  ```

- [ ] Fix force exit cancellation logic:
  ```python
  def _exit_position(..., force_market=False):
      if force_market:
          # Only cancel if truly forcing
          for exit_id in position.get("exit_order_ids", []):
              try:
                  self.order_manager.cancel_order(exit_id)
              except Exception as e:
                  logger.debug(f"Cancel failed: {e}")
      elif position.get("exit_order_id"):
          # Exit order exists, don't duplicate
          return
  ```

### Task 7: Fix EOD Flatten Logic
**Goal**: Ensure EOD closes positions before market close

- [ ] Check EOD flatten time:
  - Current: 15:55 ET
  - Market close: 16:00 ET
  - 5 minute window should be enough
  
- [ ] Verify EOD uses market orders:
  ```python
  def _close_all_positions():
      for symbol in active_positions:
          # Should use force_market=True
          self._exit_position(symbol, price, "System shutdown", force_market=True)
  ```

- [ ] Add retry logic for EOD:
  ```python
  # If market order fails, retry with limit order
  # If still fails after 3 attempts, log critical error
  ```

- [ ] Prevent after-hours market orders:
  ```python
  if current_time > market_close:
      # Use limit orders or marketable limit orders
      # Don't use pure market orders (IBKR rejects)
  ```

## Testing Tasks

### Task 8: Unit Tests

- [ ] Test OCA order placement on fill:
  - Mock entry fill
  - Verify OCA orders placed with correct prices
  - Verify no recalculation happens

- [ ] Test max hold with working OCA orders:
  - Mock position with exit_order_ids
  - Trigger max hold
  - Verify OCA orders NOT cancelled within grace period

- [ ] Test force exit:
  - Mock stale OCA orders (>60s)
  - Trigger max hold
  - Verify OCA orders cancelled and market order placed

### Task 9: Integration Tests

- [ ] Test full entry-to-exit flow:
  1. Place market entry
  2. Receive fill
  3. OCA orders placed
  4. Stop or target hit
  5. Position closed
  
- [ ] Test EOD flatten:
  1. Create open position at 15:54 ET
  2. Trigger EOD flatten at 15:55 ET
  3. Verify position closed before 16:00 ET

### Task 10: Production Validation

- [ ] Deploy to paper trading
- [ ] Monitor for 1 full trading day
- [ ] Check logs for:
  - OCA order cancellations (should be ZERO unless stale)
  - Force exit triggers (should be rare)
  - EOD flatten success (should be 100%)
  
- [ ] Verify no overnight positions

## Configuration Changes

### Task 11: Update Config Files

- [ ] `l2_scalping/config/ibkr.yaml`:
  ```yaml
  orders:
    entry_order_type: "MKT"  # Already set
    exit_price_source: "fill"  # Use actual fill price
    # Remove or ignore ioc_price_improvement_ticks for market orders
  ```

- [ ] `l2_scalping/config/strategy.yaml`:
  ```yaml
  strategy:
    max_hold_seconds: 3600  # Increase to 1 hour (or remove entirely)
    # Let OCA orders do their job, don't force exit prematurely
  ```

## Rollback Plan

- [ ] Save current `main.py` as `main.py.backup-2026-01-29`
- [ ] Document all changes in git commit
- [ ] If issues occur:
  1. `git revert <commit>`
  2. Restart l2-scalping service
  3. Review logs and adjust

## Success Criteria

1. ✅ No OCA order auto-cancellations (except stale orders >60s)
2. ✅ All positions close via stop/target or EOD flatten
3. ✅ Zero overnight positions
4. ✅ No cancel-retry loops in logs
5. ✅ EOD flatten completes before 16:00 ET market close

## Files to Modify

1. `/home/jacobw/quantstack/l2_scalping/src/main.py`
   - Entry order placement (~line 650)
   - Fill handler (~line 955)
   - Max hold logic (~line 1145)
   - Exit position method (~line 1200)
   
2. `/home/jacobw/quantstack/l2_scalping/config/strategy.yaml`
   - Increase max_hold_seconds
   
3. `/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml`
   - Verify exit_price_source setting

## Estimated Time

- Investigation: 1-2 hours
- Implementation: 2-3 hours
- Testing: 1-2 hours
- Production validation: 1 trading day

**Total**: ~1 day

## Notes

- Current open positions (T: 630 SHORT, SBUX: 126 SHORT) need manual closure at market open
- This is a CRITICAL bug affecting risk management
- Priority: Fix before next trading session
