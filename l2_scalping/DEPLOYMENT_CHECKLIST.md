# Deployment Checklist - Overnight Position Safeguards

## Pre-Deployment Verification

- [x] Python syntax validation passed
- [x] Entry curfew logic tested
- [x] Bracket order price calculations verified
- [x] Exit priority logic confirmed
- [x] Trade ID tracking verified (no changes needed)

## Deployment Steps

### 1. Backup Current System
```bash
cd /home/jacobw/quantstack/l2_scalping
cp src/main.py src/main.py.backup.$(date +%Y%m%d)
cp src/scheduler.py src/scheduler.py.backup.$(date +%Y%m%d)
cp src/execution/order_manager.py src/execution/order_manager.py.backup.$(date +%Y%m%d)
```

### 2. Stop L2-Scalping Service
```bash
sudo systemctl stop l2-scalping
```

### 3. Verify No Open Positions
```bash
python /home/jacobw/quantstack/scripts/query_positions.py --date $(date +%F)
```

### 4. Deploy Changes
Files are already modified in place:
- `src/main.py` - Entry curfew + bracket orders + force exit
- `src/scheduler.py` - Entry curfew check
- `src/execution/order_manager.py` - Bracket order support

### 5. Test Configuration
```bash
cd /home/jacobw/quantstack/l2_scalping
python3 test_safeguards.py
```

### 6. Restart Service
```bash
sudo systemctl start l2-scalping
```

### 7. Monitor Logs
```bash
journalctl -u l2-scalping -f
```

## Post-Deployment Monitoring

### Day 1 - Watch for New Log Messages

**Entry Curfew**:
```
"Entry blocked by curfew: Insufficient time: XXXs until close, need 660s"
```
- Should appear after 15:49 ET (with 600s max hold)

**Bracket Orders**:
```
"Bracket order placed: SYMBOL SIDE QTY -> parent=XXX, stop=XX.XX, target=XX.XX"
```
- Should appear with every entry order

**Force Exit**:
```
"FORCE EXIT: SYMBOL exceeded max hold time"
"Exit order placed (MARKET): SYMBOL SIDE QTY@MKT - MAX_HOLD_EXCEEDED"
```
- Should appear if position held > 600s

### Day 2-5 - Verify No Overnight Positions

```bash
# Check for positions at market open (9:30 AM ET)
python /home/jacobw/quantstack/scripts/query_positions.py --date $(date +%F)

# Should return: No open positions
```

### Week 1 - Analyze Exit Patterns

```bash
# Check trade journal for exit reasons
psql -d trading -U jacobw -c "
SELECT 
    exit_reason,
    COUNT(*) as count,
    AVG(pnl) as avg_pnl
FROM trades
WHERE exit_time >= NOW() - INTERVAL '7 days'
GROUP BY exit_reason
ORDER BY count DESC;
"
```

Expected exit reasons:
- `Scheduled exit (XXXs)` - Normal 5-min exits
- `Profit target (XX.X bps)` - Early profit exits
- `Stop loss (XX.X bps)` - Early loss exits
- `MAX_HOLD_EXCEEDED (XXXs >= 600s)` - Force exits (should be rare)

## Rollback Procedure

If issues occur:

```bash
# Stop service
sudo systemctl stop l2-scalping

# Restore backups
cd /home/jacobw/quantstack/l2_scalping
cp src/main.py.backup.YYYYMMDD src/main.py
cp src/scheduler.py.backup.YYYYMMDD src/scheduler.py
cp src/execution/order_manager.py.backup.YYYYMMDD src/execution/order_manager.py

# Restart service
sudo systemctl start l2-scalping
```

## Success Criteria

- [ ] No positions remain open after 16:00 ET market close
- [ ] Entry curfew blocks trades after 15:49 ET
- [ ] Bracket orders placed with every entry
- [ ] Force exits trigger at 600s max hold
- [ ] Trade IDs correctly tracked from entry to exit
- [ ] No system crashes or errors in logs

## Known Limitations

1. **IBKR Time-Based Stops**: IBKR does not support time-based conditional orders directly. We use:
   - Bracket orders (stop-loss + profit-target)
   - Polling loop with force exit
   - Entry curfew to prevent late entries

2. **Bracket Order Behavior**: If parent order is IOC and doesn't fill, child orders are automatically cancelled by IBKR.

3. **Market Order Slippage**: Force exits use market orders for guaranteed execution, which may result in slippage during volatile periods.

## Emergency Contacts

- **System Owner**: jacobw
- **Emergency EOD Close**: Runs automatically at 15:55 ET via systemd timer
- **Manual Position Close**: `python /home/jacobw/quantstack/scripts/emergency_eod_close.py`

## Documentation

- Full details: `/home/jacobw/quantstack/l2_scalping/docs/OVERNIGHT_POSITION_SAFEGUARDS.md`
- Test script: `/home/jacobw/quantstack/l2_scalping/test_safeguards.py`
- System guide: `/home/jacobw/quantstack/docs/SYSTEM_GUIDE.md`
