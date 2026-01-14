# Gateway Authentication Reminders - 2026-01-14

## What Was Added

### 1. NTFY Alert on Gateway Startup
**Script**: `/home/jacobw/quantstack/scripts/gateway_auth_reminder.sh`

Sends urgent NTFY notification when Gateway starts:
- 🔐 Title: "IBKR Gateway Started - Authentication Required"
- Priority: Urgent
- Instructions: Open https://localhost:5000 and login

**Triggered by**: `ibkr-gateway-startup.service` via `ExecStartPost`

### 2. Visual Console Reminder
**Script**: `/home/jacobw/quantstack/scripts/auth_reminder_visual.sh`

Displays persistent warning in terminal until authenticated:
```
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║  🔐 IBKR GATEWAY AUTHENTICATION REQUIRED                       ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

  ⚠️  TRADING SYSTEM BLOCKED - AUTHENTICATION NEEDED
  
  ACTION REQUIRED:
  1. Open browser: https://localhost:5000
  2. Login with IBKR credentials
  3. Enter 2FA code
```

**Features**:
- Checks authentication every 10 seconds
- Desktop notifications every 5 minutes (if DISPLAY available)
- Auto-exits when authenticated
- Shows success message when done

### 3. Usage

**Automatic** (when Gateway starts via timer):
- NTFY alert sent automatically
- Check your phone for notification

**Manual** (run in terminal):
```bash
# Start visual reminder
/home/jacobw/quantstack/scripts/auth_reminder_visual.sh

# Or run in background
nohup /home/jacobw/quantstack/scripts/auth_reminder_visual.sh &
```

## Reminder Flow

```
06:00 ET - Gateway starts (ibkr-gateway-startup.timer)
  ↓
Immediate - NTFY alert sent to phone 📱
  ↓
Manual - Run visual reminder in terminal (optional)
  ↓
Loop - Checks every 10 seconds until authenticated
  ↓
Success - Shows ✅ message and exits
```

## Testing

```bash
# Test NTFY alert
/home/jacobw/quantstack/scripts/gateway_auth_reminder.sh

# Test visual reminder
/home/jacobw/quantstack/scripts/auth_reminder_visual.sh
```

## Files Modified

1. `/home/jacobw/quantstack/scripts/gateway_auth_reminder.sh` - NEW
2. `/home/jacobw/quantstack/scripts/auth_reminder_visual.sh` - NEW
3. `/etc/systemd/system/ibkr-gateway-startup.service` - Added ExecStartPost

---

**Applied**: 2026-01-14 20:39 Manila (07:39 ET)  
**Status**: ✅ Reminders configured, tested successfully
