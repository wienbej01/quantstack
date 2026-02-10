# Overnight Position Safeguards

## Problem Statement

The L2-scalping system had residual open positions remaining overnight due to:
1. No bracket orders - exits relied solely on polling loop
2. No entry curfew - could open trades too close to market close
3. System crashes/stops left positions unprotected
4. No forced exit mechanism for max duration violations

## Solution Overview

Implemented **5 layers of protection** to ensure no positions remain open overnight:

### 1. Bracket Orders at Entry ✅
- **What**: Automatic stop-loss and profit-target orders attached to every entry
- **How**: Parent-child order relationship via IBKR
- **Protection**: Orders remain active even if system crashes
- **Implementation**: 
  - Stop-loss: 10 bps from entry (from risk.yaml)
  - Profit target: 15 bps from entry (from risk.yaml)
  - Applied to both OBI momentum and pattern rule signals

### 2. Entry Curfew ✅
- **What**: Block new entries if insufficient time before market close
- **How**: Check `current_time + max_hold_seconds + 60s buffer < market_close`
- **Protection**: Prevents opening positions that can't be closed before 16:00 ET
- **Example**: With 600s (10 min) max hold, blocks entries after 15:49 ET

### 3. Force Exit at Max Duration ✅
- **What**: Market order exit when max_hold_seconds exceeded
- **How**: Priority check in `_check_position_exits()` with `force_market=True`
- **Protection**: Ensures immediate exit regardless of price
- **Timing**: 600s (10 min) max hold from entry

### 4. Polling Loop Backup ✅
- **What**: Continuous monitoring every 10ms for exit conditions
- **How**: Checks scheduled_exit, profit_target, stop_loss
- **Protection**: Redundant layer if bracket orders fail
- **Priority**: max_hold (force) > scheduled_exit > profit_target > stop_loss

### 5. Emergency EOD Close ✅
- **What**: Systemd timer force-closes all positions at 15:55 ET
- **How**: `emergency-eod-close.timer` runs `emergency_eod_close.py`
- **Protection**: Final safety net before market close
- **Location**: `/home/jacobw/quantstack/scripts/emergency_eod_close.py`

## Implementation Details

### Modified Files

1. **order_manager.py**
   - Added `stop_loss_price` and `profit_target_price` to `OrderRequest`
   - Implemented `_place_bracket_order()` method
   - Parent order with child stop-loss and profit-target orders

2. **scheduler.py**
   - Added `can_open_new_position(max_hold_seconds)` method
   - Returns `(can_open, reason)` tuple
   - Checks time remaining until market close

3. **main.py**
   - Added entry curfew check to `_execute_signal()` and `_execute_pattern_signal()`
   - Calculate bracket prices from risk config
   - Enhanced `_check_position_exits()` with force exit priority
   - Added `force_market` parameter to `_exit_position()`

### Configuration

**strategy.yaml**:
```yaml
default_hold_seconds: 300  # 5-minute scheduled exit
max_hold_seconds: 600      # 10-minute force exit
```

**risk.yaml**:
```yaml
per_trade:
  max_loss_bps: 10         # Stop-loss at 10 bps
  profit_target_bps: 15    # Profit target at 15 bps
```

## Exit Priority Logic

```
1. MAX_HOLD_EXCEEDED (force market order) - CRITICAL
2. Scheduled exit (default 5 min)
3. Profit target (15 bps)
4. Stop loss (10 bps)
```

## Testing Checklist

- [ ] Verify bracket orders placed with every entry
- [ ] Confirm entry curfew blocks trades after 15:49 ET (with 600s max hold)
- [ ] Test force exit triggers at max_hold_seconds
- [ ] Verify market order used for force exits
- [ ] Check emergency EOD close timer at 15:55 ET
- [ ] Simulate system crash - bracket orders should remain active
- [ ] Verify trade IDs tracked correctly from entry to exit

## Trade ID Verification

Trade IDs are correctly tracked throughout the lifecycle:
1. `signal_id` generated in `_build_signal_id()`
2. Passed through `pending_entries` dict
3. Stored in `active_positions` with `trade_id` from journal
4. Properly linked in `trade_journal.record_trade_entry/exit`

**No changes needed** - existing implementation is correct.

## Market Hours Reference

- **Market Open**: 9:30 AM ET
- **Market Close**: 4:00 PM ET
- **Emergency EOD Close**: 3:55 PM ET (15:55)
- **Entry Curfew** (600s max hold): 3:49 PM ET (15:49)

## Monitoring

Check logs for:
- `"Entry blocked by curfew"` - Entry curfew working
- `"FORCE EXIT"` - Max hold time exceeded
- `"Bracket order placed"` - Bracket orders active
- `"Exit order placed (MARKET)"` - Force market order used

## Notes

- IBKR does not support time-based conditional orders directly
- Bracket orders use parent-child relationship (standard IBKR feature)
- Entry curfew calculated dynamically based on current time and market close
- Force exit uses market orders for guaranteed execution
- All protection layers work independently for redundancy
