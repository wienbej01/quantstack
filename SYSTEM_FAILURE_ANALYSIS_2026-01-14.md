# System Failure Analysis - 2026-01-14 05:13 ET

**Analysis Time**: 2026-01-14 18:16 Manila (05:16 ET)  
**Issue**: NTFY failure alerts during sleep hours (outside market hours)  
**Status**: ❌ **CRITICAL** - Multiple system failures

---

## Executive Summary

Your system is experiencing **cascading failures** due to the IBKR Client Portal Gateway being down. At 05:13 ET (well outside market hours of 09:30-16:00), the system should be dormant, but you're receiving failure notifications because:

1. **Client Portal Gateway is NOT running** (port 5000 down)
2. **IBKR Platform is unauthenticated** (depends on Gateway)
3. **L2 Scalping service failing** (missing SIP universe for today)
4. **Health monitor spamming alerts** (NTFY encoding bug + repeated failures)

---

## Root Causes Identified

### 1. Client Portal Gateway Down ❌ **CRITICAL**

**Evidence**:
```
Connection refused to localhost:5000
HTTPSConnectionPool(host='localhost', port=5000): Max retries exceeded
```

**Impact**:
- IBKR Platform cannot authenticate
- All trading services cannot connect to IBKR
- Platform health shows: `"authenticated": false, "connected": false`

**Process Check**:
```bash
ps aux | grep -E "(gateway|clientportal)"
# Result: NO PROCESSES FOUND
```

**Root Cause**: Gateway process not running (likely crashed overnight or never started)

---

### 2. Missing SIP Universe for Today ❌ **CRITICAL**

**Evidence**:
```
RuntimeError: No SIP universe found! 
SIP file not found: /home/jacobw/intraday_stack/data/daily_sip/date=2026-01-14/sip_universe.json
```

**Directory Status**:
```bash
ls -la /home/jacobw/intraday_stack/data/daily_sip/date=2026-01-14/
# Result: EMPTY DIRECTORY (only . and ..)
```

**Last SIP Generation**: 2026-01-13 (yesterday)

**Root Cause**: `intraday-sip.timer` scheduled for 22:10 Manila (09:10 ET) has NOT run yet today

**Timer Status**:
```
Next run: Wed 2026-01-14 22:10:00 PST (3h 53min from now)
Last run: Tue 2026-01-13 22:10:00 PST
```

**Why L2 Scalping is Failing NOW**:
- L2 scalping service is configured to auto-restart on failure
- It's attempting to start but failing immediately because SIP universe doesn't exist yet
- **Restart counter: 49 attempts** (continuous failure loop)

---

### 3. Health Monitor Alert Spam ⚠️ **HIGH**

**Evidence**:
```
Every 2 minutes from 00:14 to 00:42 (and likely continuing):
ERROR - NTFY failed: 'latin-1' codec can't encode character '\U0001f6a8' 
WARNING - Issues found: ['💳 No IBKR accounts available - check Client Portal Gateway']
```

**Problems**:
1. **NTFY encoding bug**: Emoji characters (💳, 🚨) causing encoding failures
2. **Alert spam**: Health monitor running every 5 minutes, detecting same issue repeatedly
3. **No successful notifications**: NTFY failures mean you're NOT getting the alerts (but service is logging them)

**Root Cause**: 
- Health monitor detects Gateway down
- Attempts to send NTFY alert with emoji
- Python `latin-1` codec can't encode emoji → alert fails silently
- Repeats every 5 minutes

---

### 4. Service Status Summary

| Service | Status | Issue |
|---------|--------|-------|
| **ibkr-platform** | ✅ Running | ❌ Not authenticated (Gateway down) |
| **l2-collector** | ✅ Running | ⚠️ Connected but no data (market closed) |
| **l2-scalping** | ❌ **FAILING** | Missing SIP universe (49 restart attempts) |
| **intraday-paper** | ⚠️ Inactive | Waiting for timer (09:27 ET) |
| **l2-watchdog** | ✅ Running | Monitoring but can't fix root cause |
| **system-health-monitor** | ⚠️ Running | Alert spam + encoding bug |
| **Client Portal Gateway** | ❌ **DOWN** | Process not running |

---

## Why You're Getting Alerts at 05:13 ET (Sleep Hours)

**Expected Behavior**: System should be dormant outside market hours (09:30-16:00 ET)

**Actual Behavior**: 
1. **Health monitor runs 24/7** (every 5 minutes) - detects Gateway down
2. **L2 scalping auto-restart loop** - failing every 30 seconds (49 attempts)
3. **NTFY alerts triggered** - but failing due to encoding bug

**Market Hours Check**:
```python
# system_health_monitor.py line check
if not (7 <= current_hour <= 16):  # 07:00 - 16:30 ET
    logger.info("Outside monitoring hours - skipping")
```

**Issue**: Health monitor IS respecting hours (skipping at 05:14), but:
- L2 scalping service failures still trigger `service_failure_alert.sh`
- These alerts are sent via NTFY regardless of market hours
- You're getting failure notifications from systemd, not health monitor

---

## Timeline of Events (Best Estimate)

**Yesterday (2026-01-13)**:
- 22:10 Manila: SIP generation ran successfully (date=2026-01-13)
- Market hours: System operated normally
- Evening: Client Portal Gateway crashed or was stopped

**Overnight (2026-01-14 00:00 - 05:00 ET)**:
- 00:14 ET: Health monitor starts detecting Gateway down
- Every 5 min: Health monitor logs warnings (NTFY fails due to encoding)
- Continuous: L2 scalping attempts to start, fails (no SIP), restarts (49 times)

**Current (05:13 ET)**:
- Gateway still down
- Platform unauthenticated
- L2 scalping in failure loop
- You receive NTFY alerts from service failures

**Upcoming**:
- 07:00 ET (20:00 Manila): Preflight check will run (will detect Gateway down)
- 08:00 ET (21:00 Manila): Trading orchestrator will run (will detect issues)
- 09:10 ET (22:10 Manila): SIP generation scheduled (will fail without Gateway)

---

## Immediate Actions Required

### 1. Stop L2 Scalping Failure Loop ⚡ **URGENT**
```bash
# Stop the auto-restart loop
sudo systemctl stop l2-scalping.service

# Disable timer until system is fixed
sudo systemctl stop l2-scalping.timer
```

### 2. Start Client Portal Gateway ⚡ **CRITICAL**
```bash
# Navigate to gateway directory
cd /home/jacobw/quantstack/cpapi/gateway

# Start gateway
nohup bin/run.sh root/conf.yaml > gateway_startup.log 2>&1 &

# Wait 30 seconds for startup
sleep 30

# Check if running
ps aux | grep clientportal

# Check port
curl -k https://localhost:5000/v1/api/iserver/auth/status
```

### 3. Browser Authentication 🔐 **REQUIRED**
```bash
# Open browser to Gateway
firefox https://localhost:5000

# Login with:
# - IBKR username
# - IBKR password
# - 2FA code from authenticator app

# Verify authentication
curl -k https://localhost:5000/v1/api/iserver/auth/status
# Should show: "authenticated": true
```

### 4. Verify Platform Authentication ✅
```bash
# Check platform health
curl -s http://127.0.0.1:8000/health | jq .

# Should show:
# "authenticated": true
# "connected": true

# If not, restart platform
sudo systemctl restart ibkr-platform.service
sleep 10
curl -s http://127.0.0.1:8000/health | jq .
```

### 5. Fix NTFY Encoding Bug 🐛
```bash
# Edit health monitor to remove emoji or use UTF-8
nano /home/jacobw/quantstack/system_health_monitor.py

# Find NTFY calls with emoji (💳, 🚨)
# Replace with ASCII equivalents or ensure UTF-8 encoding
```

---

## Preventive Measures

### 1. Gateway Auto-Restart
**Problem**: Gateway crashes overnight, no auto-recovery

**Solution**: Enable `gateway-manager.service` for automatic monitoring
```bash
sudo systemctl enable gateway-manager.service
sudo systemctl start gateway-manager.service
```

### 2. SIP Generation Dependency
**Problem**: L2 scalping tries to start before SIP generation

**Solution**: Add systemd dependency
```ini
# /etc/systemd/system/l2-scalping.service
[Unit]
After=intraday-sip.service
Requires=intraday-sip.service

[Service]
# Add pre-check
ExecStartPre=/bin/bash -c 'test -f /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%%F)/sip_universe.json'
```

### 3. Market Hours Enforcement
**Problem**: Services attempt to run outside market hours

**Solution**: Add market hours check to all service startup scripts
```bash
# Add to start_scalping.sh
current_hour=$(TZ=America/New_York date +%H)
if [ $current_hour -lt 7 ] || [ $current_hour -gt 16 ]; then
    echo "Outside market hours - exiting"
    exit 0
fi
```

### 4. NTFY Encoding Fix
**Problem**: Emoji characters cause encoding failures

**Solution**: Use UTF-8 encoding or ASCII-only messages
```python
# In system_health_monitor.py
import requests

def send_ntfy(message, priority=3):
    requests.post(
        "https://ntfy.sh/jacobw-trading-alerts",
        data=message.encode('utf-8'),  # Force UTF-8
        headers={"Priority": str(priority)}
    )
```

### 5. Gateway Health Check
**Problem**: No monitoring of Gateway process health

**Solution**: Add Gateway process check to health monitor
```python
# In system_health_monitor.py
def check_gateway_process():
    result = subprocess.run(['pgrep', '-f', 'clientportal'], capture_output=True)
    return result.returncode == 0
```

---

## Recovery Checklist

- [ ] Stop l2-scalping service and timer
- [ ] Start Client Portal Gateway
- [ ] Browser authentication (IBKR login + 2FA)
- [ ] Verify platform authentication
- [ ] Fix NTFY encoding bug
- [ ] Wait for SIP generation (09:10 ET)
- [ ] Re-enable l2-scalping after SIP exists
- [ ] Monitor system through market open
- [ ] Implement preventive measures

---

## System Architecture Issues Revealed

### Design Flaw: No Graceful Degradation
**Problem**: Single point of failure (Gateway) cascades to all services

**Recommendation**: 
- Services should detect Gateway down and sleep/retry gracefully
- No auto-restart loops without dependency checks
- Market hours enforcement at service level

### Design Flaw: Missing Dependency Management
**Problem**: Services start in wrong order or without prerequisites

**Recommendation**:
- Use systemd `After=` and `Requires=` directives
- Add `ExecStartPre=` checks for dependencies (SIP file, Gateway, etc.)
- Fail fast with clear error messages

### Design Flaw: Alert Fatigue
**Problem**: Repeated alerts for same issue, encoding failures

**Recommendation**:
- Implement alert deduplication (only alert on state change)
- Fix encoding issues (UTF-8 everywhere)
- Rate limit alerts (max 1 per hour for same issue)

---

## Next Steps

### Immediate (Now - 07:00 ET)
1. Execute recovery checklist above
2. Stop failure loops
3. Restore Gateway authentication

### Pre-Market (07:00 - 09:30 ET)
1. Monitor preflight check results
2. Verify SIP generation at 09:10 ET
3. Confirm all services ready before market open

### Post-Market (After 16:00 ET)
1. Implement preventive measures
2. Add dependency checks to services
3. Fix NTFY encoding bug
4. Test Gateway auto-restart

### Long-Term (This Week)
1. Implement graceful degradation
2. Add comprehensive dependency management
3. Improve alert system (deduplication, rate limiting)
4. Add Gateway process monitoring
5. Document recovery procedures

---

## Audit Logging Recommendation

**Current Status**: Audit logging system exists but not integrated

**Action**: Integrate audit logging into all services for better forensics
```bash
# Query today's failures
python3 scripts/query_audit.py --date 2026-01-14 --severity ERROR

# Analyze failure patterns
python3 scripts/analyze_failures.py --date 2026-01-14
```

---

## Conclusion

Your system is experiencing **cascading failures** due to:
1. **Client Portal Gateway down** (root cause)
2. **Missing SIP universe** (timing issue - hasn't run yet today)
3. **L2 scalping failure loop** (49 restart attempts)
4. **Health monitor alert spam** (encoding bug)

**Critical Path to Recovery**:
1. Start Gateway → 2. Authenticate → 3. Stop failure loops → 4. Wait for SIP generation

**System is NOT ready for market open** without these fixes.

**Estimated Recovery Time**: 15-30 minutes (if Gateway starts successfully)

**Risk Level**: 🔴 **HIGH** - System will not trade without intervention

---

**Report Generated**: 2026-01-14 18:16:12 Manila (05:16 ET)  
**Analyst**: Kiro AI System Analysis  
**Next Review**: After recovery actions completed
