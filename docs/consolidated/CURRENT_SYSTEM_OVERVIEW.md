# QUANTSTACK TRADING SYSTEM - CURRENT SYSTEM OVERVIEW

**Version**: 2026-01-10  
**Status**: Production Ready with Critical Fixes Applied

## Executive Summary

The QuantStack trading system is a multi-component automated trading platform running 8 systemd services across two main directories (`/home/jacobw/quantstack` and `/home/jacobw/intraday_stack`). The system executes L2 scalping and intraday paper trading strategies with comprehensive risk controls, including emergency EOD position flattening.

## System Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    QUANTSTACK TRADING SYSTEM                     │
├─────────────────────────────────────────────────────────────────┤
│  8 Systemd Services | 2 Trading Systems | 1 IBKR Gateway       │
└─────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
/home/jacobw/quantstack/          # L2 Scalping & Orchestration
├── l2_scalping/                  # L2 scalping system
├── qx-l2/                        # L2 data collection
├── scripts/                      # Orchestration & monitoring
└── docs/                         # Documentation

/home/jacobw/intraday_stack/      # Intraday Paper Trading
├── src/                          # Core trading modules
├── scripts/                      # Trading execution
└── data/                         # Trade journal & SIP data
```

## Systemd Services Overview

| Service | Location | Purpose | Schedule | Status |
|---------|----------|---------|----------|--------|
| **trading-orchestrator** | quantstack | SIP generation & monitoring | 21:00 Manila | ✅ Active |
| **preflight-check** | quantstack | Pre-market validation | 20:00 Manila | ✅ Active |
| **l2-collector** | quantstack | L2 data collection | 22:25 Manila | ✅ Active |
| **l2-scalping** | quantstack | L2-based trading | 22:25 Manila | ✅ Active |
| **l2-watchdog** | quantstack | L2 system monitoring | Continuous | ✅ Active |
| **intraday-paper** | intraday_stack | Paper trading | 22:25 Manila | ✅ Active |
| **intraday-sip** | intraday_stack | SIP refresh | 21:45 Manila | ✅ Active |
| **emergency-eod-close** | quantstack | Emergency position closer | 20:55 Manila | ✅ Active |

## Trading Systems

### L2 Scalping System
- **Location**: `/home/jacobw/quantstack/l2_scalping/`
- **Strategy**: Microstructure-based scalping
- **Client IDs**: 10, 11 (IBKR Gateway)
- **Performance**: 80% win rate, $71.34 avg P&L per trade
- **Hold Time**: 0-5 minutes (ultra-fast)

### Intraday Paper Trading
- **Location**: `/home/jacobw/intraday_stack/`
- **Strategy**: Reversal-based trading
- **Client ID**: 15 (IBKR Gateway)
- **Performance**: 36.4% win rate, $15.24 avg P&L per trade
- **Hold Time**: 5+ minutes

## Data Flow

```
External Sources → Collection → Processing → Execution → Journal
     ↓               ↓           ↓           ↓          ↓
IBKR Gateway    L2 Collector  Signal Gen   Orders    SQLite DB
Polygon API     SIP Generator  Ranking     Fills     Trade Reports
Gold Data       Price Feeds    Risk Mgmt   P&L       NTFY Alerts
```

## Risk Controls

### Position Management
- **EOD Flatten**: Automatic at 3:45 PM ET
- **Emergency Backup**: Force close at 3:55 PM ET (Gateway-independent)
- **Position Sync**: Every 5 minutes during market hours
- **Bracket Orders**: Stop/target for each entry

### Data Validation
- **Stale Price Detection**: Warns on identical prices
- **Live Price Validation**: Tracks price history per symbol
- **Connection Monitoring**: Auto-reconnect on IBKR disconnect

### System Monitoring
- **Health Monitor**: Every 5 minutes during market hours
- **Service Watchdog**: Auto-restart failed services
- **NTFY Alerts**: Real-time notifications on failures

## Database Schema

### Trade Journal (`/home/jacobw/intraday_stack/data/journal/events.db`)

**Tables**:
- `trades` - Complete trade lifecycle with P&L
- `fills` - Order execution details
- `orders` - Order submissions
- `decisions` - Trading decisions
- `risk_events` - Risk violations

**Key Fields**:
- System attribution (`system`, `strategy`)
- Complete P&L tracking (`gross_pnl`, `net_pnl`, `commission`)
- Execution quality (`entry_slippage`, `exit_slippage`)
- Hold time and performance metrics

## Configuration Files

### Systemd Services
```
/etc/systemd/system/
├── trading-orchestrator.{service,timer}
├── preflight-check.{service,timer}
├── l2-collector.{service,timer}
├── l2-scalping.service
├── l2-watchdog.service
├── intraday-paper.{service,timer}
├── intraday-sip.{service,timer}
└── emergency-eod-close.{service,timer}
```

### Application Configs
```
/home/jacobw/quantstack/
├── l2_scalping/config/
│   ├── strategy.yaml
│   └── risk.yaml
└── qx-l2/configs/maximum_l2.yaml

/home/jacobw/intraday_stack/configs/
└── paper_trading.yaml
```

## IBKR Gateway Integration

### Connection Details
- **Host**: 127.0.0.1:7497
- **Client IDs**: 
  - 1-99: qx-l2 (L2 collection)
  - 10,11: l2-scalping
  - 15: intraday-paper
  - 521: l2-collector
  - 998: preflight-check
  - 999: emergency scripts

### API Settings Required
- **TWS**: Enable API, port 7497
- **Gateway**: Enable API, port 7497
- **Both systems** need API configuration

## Daily Schedule (Manila Time)

| Time | Service | Action |
|------|---------|--------|
| 20:00 | preflight-check | Pre-market validation |
| 21:00 | trading-orchestrator | Generate SIP universe |
| 21:45 | intraday-sip | Refresh SIP mid-day |
| 22:25 | l2-collector, intraday-paper | Start trading |
| 22:30 | Market Open | Trading begins |
| 03:45 | Primary EOD | Flatten positions via IBKR |
| 03:55 | Emergency EOD | Force close any remaining |
| 05:00 | Market Close | Trading ends |

## Performance Metrics (Jan 9, 2026)

### Overall Performance
- **Total Trades**: 18
- **Total Net P&L**: $524.39
- **Win Rate**: 50% (8W/8L)
- **Total Fees**: $32.00

### By System
- **L2-Scalping**: 5 trades, $356.71 P&L (68% of profits)
- **Intraday-Paper**: 11 trades, $167.68 P&L (32% of profits)

## Monitoring & Alerts

### NTFY Channels
- `jacobw-trading-status`: System status updates
- `jacobw-trading-alerts`: Errors and failures
- `jacobw-trading-trades`: Trade executions with P&L

### Log Locations
```
/home/jacobw/quantstack/logs/
├── orchestrator.log
├── orchestrator_audit.log
└── emergency_eod.log

/home/jacobw/intraday_stack/logs/
└── paper_YYYYMMDD.log

# Systemd logs
journalctl -u <service-name>
```

### Key Commands
```bash
# Check all services
systemctl status l2-collector l2-scalping intraday-paper

# Generate trade report
python3 /home/jacobw/quantstack/scripts/trading_report.py --date $(date +%F)

# View SIP universe
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq

# Emergency position check
python3 /home/jacobw/quantstack/scripts/emergency_eod_close.py
```

## System Status: ✅ PRODUCTION READY

**Last Updated**: 2026-01-10  
**Critical Fixes Applied**: EOD flattening, stale price detection, emergency backup  
**Open Issues**: None  
**Next Review**: After first live trading session with new fixes

---

*For detailed technical documentation, see:*
- *[Development History](DEVELOPMENT_HISTORY.md)*
- *[User Guide](USER_GUIDE.md)*
- *[IBKR Gateway Protocol](IBKR_GATEWAY_PROTOCOL.md)*
- *[Emergency Procedures](EMERGENCY_PROCEDURES.md)*
