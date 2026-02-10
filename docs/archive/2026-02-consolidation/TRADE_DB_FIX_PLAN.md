# Trade Database Fix Plan

**Date**: 2026-02-03  
**Status**: PENDING  
**Priority**: CRITICAL - Blocking all trade recording

## Issues Identified

### Issue 1: L2-SCALPING PositionTracker Init Error

**Error**: `PositionTracker.__init__() missing 1 required positional argument: 'ib'`

**Location**: `/home/jacobw/quantstack/cpapi/trade_integration.py` line 85

**Root Cause**: 
```python
# Current (WRONG):
def reconcile_positions(self):
    return self.positions.reconcile_with_ibkr(self.ib)

# PositionTracker.reconcile_with_ibkr() takes NO arguments - uses self.ib from __init__
```

**Fix**:
```python
def reconcile_positions(self):
    return self.positions.reconcile_with_ibkr()
```

---

### Issue 2: L2-VWAP Fill Object Attribute Error

**Error**: `'Fill' object has no attribute 'execId'`

**Location**: `/home/jacobw/quantstack/cpapi/unified_fill_processor.py` line ~85 `_process_fill()`

**Root Cause**: 
Fill is a NamedTuple with structure:
```python
Fill(contract, execution, commissionReport, time)
```

Code incorrectly accesses `fill.execId` but should access `fill.execution.execId`

**Fix**: Update `_process_fill()` to use correct attribute paths:
```python
def _process_fill(self, fill, source: str):
    """Process fill with database-level deduplication."""
    # For Fill objects from trade.fills (poll loop)
    if hasattr(fill, 'execution'):
        exec_obj = fill.execution
        contract = fill.contract
        commission = fill.commissionReport.commission if fill.commissionReport else 0
    else:
        # For Execution objects from reqExecutions (reconcile loop)
        exec_obj = fill
        contract = None  # Need to handle separately
        commission = 0
    
    wal_entry = {
        'exec_id': exec_obj.execId,
        'ibkr_time': str(exec_obj.time),
        'symbol': contract.symbol if contract else getattr(exec_obj, 'symbol', 'UNKNOWN'),
        'side': exec_obj.side,
        'quantity': int(exec_obj.shares),
        'price': float(exec_obj.price),
        'commission': float(commission),
        'exchange': exec_obj.exchange,
        'ibkr_order_id': exec_obj.orderId,
        'ibkr_perm_id': exec_obj.permId,
        'source': source,
        'received_at': datetime.utcnow().isoformat()
    }
    self._write_wal(wal_entry)
```

---

## Impact

- **l2-scalping**: Crashes on Trade Database V2 init, no trades recorded
- **l2-vwap-reversion**: Continuous errors every 500ms, no fills recorded
- **Database**: No new orders/fills since 2026-02-02

## Files to Modify

1. `/home/jacobw/quantstack/cpapi/trade_integration.py`
2. `/home/jacobw/quantstack/cpapi/unified_fill_processor.py`

## Testing Plan

1. Apply fixes to cpapi files
2. Restart l2-scalping service
3. Restart l2-vwap-reversion service
4. Verify no errors in logs
5. Check database for new entries
6. Monitor for 10 minutes to confirm stability

## Rollback

Original files backed up before changes. Revert if issues persist.
