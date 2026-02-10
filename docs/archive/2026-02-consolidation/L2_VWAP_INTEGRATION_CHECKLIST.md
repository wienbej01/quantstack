# L2 VWAP Systemd Integration Checklist

**Date**: 2026-01-30  
**Purpose**: Ensure L2 VWAP is fully integrated into the systemd trading infrastructure

---

## Pre-Installation Verification

### 1. Dependencies Check

- [ ] **L2 Scalping Running**
  ```bash
  systemctl --user status l2-scalping.service
  # Should show: active (running)
  ```

- [ ] **L2 Data Available**
  ```bash
  ls -la ~/quantstack/data/l2/l2_maximum/features/
  # Should show recent parquet files
  ```

- [ ] **SIP Universe Generated**
  ```bash
  ls -la ~/intraday_stack/data/daily_sip/date=$(date +%Y-%m-%d)/sip_universe.json
  # Should exist with 3-7 symbols
  ```

- [ ] **PostgreSQL Accessible**
  ```bash
  psql -d trading -U jacobw -c "SELECT 1;"
  # Should return: 1
  ```

---

## Installation Steps

### 2. Install Service Files

- [ ] **Copy Service File**
  ```bash
  cp ~/quantstack/systemd/l2-vwap-reversion.service ~/.config/systemd/user/
  ```

- [ ] **Copy Timer File**
  ```bash
  cp ~/quantstack/systemd/l2-vwap-reversion.timer ~/.config/systemd/user/
  ```

- [ ] **Verify Files Copied**
  ```bash
  ls -la ~/.config/systemd/user/l2-vwap-reversion.*
  # Should show both .service and .timer
  ```

### 3. Fix Timer Schedule

- [ ] **Edit Timer File**
  ```bash
  nano ~/.config/systemd/user/l2-vwap-reversion.timer
  ```

- [ ] **Change Schedule**
  ```ini
  # OLD (WRONG):
  OnCalendar=Mon-Fri 22:26:00  # 2:26 PM ET
  
  # NEW (CORRECT):
  OnCalendar=Mon-Fri 22:20:00  # 9:20 AM ET
  ```

- [ ] **Save and Exit**

### 4. Reload Systemd

- [ ] **Reload Daemon**
  ```bash
  systemctl --user daemon-reload
  ```

- [ ] **Verify Service Recognized**
  ```bash
  systemctl --user list-unit-files | grep vwap
  # Should show: l2-vwap-reversion.service and .timer
  ```

### 5. Enable Timer

- [ ] **Enable Timer**
  ```bash
  systemctl --user enable l2-vwap-reversion.timer
  ```

- [ ] **Start Timer**
  ```bash
  systemctl --user start l2-vwap-reversion.timer
  ```

- [ ] **Verify Timer Active**
  ```bash
  systemctl --user list-timers | grep vwap
  # Should show next trigger time
  ```

---

## Integration Verification

### 6. Database Integration

- [ ] **Check Event Store Connection**
  ```bash
  # Start service manually
  systemctl --user start l2-vwap-reversion.service
  
  # Check logs for PostgreSQL connection
  journalctl --user -u l2-vwap-reversion.service | grep "PostgreSQL event store"
  # Should show: "Using shared PostgreSQL event store"
  ```

- [ ] **Verify Tables Accessible**
  ```bash
  psql -d trading -U jacobw -c "SELECT COUNT(*) FROM trades WHERE system = 'l2-vwap-reversion';"
  # Should return: 0 (or count if trades exist)
  ```

### 7. NTFY Integration

- [ ] **Check NTFY Enabled**
  ```bash
  journalctl --user -u l2-vwap-reversion.service | grep "NTFY"
  # Should show: "NTFY notifications enabled"
  ```

- [ ] **Test Notification** (when trade occurs)
  - Check NTFY app for trade alerts
  - Verify format matches expected (see L2_VWAP_SYSTEM.md)

### 8. Audit Logging Integration

- [ ] **Check Audit Logger Enabled**
  ```bash
  journalctl --user -u l2-vwap-reversion.service | grep "Audit logging"
  # Should show: "Audit logging enabled"
  ```

- [ ] **Verify Audit Logs Written**
  ```bash
  ls -la ~/quantstack/logs/audit/audit_$(date +%Y-%m-%d).jsonl
  # Should exist
  
  grep "l2-vwap-reversion" ~/quantstack/logs/audit/audit_$(date +%Y-%m-%d).jsonl
  # Should show service events
  ```

### 9. EOD Report Integration

- [ ] **Run EOD Report**
  ```bash
  python3 ~/quantstack/scripts/eod_report.py --date $(date +%Y-%m-%d)
  ```

- [ ] **Verify L2 VWAP Included**
  - Check "PERFORMANCE BY SYSTEM" section
  - Should include `l2-vwap-reversion` row (if trades exist)

### 10. L2 Data Integration

- [ ] **Verify L2 Data Path**
  ```bash
  grep "L2_DATA_ROOT" ~/.config/systemd/user/l2-vwap-reversion.service
  # Should show: Environment=L2_DATA_ROOT=/home/jacobw/quantstack/data/l2
  ```

- [ ] **Check L2 Features Accessible**
  ```bash
  # Start service and check logs
  journalctl --user -u l2-vwap-reversion.service | grep "features"
  # Should show successful L2 data loading
  ```

---

## Functional Testing

### 11. Manual Service Test

- [ ] **Start Service Manually**
  ```bash
  systemctl --user start l2-vwap-reversion.service
  ```

- [ ] **Check Service Running**
  ```bash
  systemctl --user status l2-vwap-reversion.service
  # Should show: active (running)
  ```

- [ ] **Monitor Logs**
  ```bash
  journalctl --user -u l2-vwap-reversion.service -f
  ```

- [ ] **Verify Key Events**
  - [ ] Connected to IBKR
  - [ ] Loaded SIP symbols
  - [ ] L2 data accessible
  - [ ] Strategy initialized
  - [ ] No critical errors

### 12. Signal Generation Test

- [ ] **Wait for Market Hours** (09:35-15:30 ET)

- [ ] **Check for Signals**
  ```bash
  tail -f ~/quantstack/l2_vwap_reversion/logs/vwap_reversion_$(date +%Y%m%d).log | grep -i "signal\|entry\|exit"
  ```

- [ ] **Verify Signal Logic**
  - VWAP deviation conditions checked
  - L2 ratio filter applied
  - Timing constraints enforced

### 13. Trade Execution Test

- [ ] **Wait for Trade Entry**

- [ ] **Verify Bracket Order Placed**
  ```bash
  journalctl --user -u l2-vwap-reversion.service | grep "bracket"
  # Should show bracket order submission
  ```

- [ ] **Check Database Record**
  ```sql
  SELECT * FROM trades 
  WHERE system = 'l2-vwap-reversion' 
  ORDER BY entry_time DESC 
  LIMIT 1;
  ```

- [ ] **Verify Trade Fields**
  - [ ] trade_id not null
  - [ ] entry_price correct
  - [ ] entry_qty correct
  - [ ] system = 'l2-vwap-reversion'
  - [ ] strategy = 'l2_vwap_reversion'

### 14. NTFY Notification Test

- [ ] **Check Entry Notification Received**
  - [ ] Symbol correct
  - [ ] Price not $0
  - [ ] Quantity correct
  - [ ] Strategy shows "l2-vwap-reversion"

- [ ] **Check Exit Notification** (when trade closes)
  - [ ] P&L calculated
  - [ ] Exit reason shown
  - [ ] Exit price correct

### 15. EOD Close Test

- [ ] **Wait Until 15:55 ET**

- [ ] **Verify Position Closed**
  ```bash
  journalctl --user -u l2-vwap-reversion.service | grep "forced_exit\|EOD"
  ```

- [ ] **Check Database Updated**
  ```sql
  SELECT * FROM trades 
  WHERE system = 'l2-vwap-reversion' 
    AND entry_time::date = CURRENT_DATE
    AND exit_reason = 'forced_eod';
  ```

---

## Monitoring Setup

### 16. Health Monitoring

- [ ] **Add to System Health Dashboard** (if exists)

- [ ] **Create Alert Rules**
  - [ ] Service not running during market hours
  - [ ] No trades in 3+ hours
  - [ ] Database connection failures
  - [ ] L2 data not available

### 17. Performance Tracking

- [ ] **Create Performance Dashboard Query**
  ```sql
  -- Save as view or scheduled query
  CREATE VIEW l2_vwap_daily_performance AS
  SELECT 
      entry_time::date as date,
      COUNT(*) as trades,
      SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as winners,
      ROUND(AVG(net_pnl), 2) as avg_pnl,
      ROUND(SUM(net_pnl), 2) as total_pnl,
      ROUND(100.0 * SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
  FROM trades 
  WHERE system = 'l2-vwap-reversion'
  GROUP BY entry_time::date
  ORDER BY date DESC;
  ```

- [ ] **Add to Daily Review Checklist**

---

## Documentation Updates

### 18. Update System Documentation

- [x] **Created L2_VWAP_SYSTEM.md** - Full integration guide
- [x] **Updated INDEX.md** - Added L2 VWAP to active systems
- [x] **Updated INDEX.md** - Added Jan 30 investigation
- [x] **Updated INDEX.md** - Added quick reference section

### 19. Update Operational Docs

- [ ] **Update Daily Checklist**
  - Add L2 VWAP service check
  - Add L2 VWAP performance review

- [ ] **Update Weekly Review**
  - Add L2 VWAP metrics comparison
  - Add strategy validation checks

- [ ] **Update Troubleshooting Guide**
  - Add L2 VWAP specific issues
  - Add dependency troubleshooting

---

## Post-Installation Validation

### 20. Full System Test

- [ ] **Verify All Services Running**
  ```bash
  systemctl --user list-units --type=service | grep -E "l2|intraday|sip"
  ```

- [ ] **Expected Output**:
  ```
  l2-scalping.service          loaded active running
  l2-vwap-reversion.service    loaded active running
  ```

### 21. Verify Service Dependencies

- [ ] **Check L2 Scalping Starts First**
  ```bash
  systemctl --user show l2-vwap-reversion.service | grep "After="
  # Should include: l2-scalping.service
  ```

- [ ] **Test Dependency Behavior**
  ```bash
  # Stop L2 scalping
  systemctl --user stop l2-scalping.service
  
  # Try to start L2 VWAP
  systemctl --user start l2-vwap-reversion.service
  # Should fail or wait for L2 scalping
  ```

### 22. End-to-End Test

- [ ] **Full Trading Day Test**
  - [ ] Service starts at 09:20 ET
  - [ ] Connects to IBKR successfully
  - [ ] Loads SIP symbols
  - [ ] Accesses L2 data
  - [ ] Generates signals (if conditions met)
  - [ ] Executes trades (if signals generated)
  - [ ] Records to database
  - [ ] Sends NTFY notifications
  - [ ] Writes audit logs
  - [ ] Closes positions at 15:55 ET
  - [ ] Appears in EOD report
  - [ ] Service stops cleanly at 16:05 ET

---

## Sign-Off

### Installation Completed By

- Name: _______________
- Date: _______________
- Signature: _______________

### Verification Completed By

- Name: _______________
- Date: _______________
- Signature: _______________

### Production Approval

- Name: _______________
- Date: _______________
- Signature: _______________

---

## Rollback Plan

If issues occur after installation:

```bash
# Stop and disable service
systemctl --user stop l2-vwap-reversion.service
systemctl --user stop l2-vwap-reversion.timer
systemctl --user disable l2-vwap-reversion.timer

# Remove service files
rm ~/.config/systemd/user/l2-vwap-reversion.service
rm ~/.config/systemd/user/l2-vwap-reversion.timer

# Reload systemd
systemctl --user daemon-reload

# Verify removed
systemctl --user list-unit-files | grep vwap
# Should return nothing
```

---

**Checklist Complete**: _____ / 22 sections completed

**Status**: 
- [ ] Not Started
- [ ] In Progress
- [ ] Completed
- [ ] Production Ready

**Notes**:
_____________________________________________________________________________
_____________________________________________________________________________
_____________________________________________________________________________
