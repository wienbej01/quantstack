# Service Dependencies Fix - 2026-01-14

**Issue**: Preflight check and trading services failing because they start before IBKR platform is ready

**Solution**: Added systemd dependencies to ensure all services wait for `ibkr-platform.service`

---

## Changes Made

### 1. L2 Collector Dependency
**File**: `/etc/systemd/system/l2-collector.service.d/platform-dependency.conf`
```ini
[Unit]
After=ibkr-platform.service
Requires=ibkr-platform.service
```

### 2. L2 Scalping Dependency
**File**: `/etc/systemd/system/l2-scalping.service.d/platform-dependency.conf`
```ini
[Unit]
After=ibkr-platform.service
Requires=ibkr-platform.service
```

### 3. Intraday Paper Dependency
**File**: `/etc/systemd/system/intraday-paper.service.d/platform-dependency.conf`
```ini
[Unit]
After=ibkr-platform.service
Requires=ibkr-platform.service
```

### 4. Preflight Check Dependency
**File**: `/etc/systemd/system/preflight-check.service.d/platform-dependency.conf`
```ini
[Unit]
After=ibkr-platform.service
Requires=ibkr-platform.service
```

---

## What This Does

**Before**:
- Services could start in any order
- Preflight check ran before platform was ready
- Trading services attempted connections before platform available

**After**:
- `ibkr-platform.service` starts first
- All dependent services wait for platform to be running
- Proper startup sequence guaranteed by systemd

---

## Startup Order Now

```
1. ibkr-platform.service (port 8000)
   ↓
2. preflight-check.service (07:00 ET)
   ↓
3. l2-collector.service (09:25 ET)
   ↓
4. l2-scalping.service (manual start)
   ↓
5. intraday-paper.service (09:27 ET)
```

---

## Verification

```bash
# Check dependencies
systemctl show l2-collector.service | grep -E "^(After|Requires)="
systemctl show l2-scalping.service | grep -E "^(After|Requires)="
systemctl show intraday-paper.service | grep -E "^(After|Requires)="
systemctl show preflight-check.service | grep -E "^(After|Requires)="

# All should show:
# Requires=... ibkr-platform.service ...
# After=... ibkr-platform.service ...
```

---

## Notes

- **Drop-in files**: Using `.d/` directories allows overriding without modifying main service files
- **Requires**: Service will fail if ibkr-platform fails
- **After**: Service waits for ibkr-platform to start before starting itself
- **Daemon reload**: Already executed, changes are active

---

**Applied**: 2026-01-14 20:23 Manila (07:23 ET)  
**Status**: ✅ Dependencies configured, daemon reloaded
