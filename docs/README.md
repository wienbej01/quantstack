# Quantstack Documentation

**Production Trading System Documentation**  
**✅ IBKR Gateway + ib_insync (Systemd Timers + Manual Portal Auth)**

## Current Documentation

### 📋 **Primary Guides**
- **[Complete System Guide](COMPLETE_SYSTEM_GUIDE.md)** - **START HERE** - Full operations manual
- **[IBKR ib_insync Connection Protocol](IBKR_IB_INSYNC_CONNECTION_PROTOCOL.md)** -
  Gateway, client ID, runbook
- **[L2 Scalping System Design](L2_SCALPING_SYSTEM_DESIGN.md)** - L2 scalping implementation details
- **[Timezone Guide](TIMEZONE_GUIDE.md)** - Critical timezone configuration (Manila vs NY)
- **[Performance Report](PERFORMANCE_REPORT_2026-01-10.md)** - System performance analysis

## Migration Status ✅ **COMPLETE**

**All services now run on the direct IBKR Gateway via `qx_broker` (ib_insync):**
- ✅ **l2-collector** - L2 depth capture + journaling
- ✅ **l2-scalping** - L2 signals + trading
- ✅ **intraday-paper** - Paper trading (SIP-driven)
- ✅ **l2-watchdog** - Collector monitoring + recovery
- ✅ **system-health-monitor** - Gateway + service checks with NTFY

## Quick Start

```bash
# Confirm gateway is up (manual portal auth)
ss -ltn | rg ":7494"

# Manual start (debug only)
bash /home/jacobw/quantstack/scripts/start_new_platform_manual.sh

# Check timers
systemctl list-timers --all --no-pager | rg -n \
  "intraday-sip|preflight|l2-collector|l2-scalping|intraday-paper|system-health"

# Check services
systemctl status l2-collector l2-scalping intraday-paper l2-watchdog position-monitor --no-pager
```

## System Architecture

```
IBKR Gateway/Portal (manual auth) → qx_broker (ib_insync) → Services
  ├─ L2 Collector
  ├─ L2 Scalping
  ├─ Intraday Paper
  └─ Monitoring + Reporting
```

## Key Services

| Service | Purpose | Status Command |
|---------|---------|----------------|
| `l2-collector` | L2 market data | `systemctl status l2-collector` |
| `l2-scalping` | High-frequency trading | `systemctl status l2-scalping` |
| `intraday-paper` | Paper trading | `systemctl status intraday-paper` |
| `l2-watchdog` | Health monitoring | `systemctl status l2-watchdog` |
| `system-health-monitor` | Gateway/service checks | `systemctl status system-health-monitor` |
| `daily-trade-report` | EOD reports | `systemctl status daily-trade-report` |

## Emergency Contacts

- **Platform Issues**: Check `COMPLETE_SYSTEM_GUIDE.md` troubleshooting section
- **IBKR Connection**: Verify Gateway/Portal UI is authenticated and port 7494 is open
- **Service Failures**: Check logs with `journalctl -u <service-name> -f`

## Archive

Historical and legacy documentation moved to `archive/legacy_docs/`

---

**Last Updated**: 2026-01-16  
**System Version**: 5.0 (Gateway + ib_insync + systemd timers)
