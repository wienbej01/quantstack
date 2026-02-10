# Documentation Index

## System Documentation

### Core Guides
- [System Guide](SYSTEM_GUIDE.md) - **START HERE** - Complete system overview
- [Trade Database](TRADE_DATABASE.md) - Schema, architecture, and usage
- [Trade Recording](TRADE_RECORDING.md) - Fill and trade recording system
- [Market Open Health Check](MARKET_OPEN_HEALTH_CHECK.md) - Automated 09:40 ET system verification
- [Automated Ops Checks](OPS_AUTOMATED_CHECKS.md) - Schedule 4x 30-minute check/fix runs
- [L2 Scalping System Design](L2_SCALPING_SYSTEM_DESIGN.md) - Architecture and strategy
- [L2 VWAP System](L2_VWAP_SYSTEM.md) - VWAP mean reversion with L2 filter
- [IBKR Connection Protocol](IBKR_IB_INSYNC_CONNECTION_PROTOCOL.md) - Connection management
- [Post-Outage Recovery](POST_OUTAGE_RECOVERY.md) - Emergency procedures
- [Timezone Guide](TIMEZONE_GUIDE.md) - Timezone handling across systems

## Active Trading Systems

| System | Service | Purpose | Schedule (ET) | Status |
|--------|---------|---------|---------------|--------|
| **L2 Scalping** | `l2-scalping.service` | OBI momentum + L2 data collection | 09:26-17:01 | ✅ Running |
| **L2 VWAP Reversion** | `l2-vwap-reversion.service` | VWAP mean reversion with L2 filter | 09:20-16:05 | ✅ Installed |
| Intraday Paper | `intraday-paper.service` | Paper trading with bracket orders | 09:27-17:02 | ⏸️ Disabled |
| SIP Generation | `intraday-sip.timer` | Daily universe selection | 09:10 | ✅ Enabled |
| Emergency EOD | `emergency-eod-close.timer` | Force close positions | 15:55 | ✅ Enabled |

## Recent Investigations

### Jan 30, 2026: Market Open Health Check Added ✅
- **Feature**: Automated system verification at 09:40 ET (10 min after market open)
- **Checks**: SIP, IB Gateway, all trading services, L2 data, trading activity, trade recording
- **Notifications**: NTFY alerts to `jacobw-trading-alerts` topic
- **Status**: ✅ Operational - See [Market Open Health Check](MARKET_OPEN_HEALTH_CHECK.md)

### Jan 30, 2026: Trade Recording System Fixed ✅
- **Issue**: L2 scalping (3,591 fills, 0 trades) and intraday (incorrect exit prices)
- **Fix**: Added trade recording to L2 fill handler, fixed intraday EOD exit prices
- **Status**: ✅ Complete - See [Trade Recording Guide](TRADE_RECORDING.md)
- **Archive**: [2026-01-30 Trade Recording Fix](archive/2026-01-30-trade-recording-fix/)

**Summary**: 
- **L2 Scalping**: Fixed `_legacy_fill_handler()` to call `record_trade_entry()` and `record_trade_exit()`
- **Intraday**: Fixed EOD force close to query fills table for actual exit prices
- **Validation**: Added nightly validation with NTFY alerts
- **Historical**: Jan 29 intraday data corrected ($0 → -$373 P&L), L2 data gap documented

### Jan 27, 2026: Critical Incident (L2 Scalping + Intraday Paper)
- [Error Report](ERROR_REPORT_2026-01-27.md) - Root causes, failures, remediation status
 - [Change Log](CHANGELOG.md) - Daily record of fixes and verification runs

**Summary**: Journal failures, exit order breakdown, and EOD flatten gaps; remediation
in progress with fill-based exits, market entries, and emergency close hardening.

### Jan 24, 2026: L2 VWAP Reversion System
- [L2 VWAP Reversion README](../l2_vwap_reversion/README.md) - New paper trading strategy
- [Strategy Design](../l2_vwap_reversion/docs/STRATEGY_DESIGN.md) - Full strategy specification

**Summary**: New VWAP mean reversion strategy using L2 depth filter from l2-scalping data.
- Entry: Long when close <= VWAP * 0.995 + L2 ratio >= 1.165
- Entry: Short when close >= VWAP * 1.005 + L2 ratio <= 0.858
- Expected: 67.5% win rate, 15.32 expectancy
- Bracket orders with SL/TP, EOD flatten at 15:55 ET
- PostgreSQL trade database + NTFY notifications + audit logging

### Jan 23-24, 2026: Zero-Fill Issue Resolution
- [IOC Fill Simulation Results](IOC_FILL_SIMULATION_RESULTS.md) - L2-Scalping order fill analysis
- [Intraday-Paper Forensic Audit](INTRADAY_PAPER_FORENSIC_AUDIT.md) - Complete system audit

**Summary**: Fixed two critical bugs preventing trading:
1. **L2-Scalping**: Bracket orders had invalid price precision (5-6 decimals) → Fixed with `round_to_tick_size()`
2. **Intraday-Paper**: Timestamp parsing failure + overly aggressive signal age limit → Fixed with `dateutil.parser.parse()` and revised age validation

**Result**: 85.9% of L2-Scalping IOC orders would have filled. Intraday-Paper now accepts valid same-day signals.

## Tools & Scripts

### Analysis Tools
- `/home/jacobw/quantstack/scripts/simulate_order_fills.py` - IOC order fill simulator with L2 data
- `/home/jacobw/quantstack/scripts/audit_intraday_paper.py` - End-to-end system audit tool

### Reconciliation & Reporting
- `/home/jacobw/quantstack/scripts/reconcile_trades.py` - **Trade-by-trade reconciliation** (TradeDB vs Audit Log vs IBKR) - See [TRADE_RECONCILIATION.md](TRADE_RECONCILIATION.md)
- `/home/jacobw/quantstack/scripts/eod_report.py` - **Unified end-of-day performance report** (see [EOD_REPORT.md](EOD_REPORT.md))

### Operational Scripts
- `/home/jacobw/quantstack/scripts/clear_ibkr_depth_subscriptions.py` - Cleanup zombie subscriptions

## Archive

Historical investigations and temporary files are stored in `/home/jacobw/quantstack/archive/` organized by date.

---

**Last Updated**: 2026-02-06

---

## Quick Reference

### Service Installation Status

| Service | Installed | Enabled | Running | Status |
|---------|-----------|---------|---------|--------|
| l2-scalping | ✅ | ✅ | ✅ | ✅ Trade recording fixed |
| l2-vwap-reversion | ✅ | ✅ | ⏳ | Awaiting market open |
| intraday-paper | ✅ | ❌ | ❌ | ✅ Exit prices fixed |
| intraday-sip | ✅ | ✅ | ✅ | ✅ Operational |
| emergency-eod-close | ✅ | ✅ | ✅ | ✅ Operational |

### Validation & Monitoring

| Component | Status | Schedule |
|-----------|--------|----------|
| Trade recording validation | ✅ Active | Daily 1:00 AM |
| NTFY alerts | ✅ Configured | On validation failure |
| Database functions | ✅ Installed | On-demand |

### Next Actions

1. **Test Fixes in Paper Trading** (Monday market open)
   - Verify L2 trades are recorded
   - Verify intraday exit prices are correct
   - Check NTFY notifications

2. **Monitor Validation**
   ```bash
   tail -f ~/quantstack/logs/validation.log
   ```
