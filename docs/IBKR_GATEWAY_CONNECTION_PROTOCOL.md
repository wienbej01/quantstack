# IBKR Gateway Connection Protocol

## Overview

This document defines the complete connection protocol for all trading system services connecting to IBKR Gateway, incorporating critical lessons learned from connection failures, zombie connection leaks, and race conditions.

## Service Architecture

### Active Services and Client IDs

| Service | Client IDs | Purpose | Timer Schedule |
|---------|------------|---------|----------------|
| **l2-scalping** | 20 (orders), 21 (data) | L2-based scalping trades | Always running |
| **l2-collector** | 521 | L2 market depth collection | 09:23 AM ET (Mon-Fri) |
| **intraday-paper** | 998 (preflight), 11 (trading) | Paper trading execution | 09:27 AM ET (Mon-Fri) |
| **l2-watchdog** | None | Service health monitoring | Always running |

### Client ID Allocation Strategy

- **0-99**: Reserved for manual testing and utilities
- **100-199**: Reserved for future expansion
- **500-599**: Data collection services (521 = l2-collector)
- **900-999**: Preflight and validation (998 = preflight)
- **1-50**: Core trading services (11 = intraday-paper, 20-21 = l2-scalping)

**Critical Rule**: Each client ID must be globally unique across ALL services and manual connections.

## Connection Protocol Implementation

### 1. Proper Connection Sequence

```python
def connect(self) -> bool:
    """Correct connection implementation"""
    try:
        if self.ib and self.ib.isConnected():
            return True

        self.ib = IB()
        
        # CRITICAL: Attach error handlers BEFORE connect
        # Required for API handshake to complete
        self.ib.errorEvent += self._on_error
        self.ib.disconnectedEvent += self._on_disconnect
        
        # Connect with timeout
        self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=30)

        # Attach remaining handlers after successful connect
        self.ib.orderStatusEvent += self._on_order_status
        self.ib.execDetailsEvent += self._on_fill

        self.is_connected = True
        return True

    except Exception as e:
        logger.error(f"Connection failed: {e}")
        self.is_connected = False
        
        # CRITICAL: Clean up failed connection to prevent zombie sockets
        if self.ib:
            try:
                self.ib.disconnect()
            except Exception:
                pass
            self.ib = None
        return False
```

### 2. Zombie Connection Prevention

**Root Cause**: Failed `ib.connect()` calls leave TCP sockets open. When Python garbage collects the IB object, the client closes improperly, leaving Gateway in CLOSE-WAIT state.

**Prevention**:
1. Always call `ib.disconnect()` in exception handler
2. Set `self.ib = None` after cleanup
3. Monitor zombie connections: `ss -an | grep 7497 | grep CLOSE-WAIT | wc -l`

### 3. Event Handler Attachment Order

**Critical Discovery**: Error and disconnect handlers MUST be attached BEFORE calling `connect()`. The API handshake requires these handlers to process initial messages.

**Wrong Order** (causes timeout):
```python
ib.connect(...)  # Handshake fails - no error handler
ib.errorEvent += handler  # Too late
```

**Correct Order**:
```python
ib.errorEvent += handler  # Attach first
ib.connect(...)  # Handshake succeeds
```

## Gateway Configuration Requirements

### API Settings (Both TWS and Gateway)

IBKR maintains **separate API settings** for TWS and Gateway. Both must be configured identically:

**Gateway**: Configure → Settings → API → Settings
**TWS**: File → Global Configuration → API → Settings

**Required Settings**:
- ✅ Enable ActiveX and Socket Clients
- ✅ Socket port: 7497 (paper trading)
- ✅ Allow connections from localhost only
- ✅ Trusted IPs: 127.0.0.1
- ❌ Read-Only API (unchecked)
- ❌ Master API client ID (leave empty)

### Connection Limits

- **Maximum concurrent clients**: 32 per Gateway instance
- **Practical limit**: ~8-10 clients before performance degrades
- **Current usage**: 5 clients (well within limits)

## Service Startup Sequence

### Timer Staggering (Prevents Race Conditions)

Services start at different times to prevent simultaneous Gateway connection attempts:

1. **l2-scalping**: Starts immediately (systemd boot)
2. **l2-collector**: 09:23 AM ET (2 min before market prep)
3. **intraday-paper**: 09:27 AM ET (2 min after market prep)

**Gap**: 4 minutes between timed services ensures clean connections.

### Startup Dependencies

```
Gateway (manual start) 
    ↓
l2-scalping (immediate)
    ↓ (2 min gap)
l2-collector (09:23 ET)
    ↓ (4 min gap)  
intraday-paper (09:27 ET)
```

## Error Handling and Recovery

### Connection Error Types

1. **TimeoutError**: API handshake timeout (30s)
   - **Cause**: Missing error handlers, Gateway overload, zombie connections
   - **Recovery**: Restart Gateway, check handler attachment order

2. **Error 1100**: Connectivity lost to IBKR servers
   - **Cause**: Network issues, IBKR maintenance, competing sessions
   - **Recovery**: Automatic reconnection, resubscribe data streams

3. **Error 1101/1102**: Reconnection successful
   - **1101**: Must resubscribe all data streams
   - **1102**: Data streams resume automatically

4. **Client ID conflicts**: Connection hangs during handshake
   - **Cause**: Duplicate client ID already connected
   - **Recovery**: Use unique client ID, check Gateway client list

### Reconnection Logic

```python
def _attempt_reconnect(self) -> None:
    """Proper reconnection with cleanup"""
    while not self.is_connected and self.reconnect_attempts < self.max_attempts:
        self.reconnect_attempts += 1
        time.sleep(self.reconnect_delay)
        
        try:
            # Clean up old connection first
            if self.ib:
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                self.ib = None
            
            # Create fresh connection
            self.ib = IB()
            self.ib.errorEvent += self._on_error
            self.ib.disconnectedEvent += self._on_disconnect
            
            # Use util.run() for async calls in threads
            util.run(self.ib.connectAsync(
                self.host, self.port, clientId=self.client_id, timeout=30
            ))
            
            self.is_connected = True
            logger.info("Reconnection successful")
            return
            
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")
            if self.ib:
                try:
                    self.ib.disconnect()
                except Exception:
                    pass
                self.ib = None
```

## Gateway Health Monitoring

### Connection State Monitoring

```bash
# Check active connections
ss -an | grep 7497 | grep ESTAB | wc -l

# Check zombie connections (should be 0)
ss -an | grep 7497 | grep CLOSE-WAIT | wc -l

# Check Gateway process
ps aux | grep gateway | grep -v grep
```

### Log Analysis

Use `scripts/analyze_gateway_logs.py` to detect:
- Farm disconnects (DISCONNECT_ON_INACTIVITY)
- Client disconnect patterns
- Connection leaks
- Critical errors

### Health Thresholds

- **Zombie connections > 10**: Gateway restart recommended
- **Farm disconnects > 1/day**: Network/IBKR server issues
- **Client disconnects > 5/hour**: Service instability

## Maintenance Procedures

### Daily Gateway Restart (Recommended)

Gateway accumulates state over time. Daily restart prevents issues:

```bash
# Stop all services
systemctl stop l2-collector l2-scalping intraday-paper

# Restart Gateway (manual)
pkill -f "ibgateway"
# Start Gateway, login

# Start services sequentially
systemctl start l2-scalping
sleep 30
systemctl start l2-collector  
sleep 30
systemctl start intraday-paper
```

### Emergency Recovery

If Gateway stops accepting connections:

1. **Check zombie connections**: `ss -an | grep 7497 | grep CLOSE-WAIT`
2. **If > 20 zombies**: Restart Gateway immediately
3. **Check Gateway logs**: Look for farm disconnects
4. **Restart services**: Use sequential startup script

### Pre-Market Checklist

Run at 07:00 AM ET (before market prep):

```bash
# Validate Gateway health
python scripts/analyze_gateway_logs.py

# Test connection
python -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1',7497,99,10); print('OK')"

# Check service status
systemctl status l2-scalping l2-collector intraday-paper l2-watchdog

# Verify timer schedules
systemctl list-timers | grep -E "l2-|intraday"
```

## Troubleshooting Guide

### Connection Timeouts

1. **Check error handler attachment**: Must be before `connect()`
2. **Check client ID conflicts**: Use unique IDs
3. **Check zombie connections**: Restart Gateway if > 10
4. **Check Gateway login**: Must be fully logged in
5. **Check API settings**: Both TWS and Gateway configured

### Service Failures

1. **Check systemd logs**: `journalctl -u service-name`
2. **Check connection cleanup**: Look for disconnect calls
3. **Check timer conflicts**: Ensure staggered starts
4. **Check Gateway capacity**: Max 32 clients

### Performance Issues

1. **Monitor connection count**: Keep under 10 active clients
2. **Check message rates**: IBKR limits 50 msg/sec
3. **Monitor Gateway memory**: Restart if > 2GB
4. **Check network latency**: Should be < 10ms to IBKR

## Files Modified

### Connection Protocol Fixes
- `/home/jacobw/quantstack/l2_scalping/src/execution/order_manager.py`
- `/home/jacobw/quantstack/l2_scalping/src/data/l2_feed.py`
- `/home/jacobw/intraday_stack/src/marketdata/ibkr_client.py`

### Configuration Changes
- `/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml` (client IDs 20, 21)
- `/etc/systemd/system/l2-collector.timer.d/override.conf` (09:23 start)
- `/etc/systemd/system/intraday-paper.timer.d/override.conf` (09:27 start)

### Monitoring Tools
- `/home/jacobw/quantstack/scripts/analyze_gateway_logs.py`
- `/home/jacobw/quantstack/scripts/start_trading_services.sh`

## Summary

This protocol ensures reliable, sustainable connections to IBKR Gateway by:

1. **Preventing zombie connections** through proper cleanup
2. **Avoiding race conditions** through staggered service starts  
3. **Ensuring proper handshakes** through correct handler attachment
4. **Monitoring Gateway health** through automated analysis
5. **Providing recovery procedures** for common failure modes

The system now supports 5 concurrent clients with zero zombie connections and proper error handling.
