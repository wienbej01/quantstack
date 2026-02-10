# L2 VWAP System Investigation Report
**Date**: 2026-01-30  
**Issue**: L2 VWAP took no positions on Jan 29

---

## Executive Summary

The L2 VWAP Mean Reversion system is **NOT OPERATIONAL** despite existing in the codebase. Multiple critical issues prevent it from trading:

1. ❌ Service NOT installed in systemd
2. ❌ Timer NOT enabled
3. ❌ Timer scheduled AFTER market open (2:26 PM ET instead of before 9:30 AM ET)
4. ❌ Service ran for only 1 minute on Jan 29 before shutting down
5. ❌ Zero trades recorded in database (ever)

---

## Findings

### 1. Service Configuration

**Service File Exists**: `/home/jacobw/quantstack/systemd/l2-vwap-reversion.service`
```ini
[Unit]
Description=L2 VWAP Mean Reversion Paper Trading
After=network.target l2-scalping.service
Requires=l2-scalping.service  # ← Depends on L2 scalping

[Service]
WorkingDirectory=/home/jacobw/quantstack/l2_vwap_reversion
ExecStart=/home/jacobw/quantstack/.venv/bin/python src/main.py --config config
Restart=on-failure
```

**Timer File Exists**: `/home/jacobw/quantstack/systemd/l2-vwap-reversion.timer`
```ini
[Timer]
# 09:26 ET = 22:26 Manila (UTC+8) during EST (winter)
OnCalendar=Mon-Fri 22:26:00  # ← 2:26 PM ET - AFTER market open!
```

**Installation Status**:
```bash
$ systemctl --user list-unit-files | grep vwap
# NO RESULTS - Service not installed!

$ ls ~/.config/systemd/user/ | grep vwap
# NO RESULTS - Files not linked!
```

### 2. Actual Runtime on Jan 29

**Log Analysis**: `/home/jacobw/quantstack/l2_vwap_reversion/logs/vwap_reversion_20260129.log`

```
2026-01-29 22:26:17 - System started (2:26 PM ET)
2026-01-29 22:26:17 - Connected to IBKR
2026-01-29 22:26:17 - Loaded 3 symbols: JOBY, NOW, FCX
2026-01-29 22:27:29 - Received signal 15, shutting down
```

**Runtime**: 1 minute 12 seconds  
**Trades Executed**: 0  
**Reason**: Started after market hours (2:26 PM ET is near market close)

### 3. Database Evidence

```sql
SELECT COUNT(*), system FROM trades 
WHERE system LIKE '%vwap%' 
GROUP BY system;
-- Result: 0 rows
```

**No L2 VWAP trades have EVER been recorded in the database.**

### 4. Why It Didn't Trade on Jan 29

1. **Started Too Late**: 2:26 PM ET is 5 hours after market open
2. **Ran for 1 Minute**: Shut down at 2:27 PM (signal 15 = SIGTERM)
3. **Market Closing**: By 2:26 PM, market is preparing to close (4:00 PM ET)
4. **No Signals**: Insufficient time to generate and execute signals

---

## Root Cause Analysis

### Issue 1: Service Not Installed
**Problem**: Service files exist in `~/quantstack/systemd/` but are NOT installed in `~/.config/systemd/user/`

**Impact**: Service cannot be started automatically or managed by systemd

**Fix Required**:
```bash
# Install service and timer
cp ~/quantstack/systemd/l2-vwap-reversion.service ~/.config/systemd/user/
cp ~/quantstack/systemd/l2-vwap-reversion.timer ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable timer
systemctl --user enable l2-vwap-reversion.timer

# Start timer
systemctl --user start l2-vwap-reversion.timer
```

### Issue 2: Wrong Schedule
**Problem**: Timer set for 22:26 Manila time = 2:26 PM ET (after market open)

**Impact**: System starts 5 hours late, misses entire morning session

**Correct Schedule**:
- Market opens: 9:30 AM ET = 22:30 Manila (previous day)
- Should start: 9:20 AM ET = 22:20 Manila (previous day)

**Fix Required**:
```ini
[Timer]
# 09:20 ET = 22:20 Manila (UTC+8) during EST
# This is 10 minutes before market open
OnCalendar=Mon-Fri 22:20:00
```

### Issue 3: Dependency on L2 Scalping
**Problem**: Service requires `l2-scalping.service` to be running

**Current State**:
- L2 scalping: ✅ Running
- L2 VWAP: ❌ Not installed

**Impact**: Even if timer fires, service won't start if L2 scalping isn't running

**Consideration**: Should L2 VWAP be independent or dependent?

### Issue 4: Early Shutdown
**Problem**: Service received SIGTERM after 1 minute

**Possible Causes**:
1. Timer is oneshot (starts service then stops it)
2. Service crashed/exited
3. Manual intervention
4. Resource limits

**Investigation Required**: Check why service shut down so quickly

---

## Comparison with Other Systems

| System | Installed? | Enabled? | Running? | Trades (Jan 29) |
|--------|-----------|----------|----------|-----------------|
| l2-scalping | ✅ | ✅ | ✅ | 3,591 fills (0 recorded) |
| intraday-paper | ✅ | ❌ | ❌ | 5 trades |
| l2-vwap-reversion | ❌ | ❌ | ❌ | 0 trades |
| ml-paper-trading | ✅ | ❌ | ❌ | 0 trades |

**Only l2-scalping is actually running!**

---

## Why This Wasn't Caught Earlier

### Possible Reasons:

1. **Service Files Exist**: Files are present in codebase, giving impression system is ready
2. **No Installation Check**: No validation that services are actually installed
3. **No Monitoring**: No alerts for services that should be running but aren't
4. **Timer Not Obvious**: Timer files exist but aren't enabled, easy to miss
5. **Logs Exist**: Log files exist (from manual runs?) suggesting system has run before

### What Was Likely Communicated:

- "L2 VWAP system exists" ✅ TRUE
- "Service files are configured" ✅ TRUE  
- "System can run" ✅ TRUE (manually)
- "System is running automatically" ❌ FALSE
- "System is trading" ❌ FALSE

---

## Recommendations

### Immediate Actions (Priority: HIGH)

1. **Install L2 VWAP Service**
   ```bash
   cp ~/quantstack/systemd/l2-vwap-reversion.* ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable l2-vwap-reversion.timer
   systemctl --user start l2-vwap-reversion.timer
   ```

2. **Fix Timer Schedule**
   - Change from 22:26 to 22:20 Manila time
   - Verify this equals 9:20 AM ET (10 min before market open)

3. **Verify Dependencies**
   - Ensure L2 scalping runs first
   - Consider if VWAP should be independent

4. **Test Service**
   ```bash
   # Manual test run
   systemctl --user start l2-vwap-reversion.service
   
   # Check logs
   journalctl --user -u l2-vwap-reversion.service -f
   
   # Verify it stays running
   systemctl --user status l2-vwap-reversion.service
   ```

### System-Wide Improvements (Priority: MEDIUM)

1. **Service Health Dashboard**
   - Show which services are installed vs configured
   - Show which timers are enabled
   - Show last run time and status

2. **Installation Validation Script**
   ```bash
   # Check all trading services are installed
   for service in l2-scalping intraday-paper l2-vwap-reversion ml-paper-trading; do
       if ! systemctl --user list-unit-files | grep -q "$service"; then
           echo "❌ $service NOT INSTALLED"
       fi
   done
   ```

3. **Pre-Market Checklist**
   - Verify all services running
   - Check last successful trade time
   - Validate data feeds active

4. **Monitoring Alerts**
   - Alert if expected service not running
   - Alert if service hasn't traded in X hours
   - Alert if service starts late

---

## Action Plan

### Phase 1: Install L2 VWAP (30 minutes)
- [ ] Copy service files to ~/.config/systemd/user/
- [ ] Fix timer schedule (22:26 → 22:20)
- [ ] Enable and start timer
- [ ] Verify service starts correctly

### Phase 2: Test (1 hour)
- [ ] Manual service start test
- [ ] Verify IBKR connection
- [ ] Verify L2 data access
- [ ] Check signal generation
- [ ] Confirm trade recording works

### Phase 3: Monitor (Next Trading Day)
- [ ] Verify service starts at 9:20 AM ET
- [ ] Check for trade signals
- [ ] Verify trades recorded in database
- [ ] Monitor for early shutdowns

### Phase 4: System-Wide Audit (2 hours)
- [ ] Document all trading services
- [ ] Verify installation status
- [ ] Check timer schedules
- [ ] Create health dashboard

---

## Questions for User

1. **Was L2 VWAP ever intended to run automatically?**
   - If yes: Why wasn't it installed?
   - If no: Why does it have a timer configuration?

2. **Should L2 VWAP depend on L2 scalping?**
   - Current config requires L2 scalping to be running
   - Is this intentional or should it be independent?

3. **What is the expected trading frequency?**
   - How many trades per day should L2 VWAP generate?
   - This helps validate if system is working correctly

4. **Why did service shut down after 1 minute on Jan 29?**
   - Was this manual intervention?
   - Or did service crash/exit?

---

## Summary

**L2 VWAP is NOT operational** due to:
1. Service not installed in systemd
2. Timer not enabled
3. Timer scheduled for wrong time (after market open)
4. No monitoring to detect these issues

**This is NOT a trade recording bug** - the system simply isn't running.

**Fix is straightforward**: Install service, fix timer, enable, test.

**Estimated time to fix**: 2 hours (install + test + verify)

---

**Report End**
