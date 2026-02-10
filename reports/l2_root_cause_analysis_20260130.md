# L2 Trading Systems Root Cause Analysis
## January 30, 2026

---

## Executive Summary

**L2 Scalping:** 4 trades (expected: 100-1000)  
**L2 VWAP:** 0 trades (expected: 10-100)  
**Root Cause:** Service scheduling failure + client ID conflicts

---

## Critical Findings

### 1. L2 Scalping: DID NOT RUN DURING MARKET HOURS

**Evidence:**
- Service started: **22:26:15 PST (1:26 AM ET Jan 31)** - AFTER market close
- Timer inactive since: **06:02:30 PST (9:02 AM ET Jan 30)**
- Market hours: 9:30 AM - 4:00 PM ET
- **Service was offline for entire trading day**

**Timeline:**
```
Jan 30 06:02:30 PST (9:02 AM ET) - Timer stopped
Jan 30 09:30:00 ET               - Market opens (NO SERVICE RUNNING)
Jan 30 16:00:00 ET               - Market closes (NO SERVICE RUNNING)
Jan 30 22:26:15 PST (1:26 AM ET) - Service finally starts (too late)
```

**Why 4 trades exist:**
- Trades are from **Jan 29** (carried over position)
- Timestamps show "2026-01-29 16:20:30" in logs
- Service was trying to exit FCX position from previous day
- "Not connected" errors because IBKR was offline

### 2. L2 VWAP: CLIENT ID CONFLICT

**Evidence:**
```
Error 326: Unable to connect as the client id is already in use
clientId 350 already in use
clientId 300 already in use
```

**Timeline:**
- Started: 22:26:16 PST (same time as L2 scalping)
- Immediately hit client ID conflicts
- Could not connect to IBKR
- 0 trades executed

**Root Cause:**
- L2 scalping using client ID 200
- L2 VWAP trying to use client IDs 300/350
- But another process already using those IDs
- No automatic client ID rotation/conflict resolution

### 3. Data Collection: WORKED CORRECTLY

**Evidence:**
```
Raw L2 data: 448MB (5 symbols: FCX, HL, JOBY, NOW, VZ)
Features: 144MB
Collection period: Full trading day
```

**Conclusion:** Data infrastructure is healthy

---

## Root Cause Analysis

### Primary Failure: Timer/Service Management

**Problem:** l2-scalping.timer stopped at 9:02 AM ET on Jan 30

**Possible Causes:**
1. **Manual stop:** Someone/something stopped the timer
2. **System restart:** Machine rebooted, timer didn't restart properly
3. **Systemd bug:** Timer failed to trigger
4. **Dependency failure:** Required service failed, cascaded to timer

**Evidence Needed:**
```bash
# Check system reboot history
last reboot | grep "2026-01-30"

# Check who stopped the timer
journalctl -u l2-scalping.timer --since "2026-01-29" | grep -i "stop\|deactivat"

# Check systemd errors
journalctl --since "2026-01-30 06:00" --until "2026-01-30 09:30" | grep -i "l2-scalping\|timer\|failed"
```

### Secondary Failure: Client ID Management

**Problem:** No automatic conflict resolution

**Current Behavior:**
- L2 VWAP tries client ID 300
- Gets error 326 (in use)
- Tries client ID 350
- Gets error 326 again
- **GIVES UP** - no retry with different ID

**Expected Behavior:**
- Detect client ID conflict
- Automatically try next available ID in range
- Retry with exponential backoff
- Alert if all IDs exhausted

**Missing Monitoring:**
- No alert when client ID conflict occurs
- No automatic ID rotation
- No health check detecting "stuck" connection attempts

---

## Questions to Answer

### 1. Why did the timer stop at 9:02 AM?
```bash
# Check timer stop reason
journalctl -u l2-scalping.timer --since "2026-01-30 05:00" --until "2026-01-30 10:00"

# Check if system rebooted
last reboot

# Check for manual stops
journalctl | grep "l2-scalping.timer" | grep -i "stop\|deactivat"
```

### 2. What client IDs are currently in use?
```bash
# Check IBKR connections
netstat -an | grep 7494  # Paper trading port
netstat -an | grep 7496  # Live trading port

# Check running processes
ps aux | grep -i "ibkr\|tws\|gateway"

# Check other trading services
systemctl status intraday-paper.service
systemctl status l2-vwap-reversion.service
```

### 3. Is there a monitoring system?
```bash
# Check for health monitor
systemctl status l2-health-monitor.service

# Check for alerts
journalctl -u l2-health-monitor.service --since "2026-01-30"

# Check alert configuration
cat /etc/systemd/system/l2-health-monitor.service
```

### 4. Why no automatic recovery?
- Timer should restart service if it fails
- Service should retry connection if IBKR unavailable
- Health monitor should alert on prolonged downtime

---

## Immediate Actions Required

### 1. Restart L2 Scalping Timer
```bash
sudo systemctl start l2-scalping.timer
sudo systemctl status l2-scalping.timer
```

### 2. Fix Client ID Conflicts
**Option A: Static ID Assignment**
```
l2-scalping:     client_id = 200
l2-vwap:         client_id = 300
intraday-paper:  client_id = 111
```

**Option B: Dynamic ID Pool**
```python
# Try IDs in range 200-399
for client_id in range(200, 400):
    try:
        connect(client_id)
        break
    except ClientIDInUseError:
        continue
```

### 3. Add Client ID Conflict Monitoring
```python
# In connection code
if error_code == 326:  # Client ID in use
    logger.error(f"CLIENT_ID_CONFLICT: {client_id} in use")
    send_alert("L2 VWAP cannot connect - client ID conflict")
    # Try next ID
    client_id = get_next_available_id()
    retry_connection(client_id)
```

### 4. Add Service Health Monitoring
```bash
# Create monitoring script
#!/bin/bash
# Check if L2 services are running during market hours
if is_market_hours; then
    if ! systemctl is-active l2-scalping.service; then
        alert "L2 SCALPING DOWN DURING MARKET HOURS"
        systemctl start l2-scalping.service
    fi
fi
```

---

## Long-Term Fixes

### 1. Robust Timer Management
- Add `Restart=always` to service
- Add `RestartSec=60` for retry delay
- Monitor timer health separately
- Alert if timer stops unexpectedly

### 2. Client ID Pool Management
```python
class ClientIDPool:
    def __init__(self, start=200, end=399):
        self.available = set(range(start, end + 1))
        self.in_use = {}
    
    def acquire(self, service_name):
        if not self.available:
            raise NoAvailableClientIDsError()
        client_id = self.available.pop()
        self.in_use[client_id] = service_name
        return client_id
    
    def release(self, client_id):
        if client_id in self.in_use:
            del self.in_use[client_id]
            self.available.add(client_id)
```

### 3. Connection Retry Logic
```python
def connect_with_retry(max_attempts=10):
    for attempt in range(max_attempts):
        try:
            client_id = id_pool.acquire(service_name)
            session.connect(client_id=client_id)
            return client_id
        except ClientIDInUseError:
            logger.warning(f"Client ID {client_id} in use, trying next")
            id_pool.release(client_id)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            time.sleep(5)
    raise ConnectionFailedError("Exhausted all retry attempts")
```

### 4. Comprehensive Monitoring
- Service uptime during market hours
- Client ID usage tracking
- Connection health checks
- Trade volume anomaly detection
- Automatic alerts and recovery

---

## Testing Plan

### 1. Verify Timer Restart
```bash
sudo systemctl start l2-scalping.timer
sleep 60
systemctl status l2-scalping.timer | grep "Active: active"
```

### 2. Test Client ID Conflict Resolution
```bash
# Start L2 scalping (uses ID 200)
sudo systemctl start l2-scalping.service

# Start L2 VWAP (should auto-select different ID)
sudo systemctl start l2-vwap-reversion.service

# Check both connected
journalctl -u l2-vwap-reversion.service | grep "Connected to IBKR"
```

### 3. Simulate Timer Failure
```bash
# Stop timer during "market hours"
sudo systemctl stop l2-scalping.timer

# Wait 5 minutes
sleep 300

# Check if monitoring detected and alerted
journalctl -u l2-health-monitor.service | grep "ALERT"
```

---

## Summary

**Jan 30 Failure:**
1. L2 scalping timer stopped at 9:02 AM ET
2. Service didn't run during entire trading day (9:30 AM - 4:00 PM)
3. Service finally started at 1:26 AM ET (next day, too late)
4. L2 VWAP hit client ID conflicts, couldn't connect
5. Data collection worked fine (448MB collected)

**Impact:**
- Lost entire trading day for L2 systems
- 0 real trades on Jan 30
- 4 "trades" are actually Jan 29 position cleanup attempts

**Fix Priority:**
1. **CRITICAL:** Restart timer and verify it triggers tomorrow
2. **HIGH:** Implement client ID conflict resolution
3. **HIGH:** Add service health monitoring during market hours
4. **MEDIUM:** Add automatic recovery mechanisms
5. **LOW:** Investigate why timer stopped (forensics)
