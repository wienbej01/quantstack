# Complete System Guide

**Quantstack Trading System - Production Operations Manual**  
**Version**: 2.0 (Platform-Based Architecture)  
**Date**: 2026-01-13  
**Status**: ✅ **MIGRATION COMPLETE** - Production Ready

## Overview

The Quantstack trading system is a fully automated, platform-based trading infrastructure running on Manila VPS with NY market hours operation. 

**🚨 MAJOR UPGRADE COMPLETED (2026-01-13)**: Successfully migrated from socket-based ib_insync connections to centralized IBKR API Platform, eliminating all stale connection issues.

### Migration Benefits Achieved
- ✅ **No More Stale Connections**: REST-based interface eliminates socket issues completely
- ✅ **Centralized Management**: Single platform handles all IBKR connections
- ✅ **Service Simplification**: Removed complex ib_insync connection management from all services
- ✅ **Better Reliability**: Platform handles reconnection and error recovery automatically
- ✅ **Easier Debugging**: REST endpoints provide clear error messages and status

### Services Successfully Migrated
- ✅ **l2-collector**: Now uses IBKRPlatformClient for market data
- ✅ **l2-scalping**: Migrated to platform client for orders and data
- ✅ **intraday-paper**: Uses platform client for paper trading
- ✅ **l2-watchdog**: Enhanced monitoring with recovery detection

### Legacy Code Archived
- 📁 **18 socket-based files** moved to `archive/socket_based_ibkr/`
- 🗑️ **Obsolete gateway services** disabled and removed
- 📚 **Documentation updated** to reflect new platform architecture

### System Architecture

```
VPN (Manila) → IBKR API Platform (8000) → Client Portal Gateway (5000) → IBKR
                      ↓
    L2 Collector + L2 Scalping + Intraday Paper + L2 Watchdog
                      ↓
              Trading Notifications (NTFY)
```

**Platform Components:**
- **`cpapi/platform.py`** - FastAPI server with unified IBKR endpoints
- **`cpapi/platform_client.py`** - HTTP client replacing ib_insync in all services
- **`cpapi/trading_notifications.py`** - Comprehensive trading activity notifications
- **`ibkr-platform.service`** - Systemd service for platform management

**Migration Pattern Applied:**
```python
# BEFORE (socket-based - REMOVED)
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=521)

# AFTER (platform-based - CURRENT)
from cpapi.platform_client import IBKRPlatformClient
client = IBKRPlatformClient("service-id", "Service Name")
client.register(["market-data", "orders"])
```

---

## 1. VPN Connection & Infrastructure

### VPN Setup
- **Provider**: [Your VPN provider]
- **Server**: Manila, Philippines (UTC+8)
- **Purpose**: Stable connection to IBKR, consistent timezone
- **Status Check**: `curl ifconfig.me` (should show Manila IP)

### System Specifications
- **OS**: Ubuntu Linux
- **Timezone**: Manila (UTC+8) - System level
- **Trading Timezone**: America/New_York - Service level
- **Python**: 3.11+ with virtual environments

### Network Requirements
- **Stable connection**: <50ms latency to IBKR
- **Bandwidth**: Minimum 10Mbps for L2 data
- **Ports**: 5000 (Client Portal), 8000 (Platform), 7497 (Legacy)

---

## 2. IBKR API Platform (Core Infrastructure)

### Platform Service - **PRODUCTION READY**
- **Service**: `ibkr-platform.service` ✅ **RUNNING**
- **Port**: 8000 (HTTP REST API)
- **Backend**: Client Portal Gateway (port 5000)
- **Purpose**: Centralized IBKR connection management
- **Status**: **Migration complete** - All services connected

### API Endpoints Available
**Service Management:**
- `POST /services/register` - Register service with platform
- `POST /services/{id}/heartbeat` - Service heartbeat
- `GET /health` - Platform health and authentication status

**IBKR Operations:**
- `GET /api/accounts` - Get IBKR accounts
- `POST /api/market-data/snapshot` - Market data snapshots
- `GET /api/market-data/historical` - Historical data
- `POST /api/orders/place` - Place orders
- `GET /api/positions/{account}` - Get positions
- `GET /api/portfolio/{account}` - Portfolio summary

### Client Portal Gateway
- **Location**: `/home/jacobw/quantstack/cpapi/gateway/`
- **Port**: 5000 (HTTPS)
- **Authentication**: Browser login required (IBKR credentials + 2FA)
- **Session**: ~24 hours, resets at midnight
- **Status**: **Authenticated and stable**

### Daily Startup Sequence
1. **Start Client Portal Gateway**:
   ```bash
   cd /home/jacobw/quantstack/cpapi/gateway
   bin/run.sh root/conf.yaml
   ```

2. **Browser Authentication**:
   ```bash
   firefox https://localhost:5000
   # Login with IBKR credentials + 2FA
   ```

3. **Verify Platform**:
   ```bash
   curl http://127.0.0.1:8000/health | jq .authenticated
   # Should return: true
   ```

### Platform Management
```bash
# Service control
systemctl status ibkr-platform.service
systemctl restart ibkr-platform.service

# Health check
curl -s http://127.0.0.1:8000/health | jq .

# View registered services
curl -s http://127.0.0.1:8000/health | jq .services
```

---

## 3. Trading Services - **ALL MIGRATED TO PLATFORM**

### L2 Data Collector ✅ **MIGRATED**
- **Service**: `l2-collector.service`
- **Purpose**: NYSE Level 2 market depth collection
- **Client**: Uses `IBKRPlatformClient` (no more socket connections)
- **Data**: Order book snapshots, depth analysis
- **Storage**: `/home/jacobw/quantstack/data/l2_maximum/`
- **Status**: **Production ready** with platform integration

```bash
# Service control
systemctl status l2-collector.service
systemctl restart l2-collector.service

# View logs
journalctl -u l2-collector.service -f

# Check platform registration
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector
```

### L2 Scalping System ✅ **MIGRATED**
- **Service**: `l2-scalping.service`
- **Purpose**: High-frequency scalping based on L2 signals
- **Client**: Uses `IBKRPlatformClient` for orders and market data
- **Strategy**: Order book imbalance, microstructure patterns
- **Risk**: Max 1% per position, 100 shares cap
- **Status**: **Production ready** with enhanced reliability

```bash
# Service control
systemctl status l2-scalping.service
systemctl restart l2-scalping.service

# View trading logs
tail -f /home/jacobw/quantstack/l2_scalping/logs/scalping_system.log

# Check positions via platform
curl -s http://127.0.0.1:8000/api/positions/DUN575068 | jq .
```

### Intraday Paper Trading ✅ **MIGRATED**
- **Service**: `intraday-paper.service`
- **Purpose**: ML-based intraday trading strategies
- **Client**: Uses `IBKRPlatformClient` for paper trading
- **Mode**: Paper trading (IBKR paper account)
- **Universe**: Daily SIP-selected symbols
- **Status**: **Production ready** with platform integration

```bash
# Service control
systemctl status intraday-paper.service
systemctl restart intraday-paper.service

# View paper trades
tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log

# Check portfolio via platform
curl -s http://127.0.0.1:8000/api/portfolio/DUN575068 | jq .
```

### L2 Watchdog ✅ **ENHANCED**
- **Service**: `l2-watchdog.service`
- **Purpose**: Monitor all services and platform health
- **Enhancement**: Now includes recovery detection and platform monitoring
- **Notifications**: NTFY alerts for failures and recoveries
- **Status**: **Enhanced** with platform awareness

---

## 4. Automated Scheduling (NY Market Hours)

### Timer Schedule
| Service | Manila Time | NY Time | Purpose |
|---------|-------------|---------|---------|
| **preflight-check** | 20:00 | 07:00 AM | Pre-market validation |
| **trading-orchestrator** | 21:00 | 08:00 AM | System monitoring |
| **intraday-sip** | 22:10 | 09:10 AM | Daily universe selection |
| **intraday-paper** | 22:27 | 09:27 AM | Paper trading start |
| **system-health-monitor** | Every 5min | Every 5min | Health checks |

### Timer Management
```bash
# View all timers
systemctl list-timers | grep -E "(trading|l2|intraday|preflight|health)"

# Check specific timer
systemctl status intraday-sip.timer

# Manual trigger
systemctl start intraday-sip.service
```

### Daily SIP Generation
- **Service**: `intraday-sip.service`
- **Time**: 09:10 AM ET (20 minutes before market open)
- **Purpose**: Select daily trading universe from 1,700+ symbols
- **Output**: `/home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/`

---

## 5. Monitoring & Alerting

### Health Monitoring
- **Service**: `system-health-monitor.service`
- **Frequency**: Every 5 minutes during market hours
- **Scope**: Service status, platform health, authentication

### L2 Watchdog
- **Service**: `l2-watchdog.service`
- **Purpose**: Monitor L2 collector health and auto-recovery
- **Actions**: Service restart, connection recovery

### NTFY Notifications ✅ **ENHANCED**
- **Channels**:
  - `jacobw-trading-alerts` - Errors and failures (enhanced with recovery detection)
  - `jacobw-trading-status` - System status updates (platform health included)
  - `jacobw-trading-trades` - **NEW**: Trade executions with P&L details

**Trading Notifications Include:**
- **Entry**: Symbol, direction, price, quantity, system
- **Exit**: Symbol, P&L, exit reason (TARGET/STOP/EXIT), system
- **Recovery**: Service recovery detection and alerts

```bash
# Test notifications
curl -d "Platform migration complete - System test from $(hostname)" ntfy.sh/jacobw-trading-alerts

# Subscribe on phone
# https://ntfy.sh/jacobw-trading-alerts
# https://ntfy.sh/jacobw-trading-status  
# https://ntfy.sh/jacobw-trading-trades
```

### Log Locations
```bash
# Platform logs
journalctl -u ibkr-platform.service -f

# Service logs
journalctl -u l2-collector.service -f
journalctl -u l2-scalping.service -f
journalctl -u intraday-paper.service -f

# Application logs
tail -f /home/jacobw/quantstack/l2_scalping/logs/scalping_system.log
tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log
```

---

## 6. Daily Operations

### Pre-Market Checklist (07:00 AM ET) ✅ **AUTOMATED**
1. **VPN Status**: Verify Manila connection
2. **Gateway Authentication**: Check browser login status  
3. **Platform Health**: Verify API platform running and authenticated
4. **Service Registration**: Confirm all services registered with platform
5. **SIP Generation**: Confirm universe selection completed (09:10 AM ET)

```bash
# Quick system check (UPDATED for platform)
curl -s http://127.0.0.1:8000/health | jq .
systemctl status ibkr-platform l2-collector l2-scalping intraday-paper l2-watchdog

# Check service registration
curl -s http://127.0.0.1:8000/health | jq .services

# Verify authentication
curl -s http://127.0.0.1:8000/health | jq .authenticated
```

### Market Hours Monitoring (09:30 AM - 04:00 PM ET) ✅ **ENHANCED**
- **Platform**: Monitor authentication status and service health
- **Services**: All services now report to centralized platform
- **Trades**: Monitor execution via NTFY notifications with P&L
- **Data**: Verify L2 collection active via platform endpoints
- **Recovery**: Automatic detection and alerts for service recovery

### Post-Market Review (After 04:00 PM ET) ✅ **IMPROVED**
- **Performance**: Review trade journal with system attribution
- **Data Quality**: Check L2 collection statistics via platform
- **Logs**: Review platform and service logs for issues
- **Platform Status**: Verify platform ready for next day
- **Preparation**: All services auto-register on startup

---

## 7. Troubleshooting ✅ **PLATFORM-ENHANCED**

### Platform Issues

**Problem**: Platform not authenticated
```bash
# Check gateway status
curl -k -s https://localhost:5000/v1/api/iserver/auth/status

# Check platform authentication
curl -s http://127.0.0.1:8000/health | jq .authenticated

# If false, re-login via browser
firefox https://localhost:5000

# Restart platform after authentication
systemctl restart ibkr-platform.service
```

**Problem**: Services can't connect to platform
```bash
# Check platform health and registered services
curl -s http://127.0.0.1:8000/health | jq .

# Check service logs for connection errors
journalctl -u l2-collector.service -n 20

# Restart problematic service (will auto-register)
systemctl restart l2-collector.service

# Verify service registered
curl -s http://127.0.0.1:8000/health | jq .services
```

### Service Failures ✅ **IMPROVED DIAGNOSTICS**

**Problem**: L2 collector stopped
```bash
# Check service status
systemctl status l2-collector.service

# Check platform registration
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector

# View recent logs
journalctl -u l2-collector.service -n 50

# Restart service (auto-registers with platform)
systemctl restart l2-collector.service
```

**Problem**: No trades executing
```bash
# Check platform authentication
curl -s http://127.0.0.1:8000/api/auth/status

# Check account status via platform
curl -s http://127.0.0.1:8000/api/accounts

# Check service registration
curl -s http://127.0.0.1:8000/health | jq .services

# Check service logs
journalctl -u l2-scalping.service -f
journalctl -u intraday-paper.service -f
```

### Data Issues ✅ **PLATFORM-INTEGRATED**

**Problem**: No L2 data collection
```bash
# Check L2 collector service and platform registration
systemctl status l2-collector.service
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector

# Check data directory
ls -la /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F)/

# Test platform market data access
curl -s http://127.0.0.1:8000/api/market-data/snapshot \
  -H "Content-Type: application/json" \
  -d '{"conids": [265598]}'

# Check service heartbeat
curl -s http://127.0.0.1:8000/health | jq '.services.l2_collector.last_heartbeat'
```

---

## 8. Emergency Procedures ✅ **PLATFORM-OPTIMIZED**

### System Failure Recovery
1. **Check VPN**: Ensure Manila connection active
2. **Restart Gateway**: Kill and restart Client Portal Gateway
3. **Re-authenticate**: Browser login to https://localhost:5000
4. **Restart Platform**: `systemctl restart ibkr-platform.service`
5. **Verify Platform**: `curl -s http://127.0.0.1:8000/health | jq .authenticated`
6. **Restart Services**: All services will auto-register with platform
7. **Verify Registration**: `curl -s http://127.0.0.1:8000/health | jq .services`

### Position Management ✅ **PLATFORM-INTEGRATED**
```bash
# Check current positions via platform
curl -s http://127.0.0.1:8000/api/positions/DUN575068 | jq .

# Check open orders via platform
curl -s http://127.0.0.1:8000/api/orders | jq .

# Check portfolio summary
curl -s http://127.0.0.1:8000/api/portfolio/DUN575068 | jq .

# Emergency position close (if needed)
# Use platform endpoints or manual intervention through IBKR Client Portal
```

### Data Recovery ✅ **ENHANCED**
```bash
# Check recent data
ls -la /home/jacobw/quantstack/data/l2_maximum/features/

# Check platform service registration
curl -s http://127.0.0.1:8000/health | jq .services

# Restart data collection (auto-registers)
systemctl restart l2-collector.service

# Verify collection resumed and registered
tail -f /home/jacobw/quantstack/logs/l2_collector.log
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector
```

---

## 9. Performance Monitoring

### Key Metrics
- **Platform Uptime**: >99.5% during market hours
- **Authentication**: Stable 24-hour sessions
- **L2 Data**: >95% capture rate
- **Trade Execution**: <500ms average latency
- **Service Health**: All services running

### Daily Reports
```bash
# System health summary
curl -s http://127.0.0.1:8000/health | jq .

# L2 collection stats
ls -la /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F)/ | wc -l

# Trading performance
# (Custom reporting scripts as needed)
```

---

## 10. Maintenance

### Weekly Tasks
- **Log Rotation**: Clean old log files
- **Data Cleanup**: Archive old L2 data
- **System Updates**: Apply security patches (off-hours)
- **Performance Review**: Analyze system metrics

### Monthly Tasks
- **Strategy Review**: Analyze trading performance
- **System Optimization**: Review and optimize configurations
- **Backup Verification**: Ensure data backups working
- **Documentation Updates**: Update procedures as needed

---

## Quick Reference

### Essential Commands ✅ **PLATFORM-UPDATED**
```bash
# System status (all migrated services)
systemctl status ibkr-platform l2-collector l2-scalping intraday-paper l2-watchdog

# Platform health and service registration
curl -s http://127.0.0.1:8000/health | jq .

# Check authenticated status
curl -s http://127.0.0.1:8000/health | jq .authenticated

# View registered services
curl -s http://127.0.0.1:8000/health | jq .services

# Service logs
journalctl -u ibkr-platform.service -f

# Emergency restart (services auto-register)
systemctl restart ibkr-platform.service
systemctl restart l2-collector.service
systemctl restart l2-scalping.service
systemctl restart intraday-paper.service
```

### Key Files ✅ **UPDATED**
- **Platform**: `/home/jacobw/quantstack/cpapi/` (platform.py, platform_client.py)
- **Archived Legacy**: `/home/jacobw/quantstack/archive/socket_based_ibkr/` (18 files)
- **L2 Data**: `/home/jacobw/quantstack/data/l2_maximum/`
- **Logs**: `/var/log/journal/` (systemd) + application logs
- **Config**: `/etc/systemd/system/` (services)
- **Trading Notifications**: `/home/jacobw/quantstack/cpapi/trading_notifications.py`

### Support Contacts
- **IBKR Support**: For account/connection issues
- **VPN Provider**: For connectivity issues
- **System Admin**: For infrastructure issues

---

**Last Updated**: 2026-01-13  
**Next Review**: 2026-02-13
