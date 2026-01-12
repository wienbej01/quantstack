# IBKR API Connection Protocol

## Overview

All IBKR connections now route through the centralized **IBKR API Platform** running on port 8000. This eliminates direct ib_insync connections and provides a robust, REST-based interface for all trading services.

## Architecture

### IBKR API Platform Service

**Service**: `ibkr-platform.service`  
**Port**: 8000 (HTTP REST API)  
**Backend**: Client Portal Gateway (port 5000)  
**Status**: `systemctl status ibkr-platform.service`

### Connection Flow

```
Trading Services → Platform (8000) → Client Portal Gateway (5000) → IBKR
```

**Benefits**:
- No socket connection issues
- Centralized authentication
- Unified rate limiting
- Built-in health monitoring
- Automatic reconnection

## Service Integration

### Platform Client Usage

Replace direct ib_insync connections with platform client:

```python
from cpapi.platform_client import IBKRPlatformClient

# Old way (deprecated)
# from ib_insync import IB
# ib = IB()
# ib.connect('127.0.0.1', 7497, clientId=123)

# New way
client = IBKRPlatformClient("service-id", "Service Name")
client.register(["market-data", "orders"])

# Use same interface
accounts = client.get_accounts()
positions = client.get_positions(account_id)
orders = client.place_order(account_id, symbol, quantity, side)
```

### Service Registration

All services must register with the platform:

```python
# Register service
success = client.register(["market-data", "orders", "positions"])

# Send periodic heartbeats
client.heartbeat()

# Unregister on shutdown
client.unregister()
```

## API Endpoints

### Service Management

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/services/register` | POST | Register service |
| `/services/{id}/heartbeat` | POST | Service heartbeat |
| `/services/{id}` | DELETE | Unregister service |
| `/health` | GET | Platform health |

### IBKR Operations

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/status` | GET | Authentication status |
| `/api/accounts` | GET | Get accounts |
| `/api/accounts/switch` | POST | Switch account |
| `/api/positions/{account}` | GET | Get positions |
| `/api/portfolio/{account}` | GET | Portfolio summary |
| `/api/market-data/snapshot` | POST | Market data snapshot |
| `/api/market-data/historical` | GET | Historical data |
| `/api/contracts/search` | GET | Search contracts |
| `/api/orders` | GET | Get orders |
| `/api/orders/place` | POST | Place order |
| `/api/orders/{account}/{id}` | DELETE | Cancel order |
| `/api/trades` | GET | Get trades |

## Authentication

### Client Portal Gateway Setup

1. **Start Gateway**:
   ```bash
   cd /home/jacobw/quantstack/cpapi/gateway
   bin/run.sh root/conf.yaml
   ```

2. **Browser Login**:
   - Open `https://localhost:5000`
   - Login with IBKR credentials + 2FA
   - Session valid ~24 hours

3. **Verify Authentication**:
   ```bash
   curl -s http://127.0.0.1:8000/health | jq .authenticated
   ```

### Platform Authentication

The platform automatically manages Client Portal Gateway authentication:
- Checks auth status every 30 seconds
- Attempts reconnection on auth failure
- Provides auth status via `/health` endpoint

## Service Migration

### Current Services

| Service | Status | Migration Required |
|---------|--------|-------------------|
| `l2-collector` | ✅ Active | Replace qx-l2 IBKR calls |
| `l2-scalping` | ✅ Active | Replace IBKROrderManager |
| `intraday-paper` | ✅ Active | Replace ib_insync calls |
| `l2-watchdog` | ✅ Active | Monitor platform health |

### Migration Steps

1. **Replace Connection Code**:
   ```python
   # Before
   from ib_insync import IB
   ib = IB()
   ib.connect('127.0.0.1', 7497, clientId=521)
   
   # After  
   from cpapi.platform_client import IBKRPlatformClient
   client = IBKRPlatformClient("l2-collector", "L2 Data Collector")
   client.register(["market-data"])
   ```

2. **Update API Calls**:
   ```python
   # Before
   contracts = ib.reqContractDetails(contract)
   
   # After
   contracts = client.search_contracts(symbol, "STK")
   ```

3. **Remove ib_insync Dependencies**:
   - Remove `ib_insync` imports
   - Remove connection management code
   - Remove event handlers
   - Remove client ID management

## Health Monitoring

### Platform Health

```bash
# Check platform status
curl -s http://127.0.0.1:8000/health | jq .

# Check registered services
curl -s http://127.0.0.1:8000/health | jq .services

# Check authentication
curl -s http://127.0.0.1:8000/health | jq .authenticated
```

### Service Health

```bash
# Platform service
systemctl status ibkr-platform.service

# Client Portal Gateway
ps aux | grep "java.*clientportal"

# Platform logs
journalctl -u ibkr-platform.service -f
```

### Monitoring Integration

Update `l2-watchdog` to monitor platform instead of individual connections:

```python
# Monitor platform health
health = requests.get("http://127.0.0.1:8000/health").json()
if not health["authenticated"]:
    alert("Platform not authenticated")

# Monitor service registration
if health["services"] < expected_services:
    alert("Services not registered")
```

## Error Handling

### Connection Errors

Platform client automatically handles:
- Connection timeouts (retry with backoff)
- Rate limiting (queue requests)
- Authentication failures (alert via logs)
- Service registration failures (retry)

### Recovery Procedures

1. **Platform Service Down**:
   ```bash
   systemctl restart ibkr-platform.service
   ```

2. **Authentication Lost**:
   - Check Client Portal Gateway status
   - Re-login via browser if needed
   - Platform will auto-reconnect

3. **Service Registration Failed**:
   - Check platform health
   - Retry registration
   - Check service logs

## Configuration

### Platform Configuration

Platform runs with default settings:
- Host: `127.0.0.1`
- Port: `8000`
- Client Portal: `https://localhost:5000`
- Tickle interval: 55 seconds
- Request timeout: 30 seconds

### Service Configuration

Services configure platform client:

```python
config = PlatformConfig(
    base_url="http://127.0.0.1:8000",
    timeout=30,
    retry_attempts=3,
    retry_delay=1.0
)
client = IBKRPlatformClient("service-id", "Service Name", config)
```

## Testing

### Platform Test

```bash
cd /home/jacobw/quantstack
python cpapi/test_platform.py
```

### Service Integration Test

```python
from cpapi.platform_client import IBKRPlatformClient

def test_service_integration():
    client = IBKRPlatformClient("test-service", "Test")
    
    # Test registration
    assert client.register(["market-data"])
    
    # Test API calls
    assert client.is_healthy()
    accounts = client.get_accounts()
    
    # Test cleanup
    assert client.unregister()
```

## Deployment

### Production Setup

1. **Install Platform Service**:
   ```bash
   sudo systemctl enable ibkr-platform.service
   sudo systemctl start ibkr-platform.service
   ```

2. **Migrate Services**:
   - Update service code to use platform client
   - Remove ib_insync dependencies
   - Test with platform running

3. **Update Monitoring**:
   - Point health checks to platform
   - Monitor platform service status
   - Alert on authentication failures

### Rollback Plan

If issues occur:
1. Stop platform service
2. Revert service code to use ib_insync
3. Start Client Portal Gateway directly
4. Restart services with direct connections

## Summary

The IBKR API Platform provides:

- **Centralized Connection Management**: Single point for all IBKR operations
- **REST-based Interface**: No socket connection issues
- **Automatic Recovery**: Built-in reconnection and health monitoring  
- **Service Registry**: Track and manage all connected services
- **Unified Rate Limiting**: Prevent IBKR API violations
- **Simplified Code**: Remove complex ib_insync connection logic

All services now connect through the platform, eliminating the previous connection protocol complexity and providing a robust foundation for trading operations.
