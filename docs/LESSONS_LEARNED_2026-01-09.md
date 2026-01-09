# Lessons Learned: Trading System Resilience (2026-01-09)

## Critical Issues Encountered

### 1. IBKR Gateway API Settings (TWS vs Gateway)
**Problem**: Connections timing out despite Gateway showing "connected"
**Root Cause**: IBKR maintains **separate API settings** for TWS and Gateway. Both must be configured identically.
**Fix**: Configure API settings in BOTH applications:
- Gateway: Configure → Settings → API → Settings
- TWS: File → Global Configuration → API → Settings

**Required Settings (BOTH):**
- ✅ Enable ActiveX and Socket Clients
- ✅ Socket port: 7497
- ✅ Allow connections from localhost only
- ✅ Trusted IPs: 127.0.0.1
- ❌ Read-Only API (unchecked)

### 2. Gateway Duplicate Login Window Bug
**Problem**: Starting Gateway spawns two windows - one login, one active
**Symptom**: Closing the login window kills the main Gateway
**Workaround**: **Minimize and ignore** the duplicate login window. Do not close it.

### 3. Stale Client Connections Block API
**Problem**: Gateway accepts connections but API requests timeout
**Root Cause**: Stale/orphaned client connections consume slots and block new requests
**Symptoms**: 
- Connection succeeds but operations timeout
- Gateway shows multiple client IDs (e.g., 88, 999) that shouldn't exist
**Fix**: Restart Gateway to clear stale connections. No way to manually disconnect clients.

### 4. Async Event Loop in Threads (ib_insync)
**Problem**: "There is no current event loop in thread" errors
**Root Cause**: Calling `ib.connect()` or `ib.sleep()` from a non-main thread
**Fix**: Wrap async calls with `util.run()`:
```python
from ib_insync import util

# WRONG - in thread
self.ib.connect(host, port, clientId)

# CORRECT - in thread  
util.run(self.ib.connectAsync(host, port, clientId))
```

### 5. Client ID Conflicts
**Problem**: Preflight check uses same client ID as stale connection
**Root Cause**: Client ID 999 was used by both preflight and a stale test connection
**Fix**: Use unique client IDs for each component:
- 10, 11: l2-scalping (feed + orders)
- 15: intraday-paper
- 521: l2-collector
- 998: preflight check (changed from 999)

### 6. Health Monitor False Positives
**Problem**: No NTFY alert when l2-scalping was internally broken
**Root Cause**: `systemctl is-active` returns "active" even when service is stuck
**Fix**: Also scan recent logs for CRITICAL errors:
```python
if "CRITICAL" in logs or "Failed to reconnect" in logs:
    alert("Service has CRITICAL failure")
```

### 7. Hardcoded Universe Files
**Problem**: SIP generation only scanning 556 symbols instead of 1796
**Root Cause**: Scripts falling back to hardcoded `nyse_gold_tickers.txt`
**Fix**: Remove all hardcoded ticker file references, use gold data directory directly:
```python
gold_path = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
symbols = [p.name for p in gold_path.iterdir() if p.is_dir()]
```

### 8. Silent Trading Loops (DEBUG logging)
**Problem**: No visibility into trading decisions - logs silent for 40+ minutes
**Root Cause**: All decision cycle logging at DEBUG level
**Fix**: Add INFO-level logging for cycle summaries:
```python
logger.info(f"Cycle {n}: {len(bars)} symbols, {len(candidates)} candidates, {len(tradeable)} tradeable")
```

### 9. Timezone Confusion (Manila vs ET)
**Problem**: Multi-day debugging delays due to 13-hour offset confusion
**Root Cause**: System timezone Manila (UTC+8), market timezone ET (UTC-5)
**Fix**: 
- All trading services use `TZ=America/New_York` in systemd units
- Created [TIMEZONE_GUIDE.md](TIMEZONE_GUIDE.md) for reference
- Always convert timestamps when debugging

## Resilience Improvements Made

### Systemd Services
- Added `TZ=America/New_York` to all trading services
- Pre-flight validation timer at 20:00 Manila (07:00 ET)
- Health monitor only alerts on failures during market hours

### Code Fixes
- Wrapped all threaded async calls with `util.run()`
- Added CRITICAL error detection to health monitor
- Changed preflight client ID to avoid conflicts
- Added INFO-level logging to trading loops

### Documentation
- [IBKR_GATEWAY_STARTUP.md](IBKR_GATEWAY_STARTUP.md) - API settings for TWS AND Gateway
- [TIMEZONE_GUIDE.md](TIMEZONE_GUIDE.md) - Manila/ET conversion reference
- This lessons-learned document

## Recommended Pre-Market Checklist

1. **Gateway Check**
   - Single Gateway instance running
   - No duplicate login windows (minimize if present)
   - API settings configured in BOTH TWS and Gateway

2. **Connection Test**
   ```bash
   python -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1',7497,99); print('OK'); ib.disconnect()"
   ```

3. **Service Status**
   ```bash
   systemctl is-active l2-collector l2-scalping intraday-paper
   ```

4. **Client ID Check**
   - Gateway should show only: 521, 10, 11, 15
   - If stale IDs present (88, 999, etc.), restart Gateway

5. **Log Monitoring**
   ```bash
   tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log
   journalctl -u l2-scalping -f
   ```

## Future Improvements Needed

1. **Auto-restart on CRITICAL errors**: Services should self-heal when detecting internal failures
2. **Gateway health endpoint**: Periodic API ping to detect unresponsive gateway
3. **Client ID cleanup**: Script to detect and warn about stale connections
4. **Structured logging**: JSON logs for easier parsing and alerting
5. **Metrics dashboard**: Real-time visibility into trading activity
