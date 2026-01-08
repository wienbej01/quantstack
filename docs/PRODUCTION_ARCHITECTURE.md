# Production Trading System Architecture (2026-01-08)

## System Overview

The quantstack trading system is a production-ready, fully automated trading platform with comprehensive error recovery and monitoring capabilities.

## Core Components

### 1. Trading Orchestrator (`trading_orchestrator.py`)
- **Multi-Session SIP Generation**: Combines prior day + overnight + premarket data
- **API Resilience**: Polygon API with retry logic and exponential backoff
- **Auto-Recovery**: IBKR Gateway and L2 collector automatic restart
- **Health Monitoring**: Comprehensive system health validation
- **Notifications**: Real-time status updates via ntfy

### 2. Systemd Services
```bash
# Core Services (All Enabled for Autostart)
trading-orchestrator.timer    # Daily SIP generation at 8:00 AM ET
ibkr-gateway.service         # IBKR Gateway with auto-restart
l2-collector.service         # L2 data collection
l2-watchdog.service          # L2 system monitoring
```

### 3. Data Pipeline
- **Universe Selection**: 556 NYSE symbols, $2-200 price range
- **SIP Scoring**: Multi-session analysis with 0.85 score floor
- **L2 Collection**: Real-time order book data during market hours
- **Storage**: Parquet format with date/symbol partitioning

## Production Reliability Features

### API Resilience
- **Polygon API**: 3 retries with exponential backoff (1s, 2s, 4s)
- **Connection Pooling**: Persistent HTTP clients (20 keepalive connections)
- **Timeout Management**: 30-second request timeouts
- **Error Handling**: Graceful degradation on API failures

### System Recovery
- **IBKR Gateway**: Automatic restart via systemd on failure
- **L2 Collector**: Auto-recovery with service restart
- **Health Validation**: Continuous monitoring with recovery actions
- **Service Dependencies**: Proper startup ordering and dependencies

### Persistence
- **Autostart**: All services enabled for boot persistence
- **Environment**: API keys stored in systemd environment files
- **Configuration**: Persistent across laptop restarts
- **Scheduling**: Automatic daily execution without intervention

## Monitoring & Notifications

### ntfy Integration
- **Topics**: `trading-system-status`, `trading-system-data`, `trading-system-alerts`
- **Real-time**: iPhone/Android notifications for system events
- **Health Reports**: Daily system status with component health
- **Error Alerts**: Immediate notification on system failures

### Logging
- **Orchestrator**: `/home/jacobw/quantstack/logs/orchestrator.log`
- **L2 Collection**: `/home/jacobw/quantstack/logs/l2_collector.log`
- **Daily SIP**: `/home/jacobw/quantstack/logs/daily_sip.log`

## Daily Execution Flow

### Pre-Market (8:00 AM ET)
1. **SIP Generation**: Multi-session analysis of 556 NYSE symbols
2. **Health Check**: Validate IBKR Gateway, L2 collector, services
3. **Auto-Recovery**: Restart failed components automatically
4. **Notification**: Send system status report via ntfy

### Market Hours (9:30 AM - 4:00 PM ET)
1. **Live Trading**: Execute trades based on SIP universe
2. **L2 Collection**: Capture order book data for analysis
3. **Monitoring**: Continuous health checks and recovery
4. **Alerts**: Real-time notifications on issues

### Post-Market
1. **Data Processing**: Store and analyze collected data
2. **System Cleanup**: Close connections and resources
3. **Preparation**: Ready for next trading day

## Configuration Files

### Service Definitions
- `/etc/systemd/system/trading-orchestrator.service`
- `/etc/systemd/system/trading-orchestrator.timer`
- `/etc/systemd/system/ibkr-gateway.service`
- `/etc/systemd/system/l2-collector.service`

### Environment
- `/etc/systemd/system/polygon.env` - Polygon API key
- `/home/jacobw/quantstack/.venv` - Python virtual environment

### Scripts
- `/home/jacobw/quantstack/trading_orchestrator.py` - Main orchestrator
- `/home/jacobw/quantstack/scripts/start_ibkr_gateway.sh` - IBKR startup

## Deployment Commands

```bash
# Enable all services for autostart
sudo systemctl enable trading-orchestrator.timer
sudo systemctl enable ibkr-gateway.service
sudo systemctl enable l2-collector.service
sudo systemctl enable l2-watchdog.service

# Start services
sudo systemctl start trading-orchestrator.timer
sudo systemctl start ibkr-gateway.service
sudo systemctl start l2-collector.service

# Check status
systemctl status trading-orchestrator.timer
systemctl list-timers trading-orchestrator.timer
```

## Performance Characteristics

### SIP Generation
- **Processing**: 556 symbols in ~5-10 minutes
- **Concurrency**: 8 parallel Polygon API requests
- **Reliability**: 99%+ success rate with retry logic
- **Output**: JSON artifact with scores and metadata

### System Resources
- **Memory**: ~500MB for orchestrator + services
- **Storage**: ~1GB/day for L2 data collection
- **Network**: Minimal bandwidth for API calls
- **CPU**: Low utilization except during SIP generation

## Error Recovery Scenarios

### Polygon API Failures
- **Retry Logic**: Exponential backoff with 3 attempts
- **Fallback**: Skip failed symbols, continue processing
- **Notification**: Alert on excessive failures

### IBKR Gateway Issues
- **Detection**: Socket connection health checks
- **Recovery**: Automatic systemd service restart
- **Validation**: Verify connectivity after restart

### Service Failures
- **L2 Collector**: Auto-restart via systemd
- **Watchdog**: Monitor and recover L2 services
- **Orchestrator**: Timer-based execution resilience

This architecture provides a robust, production-ready trading system with comprehensive error recovery and monitoring capabilities.
