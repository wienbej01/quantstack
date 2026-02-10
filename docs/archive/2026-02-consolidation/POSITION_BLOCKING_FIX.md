# Position Blocking Fix - Change Log

**Date**: 2026-02-04 00:05  
**Issue**: Systems blocking trades based on ALL IBKR positions, not just their own

## Problem

All 3 trading systems checked global IBKR positions before opening new trades:
- l2-scalping: Checked `ib.positions()` globally
- l2-vwap-reversion: Checked `ib.positions()` globally  
- intraday-paper: Already correct (checks only own positions)

**Impact**: Systems couldn't trade same symbol in opposite directions
- Example: RMBS LONG in intraday-paper blocked l2-vwap SHORT signal

## Solution

Changed position blocking to only check each system's own tracked positions.

### Files Modified

**1. `/home/jacobw/quantstack/l2_vwap_reversion/src/main.py`**

Before:
```python
if self.strategy.position is None:
    # Check actual IBKR position first
    try:
        for p in self.order_session.ib.positions():
            if p.contract.symbol == signal.symbol and abs(p.position) > 0:
                logger.info(f"Blocking entry for {signal.symbol} - existing IBKR position: {p.position}")
                return
    except Exception as e:
        logger.warning(f"Failed to check IBKR positions: {e}")
```

After:
```python
if self.strategy.position is None:
    # Only check our own tracked position, not global IBKR positions
    # This allows multiple strategies to trade the same symbol independently
```

**2. `/home/jacobw/quantstack/l2_scalping/src/main.py`**

Before:
```python
def _can_open_position(self, symbol: str) -> bool:
    # Check actual IBKR position FIRST - critical to prevent pyramiding
    try:
        positions = self.order_manager.session.ib.positions()
        for p in positions:
            if p.contract.symbol == symbol and abs(p.position) > 0:
                logger.info(f"Blocking entry for {symbol} - existing IBKR position: {p.position}")
                return False
    except Exception as e:
        logger.warning(f"Failed to check IBKR positions: {e}")
    
    # Check new position manager
    if self.position_manager.has_open_position(symbol):
        return False
```

After:
```python
def _can_open_position(self, symbol: str) -> bool:
    # Only check our own tracked positions, not global IBKR positions
    # This allows multiple strategies to trade the same symbol independently
    
    # Check new position manager
    if self.position_manager.has_open_position(symbol):
        return False
```

**3. `/home/jacobw/intraday_stack/scripts/paper_trade.py`**

No change needed - already checks only own positions via `self.adapter.get_positions()`

## Result

Each system now independently manages its own positions:
- ✅ l2-scalping can be LONG RMBS
- ✅ l2-vwap can be SHORT RMBS simultaneously
- ✅ intraday-paper can have different position
- ✅ Each system still prevents pyramiding within itself

## Testing

Verified l2-vwap RMBS SHORT signal no longer blocked by intraday-paper LONG position.

## Notes

- Each system tracks its own positions internally
- Position managers prevent pyramiding within each strategy
- Systems can now hedge or take opposite views on same symbol
- Net IBKR position = sum of all system positions
