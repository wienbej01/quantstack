# IBKR GATEWAY CONNECTION PROTOCOL

**Version**: 2026-01-10  
**Critical for**: System stability and connection reliability

## Overview

The IBKR Gateway connection protocol defines how trading systems connect to Interactive Brokers Gateway to prevent connection leaks, client ID conflicts, and system instability.

## Connection Architecture

### Client ID Allocation
```
Range 1-99:     qx-l2 (L2 data collection)
Range 100-199:  Reserved for future expansion
Range 200-299:  l2-scalping system
Range 300-399:  Reserved
Range 400-499:  Reserved
Range 500-599:  l2-collector (521)
Range 600-699:  Reserved
Range 700-799:  Reserved
Range 800-899:  Reserved
Range 900-999:  Utility scripts (preflight=998, emergency=999)

Active Assignments:
- Client 1:   qx-l2 L2 collection
- Client 10:  l2-scalping data feed
- Client 11:  l2-scalping order execution
- Client 15:  intraday-paper trading
- Client 521: l2-collector service
- Client 998: preflight-check
- Client 999: emergency scripts
```

### Gateway Configuration
```
Host: 127.0.0.1
Port: 7497
API Version: Latest
Socket Port: 7496 (if needed)

Required Settings (Both TWS AND Gateway):
- Enable ActiveX and Socket Clients: ✓
- Socket port: 7497
- Master API client ID: 0
- Read-Only API: ✗ (unchecked)
- Download open orders on connection: ✓
```

## Connection Lifecycle

### 1. Pre-Connection Validation
```python
def validate_connection_prerequisites():
    """Validate before attempting connection."""
    # Check Gateway process
    if not is_gateway_running():
        raise ConnectionError("IBKR Gateway not running")
    
    # Check port availability
    if not is_port_accessible("127.0.0.1", 7497):
        raise ConnectionError("Gateway port 7497 not accessible")
    
    # Check client ID availability
    if is_client_id_in_use(client_id):
        raise ConnectionError(f"Client ID {client_id} already in use")
```

### 2. Connection Establishment
```python
def establish_connection(client_id: int, timeout: int = 10):
    """Establish connection with proper error handling."""
    ib = IB()
    
    # CRITICAL: Attach error handlers BEFORE connect()
    ib.errorEvent += on_error
    ib.disconnectedEvent += on_disconnect
    
    try:
        # Connect with timeout
        ib.connect('127.0.0.1', 7497, clientId=client_id, timeout=timeout)
        
        # Validate connection
        if not ib.isConnected():
            raise ConnectionError("Connection failed - not connected")
        
        # Test basic functionality
        account_summary = ib.accountSummary()
        if not account_summary:
            raise ConnectionError("Connection failed - no account data")
        
        logger.info(f"Connected successfully: client_id={client_id}")
        return ib
        
    except Exception as e:
        # CRITICAL: Clean up on failure
        try:
            ib.disconnect()
        except:
            pass
        raise ConnectionError(f"Connection failed: {e}")
```

### 3. Connection Monitoring
```python
def monitor_connection(ib: IB):
    """Monitor connection health."""
    if not ib.isConnected():
        logger.error("Connection lost - attempting reconnect")
        return reconnect_with_backoff(ib)
    
    # Test connection with simple request
    try:
        ib.reqCurrentTime()
        return True
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False
```

### 4. Graceful Disconnection
```python
def disconnect_gracefully(ib: IB):
    """Disconnect with proper cleanup."""
    if not ib.isConnected():
        return
    
    try:
        # Cancel all pending requests
        ib.cancelAllOrders()
        
        # Unsubscribe from data
        for contract in ib.reqContractDetails():
            ib.cancelMktData(contract)
        
        # Disconnect
        ib.disconnect()
        
        # Wait for cleanup
        time.sleep(1)
        
        logger.info("Disconnected gracefully")
        
    except Exception as e:
        logger.error(f"Disconnect error: {e}")
```

## Error Handling

### Connection Errors
```python
def on_error(reqId, errorCode, errorString, contract):
    """Handle IBKR errors."""
    
    # Critical connection errors
    if errorCode in [1100, 1101, 1102]:  # Connectivity lost
        logger.error(f"Connection lost: {errorCode} - {errorString}")
        trigger_reconnect()
    
    # Client ID conflicts
    elif errorCode == 326:  # Client ID in use
        logger.error(f"Client ID conflict: {errorString}")
        # Don't reconnect - use different client ID
        
    # Order errors
    elif errorCode in [201, 202, 203]:  # Order rejected
        logger.warning(f"Order error: {errorCode} - {errorString}")
        
    # Data errors
    elif errorCode in [162, 200]:  # No security definition
        logger.warning(f"Data error: {errorCode} - {errorString}")
    
    else:
        logger.info(f"IBKR message: {errorCode} - {errorString}")
```

### Reconnection Strategy
```python
def reconnect_with_backoff(ib: IB, max_attempts: int = 5):
    """Reconnect with exponential backoff."""
    
    for attempt in range(max_attempts):
        try:
            # Disconnect first
            if ib.isConnected():
                ib.disconnect()
            
            # Wait with exponential backoff
            wait_time = 2 ** attempt
            logger.info(f"Reconnect attempt {attempt + 1}/{max_attempts} in {wait_time}s")
            time.sleep(wait_time)
            
            # Reconnect
            ib.connect('127.0.0.1', 7497, clientId=client_id, timeout=10)
            
            if ib.isConnected():
                logger.info("Reconnection successful")
                return True
                
        except Exception as e:
            logger.error(f"Reconnect attempt {attempt + 1} failed: {e}")
    
    logger.error("All reconnection attempts failed")
    return False
```

## Zombie Connection Prevention

### Root Cause
Failed `ib.connect()` calls can leave sockets in CLOSE-WAIT state, creating "zombie" connections that consume Gateway resources.

### Prevention Strategy
```python
def prevent_zombie_connections():
    """Prevent zombie connection accumulation."""
    
    # 1. Always use try/except around connect()
    try:
        ib.connect('127.0.0.1', 7497, clientId=client_id)
    except Exception as e:
        # CRITICAL: Always disconnect on failure
        try:
            ib.disconnect()
        except:
            pass
        raise
    
    # 2. Set connection timeout
    ib.connect('127.0.0.1', 7497, clientId=client_id, timeout=10)
    
    # 3. Validate connection immediately
    if not ib.isConnected():
        ib.disconnect()
        raise ConnectionError("Connection validation failed")
    
    # 4. Test basic functionality
    try:
        ib.reqCurrentTime()
    except:
        ib.disconnect()
        raise ConnectionError("Connection test failed")
```

### Zombie Detection
```python
def detect_zombie_connections():
    """Detect zombie connections via system monitoring."""
    
    # Check CLOSE-WAIT sockets
    result = subprocess.run(['netstat', '-an'], capture_output=True, text=True)
    close_wait_count = result.stdout.count('CLOSE_WAIT')
    
    if close_wait_count > 5:
        logger.warning(f"High CLOSE_WAIT count: {close_wait_count} (possible zombies)")
        return True
    
    return False
```

## Client ID Management

### Client ID Caching
IBKR Gateway caches client IDs and blocks reconnection with the same ID until Gateway restart.

**Symptoms**:
- Connection succeeds but no data received
- Orders submitted but not executed
- No error messages

**Solution**:
```python
def handle_client_id_caching():
    """Handle Gateway client ID caching."""
    
    # Try primary client ID
    try:
        ib.connect('127.0.0.1', 7497, clientId=primary_client_id)
        if test_connection_functionality(ib):
            return ib
    except:
        pass
    
    # Try backup client IDs in range
    for backup_id in range(primary_client_id + 1, primary_client_id + 10):
        try:
            ib.connect('127.0.0.1', 7497, clientId=backup_id)
            if test_connection_functionality(ib):
                logger.info(f"Using backup client ID: {backup_id}")
                return ib
        except:
            continue
    
    raise ConnectionError("All client IDs in range failed")
```

### Client ID Ranges
Each system uses a dedicated range to prevent conflicts:

```python
CLIENT_ID_RANGES = {
    'qx-l2': (1, 99),
    'l2-scalping': (200, 299),
    'intraday-paper': (15, 15),  # Single ID
    'l2-collector': (521, 521),  # Single ID
    'utilities': (900, 999)
}

def get_available_client_id(system: str) -> int:
    """Get available client ID from system range."""
    start, end = CLIENT_ID_RANGES[system]
    
    for client_id in range(start, end + 1):
        if not is_client_id_in_use(client_id):
            return client_id
    
    raise RuntimeError(f"No available client IDs for {system}")
```

## Farm Disconnect Handling

### Problem
Gateway "farm disconnects" (DISCONNECT_ON_INACTIVITY) break all API connections with no auto-recovery.

### Detection
```python
def detect_farm_disconnect(error_code: int, error_string: str) -> bool:
    """Detect farm disconnect events."""
    
    farm_disconnect_indicators = [
        "DISCONNECT_ON_INACTIVITY",
        "Farm connection is broken",
        "Market data farm connection is broken"
    ]
    
    return any(indicator in error_string for indicator in farm_disconnect_indicators)
```

### Recovery
```python
def handle_farm_disconnect():
    """Handle farm disconnect recovery."""
    
    logger.error("Farm disconnect detected - full system restart required")
    
    # 1. Disconnect all clients
    for ib_client in active_connections:
        try:
            ib_client.disconnect()
        except:
            pass
    
    # 2. Wait for Gateway to stabilize
    time.sleep(30)
    
    # 3. Restart all connections with new client IDs
    for system in systems:
        system.reconnect_with_new_client_id()
```

## Gateway Health Monitoring

### Health Checks
```python
def check_gateway_health():
    """Comprehensive Gateway health check."""
    
    checks = {
        'process_running': is_gateway_process_running(),
        'port_accessible': is_port_accessible('127.0.0.1', 7497),
        'api_responsive': test_api_connection(),
        'zombie_connections': detect_zombie_connections(),
        'memory_usage': get_gateway_memory_usage()
    }
    
    health_score = sum(checks.values()) / len(checks)
    
    if health_score < 0.8:
        logger.warning(f"Gateway health degraded: {health_score:.2f}")
        return False
    
    return True
```

### Automatic Restart
```python
def restart_gateway_if_needed():
    """Restart Gateway if health checks fail."""
    
    if not check_gateway_health():
        logger.error("Gateway health check failed - restart required")
        
        # Note: Gateway restart must be manual or via external script
        # API cannot restart Gateway programmatically
        
        send_alert("Gateway restart required - manual intervention needed")
        return False
    
    return True
```

## Best Practices

### 1. Connection Management
- ✅ Always attach error handlers before `connect()`
- ✅ Use connection timeouts (10 seconds)
- ✅ Validate connection immediately after connect
- ✅ Clean up on connection failures
- ✅ Use exponential backoff for reconnection

### 2. Client ID Management
- ✅ Use dedicated client ID ranges per system
- ✅ Handle client ID caching with backup IDs
- ✅ Never reuse client IDs within same session
- ✅ Document client ID assignments

### 3. Error Handling
- ✅ Handle all IBKR error codes appropriately
- ✅ Distinguish between recoverable and fatal errors
- ✅ Log all connection events for debugging
- ✅ Implement graceful degradation

### 4. Resource Management
- ✅ Monitor for zombie connections
- ✅ Clean up subscriptions on disconnect
- ✅ Cancel pending orders on shutdown
- ✅ Limit concurrent connections per system

### 5. Monitoring
- ✅ Regular health checks
- ✅ Connection quality monitoring
- ✅ Alert on connection issues
- ✅ Track connection metrics

## Troubleshooting

### Common Issues

#### 1. Connection Refused
```bash
# Check Gateway process
ps aux | grep -i gateway

# Check port
netstat -an | grep 7497

# Check API settings in Gateway GUI
```

#### 2. Client ID Conflicts
```bash
# View active connections in Gateway GUI
# Use different client ID range
# Restart Gateway to clear cache
```

#### 3. Zombie Connections
```bash
# Check CLOSE_WAIT sockets
netstat -an | grep CLOSE_WAIT | wc -l

# Restart Gateway if count > 10
```

#### 4. Farm Disconnects
```bash
# Check Gateway logs for "farm" messages
# Full system restart required
# No programmatic recovery possible
```

### Diagnostic Commands
```bash
# Test basic connectivity
python3 -c "
import ib_insync as ib
client = ib.IB()
try:
    client.connect('127.0.0.1', 7497, clientId=999, timeout=5)
    print(f'Connected: {client.isConnected()}')
    print(f'Account: {client.managedAccounts()}')
    client.disconnect()
except Exception as e:
    print(f'Connection failed: {e}')
"

# Check client ID usage
# (View in Gateway GUI - API section)

# Monitor connection health
python3 /home/jacobw/quantstack/scripts/check_portal_status.py
```

## Status: ✅ IMPLEMENTED

This protocol is implemented across all trading systems and has resolved:
- ✅ Zombie connection leaks
- ✅ Client ID conflicts  
- ✅ Farm disconnect recovery
- ✅ Connection stability issues

**Last Updated**: 2026-01-10  
**Next Review**: After 30 days of stable operation

---

*This protocol is critical for system stability. All trading systems must follow these guidelines.*
