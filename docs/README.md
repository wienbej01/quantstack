# Quantstack Trading System — Documentation

> Last updated: 2026-02-10

## Quick Start

```bash
# Check all services
systemctl list-timers | grep -E "l2-|intraday-"
systemctl list-units --state=failed

# Watch live trading
journalctl -u l2-scalping.service -f
journalctl -u l2-vwap-reversion.service -f

# EOD report
python3 scripts/eod_report.py

# Pre-flight check
python3 scripts/preflight_check.py
```

## Active Trading Systems

| System | Service | Schedule (ET) | Strategy |
|--------|---------|---------------|----------|
| L2 Scalping | `l2-scalping.service` | 09:28–16:05 | OBI momentum + pattern rules |
| L2 VWAP Reversion | `l2-vwap-reversion.service` | 09:28–16:05 | VWAP mean reversion + L2 depth |
| Intraday Paper | `intraday-paper.service` | 09:28–16:05 | ML regime-aware (paper only) |
| L2 Collector | `l2-collector.service` | 09:20–16:10 | L2 data collection |

All services share one IBKR paper account via IB Gateway on port 7494.

## Documentation Map

| Document | What it covers |
|----------|---------------|
| [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md) | Complete system reference — architecture, config, services, daily procedures |
| [OPERATIONS.md](OPERATIONS.md) | Daily ops runbook — pre-market, health checks, monitoring, EOD, recovery |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | IBKR connection protocol, Trade DB schema, audit logging |
| [L2_SCALPING_SYSTEM_DESIGN.md](L2_SCALPING_SYSTEM_DESIGN.md) | L2 scalping strategy spec — signals, execution, risk management |
| [L2_VWAP_SYSTEM.md](L2_VWAP_SYSTEM.md) | VWAP reversion strategy spec — entry/exit logic, bracket orders |
| [INCIDENT_LOG.md](INCIDENT_LOG.md) | Chronological incident history and post-mortems |
| [CHANGELOG.md](CHANGELOG.md) | Daily change log |
| [SPRINT_FEB9_INCIDENT_FIX.md](SPRINT_FEB9_INCIDENT_FIX.md) | Active sprint — margin breach & CPU spike fixes |

## Key File Locations

| What | Where |
|------|-------|
| L2 scalping source | `l2_scalping/src/main.py` |
| L2 VWAP source | `l2_vwap_reversion/src/main.py` |
| Shared modules | `cpapi/` (margin_check, emergency_alerts, shared_positions, trade_database) |
| IBKR broker layer | `qx-broker/src/qx_broker/ibkr/` |
| Config files | `l2_scalping/config/`, `l2_vwap_reversion/config/` |
| Trade DB schema | `cpapi/schema.sql` |
| Systemd services | `/etc/systemd/system/l2-*.service` |
| Logs | `l2_scalping/logs/`, `l2_vwap_reversion/logs/`, `logs/audit/` |
| Tests | `tests/test_feb9_incident_fixes.py` (75 tests) |

## Recent Changes (Feb 2026)

- **Feb 9 incident fix** (P0–P3): Exit retry circuit breaker, margin checks, shared position ledger, CPU spike alerting, EOD flatten hardening — see [SPRINT_FEB9_INCIDENT_FIX.md](SPRINT_FEB9_INCIDENT_FIX.md)
- **Feb 6**: Systemd standardization, data flow audit, fill callback fixes
- **Feb 4**: Trade DB v2 remediation, position blocking fix
- **Feb 3**: Trade reconciliation system, L2-VWAP fix plan

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   IBKR Gateway (:7494)              │
├──────────┬──────────┬──────────┬────────────────────┤
│ L2       │ L2 VWAP  │ Intraday │ L2 Collector       │
│ Scalping │ Reversion│ Paper    │                    │
├──────────┴──────────┴──────────┴────────────────────┤
│ Shared: MarginChecker │ ExitGuard │ SharedPositions  │
│         EmergencyAlerts │ TradeDB │ AuditLogger      │
├─────────────────────────────────────────────────────┤
│ PostgreSQL (trading DB) │ NTFY Alerts │ Vitals Monitor│
└─────────────────────────────────────────────────────┘
```
