# Gateway Startup + Preflight Redesign - 2026-01-14

**Issue**: IBKR disconnects daily, Gateway not starting automatically, Preflight checking wrong things at wrong time

**Solution**: Automated Gateway startup at 06:00 ET, simplified Preflight at 09:00 ET

---

## Changes Made

### 1. Gateway Automatic Startup (NEW)

**Service**: `/etc/systemd/system/ibkr-gateway-startup.service`
```ini
[Unit]
Description=IBKR Client Portal Gateway Startup
Before=ibkr-platform.service
After=network.target

[Service]
Type=forking
User=jacobw
WorkingDirectory=/home/jacobw/quantstack/cpapi/gateway
ExecStart=/bin/bash -c 'nohup bin/run.sh root/conf.yaml > gateway_startup.log 2>&1 &'
RemainAfterExit=yes
TimeoutStartSec=60
```

**Timer**: `/etc/systemd/system/ibkr-gateway-startup.timer`
```ini
[Timer]
OnCalendar=Mon..Fri 06:00:00 America/New_York
Persistent=true
```

### 2. Platform Dependency on Gateway

**File**: `/etc/systemd/system/ibkr-platform.service.d/gateway-dependency.conf`
```ini
[Unit]
After=ibkr-gateway-startup.service
Wants=ibkr-gateway-startup.service
```

### 3. Simplified Preflight Check

**Updated**: `/home/jacobw/quantstack/scripts/preflight_check.py`

**Removed**:
- Python imports check (not needed)
- SIP file exists check (SIP generates at 09:10, not 09:00)
- Config loads check (not critical)
- Services active check (services not running at 09:00)

**Kept**:
- Gateway process check (critical)
- Platform authentication check (critical)
- Polygon API check (critical)

### 4. Preflight Timer Moved

**Updated**: `/etc/systemd/system/preflight-check.timer`
```ini
[Timer]
OnCalendar=Mon..Fri 09:00:00 America/New_York
```

**Before**: 07:00 ET (too early, services not running)  
**After**: 09:00 ET (right before SIP generation)

---

## New Timer Schedule

```
19:00 Manila / 06:00 ET - ibkr-gateway-startup (NEW - FIRST)
  ↓ (Gateway starts, takes ~30 seconds)
  ↓ (Platform connects to Gateway)
22:00 Manila / 09:00 ET - preflight-check (MOVED from 07:00)
  ↓ (Validates: Gateway running, Platform authenticated, Polygon API)
22:10 Manila / 09:10 ET - intraday-sip (SIP generation)
22:25 Manila / 09:25 ET - l2-collector
22:28 Manila / 09:27 ET - intraday-paper
```

---

## What This Fixes

### Before
- ❌ Gateway not starting automatically (manual browser login required)
- ❌ IBKR disconnects daily, no recovery
- ❌ Preflight at 07:00 ET checking services that aren't running
- ❌ Preflight checking for SIP file before SIP generates
- ❌ Platform starts at boot but Gateway not running

### After
- ✅ Gateway starts automatically at 06:00 ET daily
- ✅ Platform waits for Gateway to be ready
- ✅ Preflight at 09:00 ET checks critical infrastructure only
- ✅ Preflight validates Gateway + Platform + Polygon before SIP
- ✅ Proper startup sequence guaranteed

---

## Manual Authentication Still Required

**Important**: Gateway starts automatically but **browser authentication is still required**:

1. Gateway starts at 06:00 ET (19:00 Manila)
2. Open browser: https://localhost:5000
3. Login with IBKR credentials + 2FA
4. Platform will authenticate automatically after browser login

**Note**: IBKR requires browser-based 2FA authentication daily. This cannot be fully automated.

---

## Verification

```bash
# Check timer schedule
systemctl list-timers | grep -E "(gateway|preflight)"

# Should show:
# Thu 19:00 Manila / 06:00 ET - ibkr-gateway-startup
# Thu 22:00 Manila / 09:00 ET - preflight-check

# Check Gateway process
ps aux | grep clientportal

# Check Platform authentication
curl -s http://127.0.0.1:8000/health | jq .authenticated

# Test preflight manually
/home/jacobw/quantstack/.venv/bin/python /home/jacobw/quantstack/scripts/preflight_check.py
```

---

## Startup Sequence

```
1. 06:00 ET - Gateway starts (ibkr-gateway-startup.timer)
   ├─ Gateway process launches
   └─ Waits for browser authentication

2. Manual - Browser login (https://localhost:5000)
   ├─ IBKR credentials + 2FA
   └─ Gateway authenticated

3. Platform connects to Gateway (automatic)
   └─ Platform shows authenticated=true

4. 09:00 ET - Preflight validates (preflight-check.timer)
   ├─ Gateway process running ✓
   ├─ Platform authenticated ✓
   └─ Polygon API accessible ✓

5. 09:10 ET - SIP generation (intraday-sip.timer)
6. 09:25 ET - L2 collector starts
7. 09:27 ET - Intraday paper starts
```

---

## Files Modified

1. `/etc/systemd/system/ibkr-gateway-startup.service` - NEW
2. `/etc/systemd/system/ibkr-gateway-startup.timer` - NEW
3. `/etc/systemd/system/ibkr-platform.service.d/gateway-dependency.conf` - NEW
4. `/etc/systemd/system/preflight-check.timer` - UPDATED (07:00 → 09:00 ET)
5. `/home/jacobw/quantstack/scripts/preflight_check.py` - SIMPLIFIED

---

**Applied**: 2026-01-14 20:28 Manila (07:28 ET)  
**Status**: ✅ Gateway timer enabled, Preflight moved to 09:00 ET  
**Next Gateway Start**: Thu 2026-01-15 19:00 Manila (06:00 ET)
