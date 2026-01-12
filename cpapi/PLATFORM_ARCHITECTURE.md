"""
IBKR API Platform Architecture

Centralized IBKR connection management platform to replace individual service connections.

## Current State Analysis

### Services Using Direct IBKR Connections:
1. **l2-collector**: Uses qx-l2 package with ib_insync (client ID 521)
2. **l2-scalping**: Uses IBKROrderManager with ib_insync (client IDs 10,11)  
3. **intraday-paper**: Uses start_paper_trading.sh with ib_insync
4. **l2-watchdog**: Monitors IBKR connection health
5. **trading-orchestrator**: Gateway management and monitoring

### Problems with Current Architecture:
- Multiple direct ib_insync connections (socket-based, prone to stale connections)
- Duplicate connection management code across services
- Individual watchdog logic in each service
- Client ID conflicts and coordination issues
- No centralized rate limiting or connection pooling

## Proposed Platform Architecture

### Core Components:

1. **IBKR API Platform Service** (`ibkr-platform.service`)
   - Single REST-based service using Client Portal Gateway (port 5000)
   - Manages all IBKR connections centrally
   - Provides unified HTTP API for all trading services
   - Built on existing CPAPI client foundation

2. **Connection Manager**
   - Session management and authentication
   - Automatic tickle/keepalive handling
   - Connection health monitoring and recovery
   - Rate limiting and request queuing

3. **Service Registry**
   - Register/deregister client services
   - Route requests to appropriate IBKR endpoints
   - Track service-specific state (accounts, positions, etc.)

4. **Unified API Endpoints**
   - Market data: `/api/market-data/snapshot`, `/api/market-data/historical`
   - Orders: `/api/orders/place`, `/api/orders/cancel`, `/api/orders/status`
   - Positions: `/api/positions/{account}`, `/api/portfolio/{account}`
   - Accounts: `/api/accounts`, `/api/accounts/switch`

### Service Migration Strategy:

1. **l2-collector** → HTTP client to platform `/api/market-data/*`
2. **l2-scalping** → HTTP client to platform `/api/orders/*` and `/api/market-data/*`
3. **intraday-paper** → HTTP client to platform for all IBKR operations
4. **l2-watchdog** → Monitor platform health instead of individual connections

### Benefits:
- Single point of IBKR connection management
- REST-based (no socket connection issues)
- Centralized rate limiting and error handling
- Simplified service code (remove ib_insync dependencies)
- Better monitoring and debugging
- Easier testing and development

### Implementation Plan:
1. Expand CPAPI into full platform service
2. Add HTTP server with unified API endpoints
3. Migrate services one by one to use platform
4. Remove direct ib_insync dependencies
5. Update systemd services and monitoring
"""
