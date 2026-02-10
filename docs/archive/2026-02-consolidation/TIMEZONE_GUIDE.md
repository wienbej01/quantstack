# Timezone Configuration Guide

## The Problem

**System timezone**: Manila (UTC+8)  
**Market timezone**: US Eastern Time (UTC-5 winter, UTC-4 summer)  
**Result**: 13-hour offset causes massive confusion in logs and debugging

## Real Examples from Jan 8, 2026 Incident

| Log Timestamp (Manila) | Actual ET Time | What's Happening |
|------------------------|----------------|------------------|
| Jan 8, 10:20 AM | Jan 7, 9:20 PM | SIP generation (pre-market) |
| Jan 8, 22:30 PM | Jan 8, 9:30 AM | Market opens |
| Jan 8, 23:00 PM | Jan 8, 10:00 AM | First trades should execute |
| Jan 9, 05:00 AM | Jan 8, 4:00 PM | Market closes |

**This caused days of confusion** because logs showed "Jan 8 10:00 AM" but market hadn't opened yet.

## Solution Implemented

### All Trading Services Use ET Timezone

```ini
# /etc/systemd/system/l2-scalping.service
[Service]
Environment="TZ=America/New_York"
```

**Services with TZ=America/New_York**:
- `l2-scalping.service`
- `l2-collector.service`
- `intraday-paper.service`
- `trading-orchestrator.service`

### Orchestrator Uses ET for Market Logic

```python
# bulletproof_orchestrator.py
os.environ["TZ"] = "America/New_York"
time.tzset()
```

### Quick Timezone Conversion

```bash
# Manila to ET (subtract 13 hours in winter, 12 in summer)
Manila: Jan 8, 23:00 → ET: Jan 8, 10:00

# ET to Manila (add 13 hours in winter, 12 in summer)
ET: Jan 8, 09:30 → Manila: Jan 8, 22:30
```

## Debugging Checklist

When debugging trading issues:

1. **Check system timezone**: `timedatectl` → Shows Manila (Asia/Manila)
2. **Check service timezone**: `systemctl cat l2-scalping | grep TZ` → Should show `TZ=America/New_York`
3. **Check log timestamps**: Service logs should show ET, system logs show Manila
4. **Convert timestamps**: Always convert to ET when analyzing market hours
5. **Market hours in Manila**: 22:30 PM → 05:00 AM next day (winter)

## Market Hours Reference

### US Market Hours (ET)
- Pre-market: 04:00 - 09:30 AM
- Regular: 09:30 AM - 04:00 PM
- After-hours: 04:00 - 08:00 PM

### Manila Equivalent (Winter, UTC+8)
- Pre-market: 17:00 - 22:30 PM
- Regular: 22:30 PM - 05:00 AM (next day)
- After-hours: 05:00 - 09:00 AM (next day)

## Python Timezone Conversion

```python
from datetime import datetime
import pytz

manila_tz = pytz.timezone("Asia/Manila")
et_tz = pytz.timezone("America/New_York")

# Manila to ET
manila_time = manila_tz.localize(datetime(2026, 1, 8, 23, 0))
et_time = manila_time.astimezone(et_tz)
print(f"Manila: {manila_time} → ET: {et_time}")
# Output: Manila: 2026-01-08 23:00:00+08:00 → ET: 2026-01-08 10:00:00-05:00
```

## Lessons Learned

1. **Always use market timezone for trading services** - Prevents confusion
2. **Document timezone in all logs** - Include timezone indicator (ET/Manila)
3. **Convert timestamps immediately** - Don't debug in wrong timezone
4. **Test timezone logic** - Verify market hours detection works correctly
5. **Use ISO 8601 with timezone** - `2026-01-08T10:00:00-05:00` is unambiguous

## Files to Check

- `/etc/systemd/system/*.service` - Service timezone configuration
- `bulletproof_orchestrator.py` - Orchestrator timezone setup
- `l2_scalping/src/scheduler.py` - Market hours detection
- Service logs - Should show ET timestamps after fix
