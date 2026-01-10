# QUANTSTACK TRADING SYSTEM - DOCUMENTATION INDEX

**Version**: 2026-01-10  
**Status**: Consolidated and Current

## Primary Documentation

### 📋 [CURRENT SYSTEM OVERVIEW](CURRENT_SYSTEM_OVERVIEW.md)
**Essential reading for system operators**
- Executive summary of the complete trading system
- 8 systemd services across 2 directories
- Performance metrics and system status
- Daily schedule and monitoring commands

### 📚 [USER GUIDE](USER_GUIDE.md)
**Daily operations manual**
- Quick start procedures
- Service management commands
- Trading operations workflow
- Troubleshooting guide
- Maintenance procedures

### 🔧 [DEVELOPMENT HISTORY](DEVELOPMENT_HISTORY.md)
**Technical evolution and lessons learned**
- Development phases (Oct 2025 - Jan 2026)
- Critical fixes and improvements
- Architecture evolution
- Performance improvements
- Technical debt resolution

### 🔌 [IBKR GATEWAY PROTOCOL](IBKR_GATEWAY_PROTOCOL.md)
**Critical connection management**
- Client ID allocation and management
- Connection lifecycle procedures
- Error handling and recovery
- Zombie connection prevention
- Best practices and troubleshooting

### 🚨 [EMERGENCY PROCEDURES](EMERGENCY_PROCEDURES.md)
**Crisis management and recovery**
- Emergency scenarios and responses
- Position management procedures
- System recovery checklists
- Contact information and escalation
- Prevention measures

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    QUANTSTACK TRADING SYSTEM                     │
├─────────────────────────────────────────────────────────────────┤
│  Directory Structure:                                           │
│                                                                 │
│  /home/jacobw/quantstack/          # L2 Scalping & Orchestration│
│  ├── l2_scalping/                  # L2 scalping system        │
│  ├── qx-l2/                        # L2 data collection        │
│  ├── scripts/                      # Orchestration & monitoring│
│  └── docs/consolidated/            # THIS DOCUMENTATION        │
│                                                                 │
│  /home/jacobw/intraday_stack/      # Intraday Paper Trading    │
│  ├── src/                          # Core trading modules      │
│  ├── scripts/                      # Trading execution         │
│  └── data/                         # Trade journal & SIP data  │
└─────────────────────────────────────────────────────────────────┘
```

## Service Overview

| Service | Purpose | Schedule | Documentation |
|---------|---------|----------|---------------|
| **trading-orchestrator** | SIP generation & monitoring | 21:00 Manila | [USER_GUIDE.md](USER_GUIDE.md#trading-orchestrator) |
| **preflight-check** | Pre-market validation | 20:00 Manila | [USER_GUIDE.md](USER_GUIDE.md#preflight-check) |
| **l2-collector** | L2 data collection | 22:25 Manila | [USER_GUIDE.md](USER_GUIDE.md#l2-collector) |
| **l2-scalping** | L2-based trading | 22:25 Manila | [USER_GUIDE.md](USER_GUIDE.md#l2-scalping) |
| **l2-watchdog** | L2 system monitoring | Continuous | [USER_GUIDE.md](USER_GUIDE.md#l2-watchdog) |
| **intraday-paper** | Paper trading | 22:25 Manila | [USER_GUIDE.md](USER_GUIDE.md#intraday-paper-trading) |
| **intraday-sip** | SIP refresh | 21:45 Manila | [USER_GUIDE.md](USER_GUIDE.md#support-services) |
| **emergency-eod-close** | Emergency position closer | 20:55 Manila | [EMERGENCY_PROCEDURES.md](EMERGENCY_PROCEDURES.md#1-positions-stuck-open-at-eod) |

## Quick Reference

### Daily Operations
```bash
# Check system status
systemctl status l2-collector l2-scalping intraday-paper

# View today's trades
python3 /home/jacobw/quantstack/scripts/trading_report.py --date $(date +%F)

# Monitor real-time activity
journalctl -u intraday-paper -f
```

### Emergency Commands
```bash
# Stop all trading
sudo systemctl stop l2-scalping intraday-paper

# Force close positions
python3 /home/jacobw/quantstack/close_open_positions.py

# Check IBKR connectivity
python3 /home/jacobw/quantstack/scripts/check_portal_status.py
```

### Key Locations
```bash
# Trade database
/home/jacobw/intraday_stack/data/journal/events.db

# SIP universe
/home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json

# System logs
journalctl -u <service-name>

# Configuration files
/home/jacobw/quantstack/l2_scalping/config/
/etc/systemd/system/*trading*
```

## Documentation Standards

### File Organization
- **consolidated/**: Current, authoritative documentation
- **archive/**: Historical and superseded documents
- **README.md**: This index file

### Update Process
1. Update relevant consolidated document
2. Archive superseded documents
3. Update this index
4. Test all procedures

### Version Control
- All documentation versioned with system
- Major changes documented in DEVELOPMENT_HISTORY.md
- Emergency procedures tested monthly

## Support Information

### NTFY Channels
- **Alerts**: https://ntfy.sh/jacobw-trading-alerts
- **Trades**: https://ntfy.sh/jacobw-trading-trades
- **Status**: https://ntfy.sh/jacobw-trading-status

### Log Locations
```bash
# Application logs
/home/jacobw/quantstack/logs/
/home/jacobw/intraday_stack/logs/

# System logs
journalctl -u <service-name>

# Emergency logs
/home/jacobw/quantstack/logs/emergency_eod.log
```

### Key Scripts
```bash
# System health
/home/jacobw/quantstack/scripts/definitive_e2e_test.py

# Trading reports
/home/jacobw/quantstack/scripts/trading_report.py
/home/jacobw/quantstack/full_trading_report.py

# Emergency tools
/home/jacobw/quantstack/close_open_positions.py
/home/jacobw/quantstack/scripts/emergency_eod_close.py
```

## System Status

### Current Version: 2026-01-10
- ✅ **Production Ready**: All critical fixes applied
- ✅ **Risk Controls**: Dual-layer EOD protection
- ✅ **Monitoring**: Comprehensive health checks
- ✅ **Documentation**: Complete and current

### Recent Updates
- **2026-01-10**: Critical trading system fixes
- **2026-01-09**: IBKR Gateway connection protocol
- **2026-01-09**: Emergency EOD backup system
- **2026-01-09**: Database schema improvements

### Next Review
- **Weekly**: Emergency procedure validation
- **Monthly**: Performance review and optimization
- **Quarterly**: Full system architecture review

---

## Getting Started

**New Users**: Start with [CURRENT_SYSTEM_OVERVIEW.md](CURRENT_SYSTEM_OVERVIEW.md)  
**Daily Operations**: Use [USER_GUIDE.md](USER_GUIDE.md)  
**Emergencies**: Reference [EMERGENCY_PROCEDURES.md](EMERGENCY_PROCEDURES.md)  
**Technical Details**: See [DEVELOPMENT_HISTORY.md](DEVELOPMENT_HISTORY.md)  
**IBKR Issues**: Follow [IBKR_GATEWAY_PROTOCOL.md](IBKR_GATEWAY_PROTOCOL.md)

---

*This documentation library provides complete coverage of the QuantStack trading system. All documents are current as of 2026-01-10.*
