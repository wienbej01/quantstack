# Trade Recording Issues - Summary & Plan
**Date**: 2026-01-30  
**Status**: Analysis Complete, Ready for Implementation

---

## Issues Identified

### 1. L2 Scalping: Trades Not Recorded ❌
- **Impact**: 3,591 fills on Jan 29, but 0 trades in database
- **Root Cause**: `_legacy_fill_handler()` only calls `record_fill()`, never `record_trade_entry()`
- **File**: `/home/jacobw/quantstack/l2_scalping/src/main.py`

### 2. Intraday: Wrong Exit Prices ❌
- **Impact**: 5 trades show $0 P&L, actual P&L is -$595
- **Root Cause**: Trades table records signal prices instead of actual fill prices
- **File**: Intraday system trade closing logic (TBD)

### 3. NTFY: Shows Price $0 Value $0 ❌
- **Impact**: User receives notifications with zero prices
- **Root Cause**: Same as Issue #1 - `record_trade_entry()` never called
- **Will be fixed**: Automatically resolved by fixing Issue #1

---

## Documentation

### Detailed Reports
1. **`~/quantstack/reports/jan29_trade_issues_report.md`**
   - Full analysis of all 3 issues
   - Evidence from logs and database
   - Impact assessment
   - Revised conclusions after investigation

2. **`~/quantstack/scripts/fix_trade_recording_plan.md`**
   - 7-phase implementation plan
   - Detailed code changes with examples
   - Testing procedures
   - Monitoring setup
   - Estimated timeline: 3 days

---

## Implementation Plan

### Phase 1: Audit ✅ COMPLETE
- Identified L2 and intraday issues
- Documented root causes
- Created fix plan

### Phase 2: Fix L2 Scalping (NEXT)
**File**: `/home/jacobw/quantstack/l2_scalping/src/main.py`

**Changes Required**:
1. Add instance variable: `self.active_trades = {}`
2. Add helper methods:
   - `_extract_rule_from_ref()` - Extract rule name from order ref
   - `_determine_exit_reason()` - Determine exit reason from order ref
3. Modify `_legacy_fill_handler()`:
   - On entry fill: Call `record_trade_entry()`
   - On exit fill: Call `record_trade_exit()`

**Result**: 
- ✅ Trades recorded in database
- ✅ NTFY shows correct prices
- ✅ Full audit trail

### Phase 3: Fix Intraday Exit Prices
**Investigation Required**:
- Find who calls `close_trade()` in event_store.py
- Verify they pass actual fill price, not signal price
- Fix EMERGENCY_EOD logic if needed

**Result**:
- ✅ Correct exit prices in trades table
- ✅ Accurate P&L calculations

### Phase 4: Add Validation
- Database validation function
- Nightly validation script
- Alerts for orphaned fills

### Phase 5: Backfill Historical Data
- Parse L2 logs to reconstruct Jan 29 trades
- Update intraday trades with correct exit prices

### Phase 6: Testing
- Deploy to paper trading
- Execute test trades
- Verify database recording

### Phase 7: Monitoring
- Alert on orphaned fills
- Alert on zero-slippage exits
- Alert on L2 fills without trades

---

## Quick Reference

### Files to Modify
1. `/home/jacobw/quantstack/l2_scalping/src/main.py` - Add trade recording to fill handler
2. Intraday system (TBD) - Fix exit price source
3. `/home/jacobw/quantstack/scripts/validate_trade_recording.py` - New validation script
4. `/home/jacobw/quantstack/scripts/backfill_l2_jan29.py` - New backfill script

### Database Queries

**Check fills vs trades**:
```sql
SELECT 
    DATE(f.timestamp) as date,
    COUNT(*) as fills,
    (SELECT COUNT(*) FROM trades WHERE DATE(entry_time) = DATE(f.timestamp)) as trades
FROM fills f
WHERE f.timestamp >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(f.timestamp);
```

**Check for orphaned fills**:
```sql
SELECT f.symbol, COUNT(*) as fill_count, COUNT(DISTINCT t.trade_id) as trade_count
FROM fills f
LEFT JOIN trades t ON f.order_id = t.entry_order_id OR f.order_id = t.exit_order_id
WHERE f.timestamp::date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY f.symbol
HAVING COUNT(*) > COUNT(DISTINCT t.trade_id);
```

**Fix intraday exit prices**:
```sql
UPDATE trades t
SET 
    exit_price = f.price,
    gross_pnl = CASE 
        WHEN t.direction = 'long' THEN (f.price - t.entry_price) * t.exit_qty
        ELSE (t.entry_price - f.price) * t.exit_qty
    END,
    net_pnl = CASE 
        WHEN t.direction = 'long' THEN (f.price - t.entry_price) * t.exit_qty - t.commission
        ELSE (t.entry_price - f.price) * t.exit_qty - t.commission
    END
FROM fills f
WHERE t.exit_order_id = f.order_id
  AND t.entry_time::date = '2026-01-29'
  AND t.system = 'intraday-paper';
```

---

## Timeline

- **Phase 1**: ✅ Complete (2 hours)
- **Phase 2**: 4 hours (L2 fix)
- **Phase 3**: 4 hours (Intraday fix)
- **Phase 4**: 2 hours (Validation)
- **Phase 5**: 3 hours (Backfill)
- **Phase 6**: 4 hours (Testing)
- **Phase 7**: 2 hours (Monitoring)

**Total**: ~21 hours (3 days)

---

## Risk Mitigation

1. Test all changes in paper trading first
2. Keep database backups before backfill
3. Deploy fixes incrementally (L2 first, then intraday)
4. Monitor closely for 48 hours after deployment
5. Have rollback plan ready

---

## Success Criteria

### After Phase 2 (L2 Fix)
- [ ] L2 fills generate corresponding trade records
- [ ] NTFY notifications show correct prices
- [ ] Database query: `fills_count == trades_count * 2` (entry + exit)

### After Phase 3 (Intraday Fix)
- [ ] Exit prices match actual fills
- [ ] P&L calculations are accurate
- [ ] No zero-slippage trades (unless legitimate)

### After Phase 4 (Validation)
- [ ] Nightly validation runs successfully
- [ ] Alerts trigger on orphaned fills
- [ ] Dashboard shows trade recording health

---

## Next Steps

1. Review this plan with team
2. Schedule implementation window
3. Prepare paper trading environment
4. Begin Phase 2: L2 Scalping fix
5. Test thoroughly before production deployment

---

**All documentation stored in**:
- `~/quantstack/reports/jan29_trade_issues_report.md`
- `~/quantstack/scripts/fix_trade_recording_plan.md`
- `~/quantstack/scripts/fix_trade_recording_summary.md` (this file)
