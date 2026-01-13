# Quantstack Documentation

**Production Trading System Documentation**  
**✅ IBKR Platform Migration Complete (2026-01-13)**

## Current Documentation

### 📋 **Primary Guides**
- **[Complete System Guide](COMPLETE_SYSTEM_GUIDE.md)** - **START HERE** - Full system operations manual (UPDATED)
- **[IBKR API Connection Protocol](IBKR_API_CONNECTION_PROTOCOL.md)** - Platform-based architecture and service integration
- **[L2 Scalping System Design](L2_SCALPING_SYSTEM_DESIGN.md)** - L2 scalping implementation details
- **[Timezone Guide](TIMEZONE_GUIDE.md)** - Critical timezone configuration (Manila vs NY)
- **[Performance Report](PERFORMANCE_REPORT_2026-01-10.md)** - System performance analysis

## Migration Status ✅ **COMPLETE**

**All services successfully migrated from socket-based ib_insync to REST-based IBKR API Platform:**
- ✅ **l2-collector** - Market data via platform client
- ✅ **l2-scalping** - Orders and data via platform client  
- ✅ **intraday-paper** - Paper trading via platform client
- ✅ **l2-watchdog** - Enhanced monitoring with recovery detection
- 📁 **Legacy code archived** - 18 socket-based files moved to archive/

## Quick Start

```bash
# Check system status (all migrated services)
curl -s http://127.0.0.1:8000/health | jq .
systemctl status ibkr-platform l2-collector l2-scalping intraday-paper l2-watchdog

# View platform logs
journalctl -u ibkr-platform.service -f

# Check service registration
curl -s http://127.0.0.1:8000/health | jq .services

# Emergency restart (services auto-register)
systemctl restart ibkr-platform.service
```

## System Architecture

```
VPN (Manila) → IBKR API Platform (8000) → Client Portal Gateway (5000) → IBKR
                      ↓
    L2 Collector + L2 Scalping + Intraday Paper + Monitoring
```

## Key Services

| Service | Purpose | Status Command |
|---------|---------|----------------|
| `ibkr-platform` | Centralized IBKR API | `systemctl status ibkr-platform` |
| `l2-collector` | L2 market data | `systemctl status l2-collector` |
| `l2-scalping` | High-frequency trading | `systemctl status l2-scalping` |
| `intraday-paper` | Paper trading | `systemctl status intraday-paper` |
| `l2-watchdog` | Health monitoring | `systemctl status l2-watchdog` |

## Emergency Contacts

- **Platform Issues**: Check `COMPLETE_SYSTEM_GUIDE.md` troubleshooting section
- **IBKR Connection**: Verify authentication at https://localhost:5000
- **Service Failures**: Check logs with `journalctl -u <service-name> -f`

## Archive

Historical and legacy documentation moved to `archive/legacy_docs/`

---

**Last Updated**: 2026-01-13  
**System Version**: 2.0 (Platform-Based Architecture)
