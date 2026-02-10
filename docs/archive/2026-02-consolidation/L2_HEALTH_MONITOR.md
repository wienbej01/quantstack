# L2 Scalping Health Monitor

## Overview

Automated health monitoring and recovery system for L2 scalping service. Detects zombie depth subscriptions and connection issues, then automatically recovers by clearing subscriptions and restarting the service.

## Features

- **Automatic Detection**: Monitors for Error 309 (max depth reached), Error 326 (client ID conflicts), and data flow issues
- **Auto-Recovery**: Stops service, clears zombie subscriptions, restarts service
- **Rate Limiting**: 5-minute cooldown between recovery attempts
- **Max Attempts**: Stops after 3 recovery attempts to prevent infinite loops
- **Self-Healing**: Resets recovery count when system is healthy

## Installation

Already installed and enabled:
```bash
systemctl status l2-health-monitor
```

## Configuration

**Location**: `/home/jacobw/quantstack/scripts/l2_health_monitor.py`

**Parameters**:
- `MONITOR_INTERVAL = 60` - Check every 60 seconds
- `MAX_RECOVERY_ATTEMPTS = 3` - Max 3 recovery attempts
- `RECOVERY_COOLDOWN = 300` - 5 minutes between attempts

## Health Checks

The monitor detects:

1. **Error 309**: Max depth subscriptions reached (zombie connections)
2. **Error 326**: Client ID already in use
3. **Data: False**: No L2 data flowing
4. **Fresh: 0/3**: No fresh snapshots from any symbols

## Recovery Process

When unhealthy:
1. Stop l2-scalping service
2. Run `clear_ibkr_depth_subscriptions.py`
3. Restart l2-scalping service
4. Wait 10s for stabilization
5. Verify recovery

## Monitoring

**View logs**:
```bash
journalctl -u l2-health-monitor -f
```

**Check status**:
```bash
systemctl status l2-health-monitor
```

**Recent health checks**:
```bash
journalctl -u l2-health-monitor --since "1 hour ago" | grep -E "(UNHEALTHY|Recovery|System healthy)"
```

## Manual Control

**Stop monitor**:
```bash
sudo systemctl stop l2-health-monitor
```

**Start monitor**:
```bash
sudo systemctl start l2-health-monitor
```

**Disable auto-start**:
```bash
sudo systemctl disable l2-health-monitor
```

## Log Messages

- `L2 Scalping Health Monitor started` - Monitor initialized
- `UNHEALTHY: <reason>` - Issue detected
- `Attempting recovery (N/3)...` - Recovery started
- `Recovery successful!` - Recovery completed
- `System healthy - resetting recovery count` - System recovered
- `Max recovery attempts (3) reached` - Manual intervention needed

## Troubleshooting

**Monitor not detecting issues**:
- Check if l2-scalping is running: `systemctl status l2-scalping`
- Verify journalctl access: `journalctl -u l2-scalping -n 10`

**Recovery fails repeatedly**:
- Check IBKR Gateway is running: `ss -ltn | grep :7494`
- Verify clear script works: `python3 /home/jacobw/quantstack/scripts/clear_ibkr_depth_subscriptions.py`
- Check for deeper issues in l2-scalping logs

**Max attempts reached**:
- Manual recovery: Stop monitor, manually fix issue, restart monitor
- Check for configuration issues in l2-scalping

## Integration

The monitor runs alongside l2-scalping:
- Starts after l2-scalping service
- Requires l2-scalping to be running
- Auto-restarts if monitor crashes
- Enabled by default on system boot

## Zombie Connection Prevention

This monitor prevents the issue where:
1. L2-scalping starts during development (before 08:00 ET)
2. Creates depth subscriptions
3. Crashes or stops without clean disconnect
4. IBKR Gateway keeps subscriptions active
5. Next startup hits 3-subscription limit (Error 309)

The monitor detects this and automatically clears zombie subscriptions.
