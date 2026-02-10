# quantstack

Production trading system with L2 scalping, L2 VWAP reversion, intraday paper trading, and SIP-based universe selection.

## Active Systems

| System | Service | Purpose | Schedule (ET) |
|--------|---------|---------|---------------|
| **L2 Scalping** | `l2-scalping.service` | L2 scalping + data collection | 09:26-17:01 |
| **L2 VWAP Reversion** | `l2-vwap-reversion.service` | VWAP mean reversion with L2 filter | 09:26-16:05 |
| **Intraday Paper** | `intraday-paper.service` | Paper trading with bracket orders | 09:27-17:02 |
| **SIP Generation** | `intraday-sip.timer` | Daily universe selection | 09:10 |
| **Emergency EOD** | `emergency-eod-close.timer` | Force close positions | 15:55 |
| **Preflight Check** | `preflight-check.timer` | Pre-market validation | 07:00 |

**Note**: L2 Collector is disabled - L2 Scalping now handles data collection.

## Quick Commands

```bash
# Check all services
systemctl status l2-scalping l2-vwap-reversion intraday-paper

# View trading logs
journalctl -u l2-scalping -f
journalctl -u l2-vwap-reversion -f
journalctl -u intraday-paper -f

# End-of-day performance report (unified)
python scripts/eod_report.py --date $(date +%F)

# Export to CSV
python scripts/eod_report.py --date $(date +%F) --csv report.csv

# Clear zombie depth subscriptions (before restart)
python scripts/clear_ibkr_depth_subscriptions.py

# Restart services after outage
sudo systemctl restart l2-scalping l2-vwap-reversion intraday-paper
```

## Architecture

```
quantstack/
├── l2_scalping/          # L2 scalping system (OBI momentum + pattern rules)
├── cpapi/                # IBKR Client Portal API integration
├── qx-*/                 # Core framework packages
│   ├── qx-core/          # Schemas, contracts, validators
│   ├── qx-broker/        # IBKR connection management
│   ├── qx-data/          # Data loading and normalization
│   ├── qx-features/      # Feature engineering
│   ├── qx-screener/      # Universe selection (SIP)
│   ├── qx-backtest/      # Backtesting engine
│   ├── qx-risk/          # Risk management
│   └── qx-l2/            # L2 data collection
├── sip_pattern_discovery/ # Pattern discovery system
├── scripts/              # Operational scripts
├── systemd/              # Service definitions
├── configs/              # Configuration files
└── docs/                 # Documentation
```

## IBKR Connection

Services connect via IB Gateway on port 7494:
- **L2 Scalping**: Client IDs 200 (orders), 250 (data)
- **Intraday Paper**: Client ID 111
- **L2 VWAP Reversion**: Client IDs 300 (orders), 350 (data)
- **Position Monitor**: Client ID 998

Gateway must be authenticated before market open. See `docs/IBKR_IB_INSYNC_CONNECTION_PROTOCOL.md`.

## Data Locations

| Data | Path |
|------|------|
| Trade Journal | `/home/jacobw/intraday_stack/data/journal/events.db` |
| SIP Universe | `/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/` |
| L2 Features | `/home/jacobw/quantstack/data/l2_maximum/features/` |
| Logs | `/home/jacobw/quantstack/logs/` |

## Key Documentation

- [Complete System Guide](docs/SYSTEM_GUIDE.md) - **START HERE**
- [Documentation Index](docs/INDEX.md) - All documentation organized by topic
- [L2 Scalping Design](docs/L2_SCALPING_SYSTEM_DESIGN.md)
- [IBKR Connection Protocol](docs/IBKR_IB_INSYNC_CONNECTION_PROTOCOL.md)
- [Post-Outage Recovery](docs/POST_OUTAGE_RECOVERY.md)
- [Timezone Guide](docs/TIMEZONE_GUIDE.md)

### Recent Fixes (Jan 24, 2026)
- **L2-Scalping**: Fixed bracket order price precision (Error 110) - added `round_to_tick_size()` utility
- **Intraday-Paper**: Fixed timestamp parsing + signal age validation - now accepts same-day signals
- [IOC Fill Simulation](docs/IOC_FILL_SIMULATION_RESULTS.md) - L2-Scalping order analysis (85.9% fill rate)
- [Intraday-Paper Audit](docs/INTRADAY_PAPER_FORENSIC_AUDIT.md) - Complete forensic audit report

## Timezone Reference

- **System**: Manila (UTC+8)
- **Trading Services**: America/New_York (ET)
- **Market Hours in Manila**: 22:30 PM → 05:00 AM next day

## Emergency Procedures

See [Post-Outage Recovery Runbook](docs/POST_OUTAGE_RECOVERY.md) for:
- Gateway crash recovery
- Service restart procedures
- Position sync issues
- Zombie subscription cleanup
