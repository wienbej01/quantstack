# Operations Runbook

> Consolidated from: PRE_MARKET_CHECKLIST, MARKET_OPEN_HEALTH_CHECK, OPS_AUTOMATED_CHECKS, EOD_REPORT, TIMEZONE_GUIDE, POST_OUTAGE_RECOVERY, L2_HEALTH_MONITOR, TRADE_RECONCILIATION
>
> Last updated: 2026-02-10

---

## Daily Schedule (ET)

| Time (ET) | Manila | What |
|-----------|--------|------|
| 09:10 | 22:10 | SIP universe generation |
| 09:20 | 22:20 | L2 Collector starts |
| 09:28 | 22:28 | Trading services start (l2-scalping, l2-vwap, intraday-paper) |
| 09:30 | 22:30 | Market open |
| 09:40 | 22:40 | Automated health check fires |
| 10:00+ | 23:00+ | Ops checks every 30 min (4 rounds) |
| 15:55 | 04:55+1 | EOD flatten triggers |
| 16:00 | 05:00+1 | Market close |
| 16:05 | 05:05+1 | Services stop |
| 17:05 | 06:05+1 | EOD report runs |

---

## 1. Pre-Market (Before 09:28 ET)

### IBKR Gateway
```bash
ss -ltn | grep :7494                    # Verify listening
python3 scripts/preflight_check.py      # Full preflight probe
```

### Database
```bash
psql -d trading -U jacobw -c "SELECT 1"
```

### Services & Timers
```bash
systemctl list-timers | grep -E "l2-|intraday-"
systemctl list-units --state=failed
```

### WAL Directory
```bash
ls -ld ~/quantstack/logs/wal/
```

---

## 2. Market Open Monitoring (09:28–09:45 ET)

### Watch Logs
```bash
journalctl -u l2-scalping.service -f
journalctl -u l2-vwap-reversion.service -f
```

### Automated Health Check (09:40 ET)
Script: `scripts/market_open_health_check.py`
Timer: `market-open-health-check.timer`

Checks: SIP generation, IB Gateway, all 3 trading services, L2 data storage, trading activity, trade recording. Sends NTFY alert to `jacobw-trading-alerts`.

```bash
# Manual run
python3 scripts/market_open_health_check.py

# View last run
journalctl -u market-open-health-check.service -n 50
```

### Ops Auto-Checks (30/60/90/120 min after open)
Script: `scripts/ops_check_and_fix.sh`

Checks Gateway, all services (auto-restarts if down), DB activity, WAL growth. Sends NTFY summary.

```bash
# Schedule
scripts/schedule_ops_checks.sh

# Manual single run
scripts/ops_check_and_fix.sh 0

# Check timers
systemctl --user list-timers --all | grep ops-check
```

---

## 3. L2 Health Monitor

Script: `scripts/l2_health_monitor.py`
Service: `l2-health-monitor.service`

Detects: Error 309 (max depth subscriptions), Error 326 (client ID conflict), data flow issues.
Auto-recovery: stops service → clears zombie subscriptions → restarts. Max 3 attempts, 5-min cooldown.

```bash
systemctl status l2-health-monitor
journalctl -u l2-health-monitor --since "1 hour ago" | grep -E "UNHEALTHY|Recovery"
```

---

## 4. EOD Report

Script: `scripts/eod_report.py`

```bash
python3 scripts/eod_report.py                          # Today
python3 scripts/eod_report.py --date 2026-02-09        # Specific date
python3 scripts/eod_report.py --date 2026-02-09 --csv report.csv
```

Sections: executive summary, performance by system/strategy/symbol/direction, exit reason analysis, risk metrics, signal vs execution slippage, trade details.

---

## 5. Trade Reconciliation

Script: `scripts/reconcile_trades.py`

Cross-references TradeDB (PostgreSQL), audit logs (`logs/audit/`), and IBKR API logs (`~/IBKRlogs/YYYYMMDD/`).

```bash
python3 scripts/reconcile_trades.py --date 2026-02-09
```

Checks per trade: entry/exit qty match, price match (±$0.01), PnL match (±$1.00), audit event coverage. Outputs JSON to `logs/reconciliation/`.

Run daily after market close.

---

## 6. Outage Recovery

When IBKR Gateway crashes or services fail during market hours:

```bash
# 1. Check Gateway
ss -ltn | grep 7494

# 2. If down: restart Gateway manually (GUI/IBC)

# 3. Clear zombie depth subscriptions
python3 scripts/clear_ibkr_depth_subscriptions.py

# 4. Restart services
sudo systemctl restart l2-collector l2-scalping intraday-paper
systemctl --user restart l2-vwap-reversion

# 5. Verify data flow
journalctl -u l2-scalping -f   # Look for "Fresh: 3/3"
```

Common issues:
- **Error 309**: Max depth subscriptions → clear zombies first
- **Error 326**: Client ID conflict → check no duplicate processes
- **Gateway auto-logoff**: IBKR daily logoff kills connections → restart Gateway
- **False positive health**: "Data: True" but no L2 flow → check fresh snapshots

---

## 7. Timezone Reference

System timezone: Manila (UTC+8). All trading services run with `TZ=America/New_York`.

| Manila Time | ET Time | Event |
|-------------|---------|-------|
| 22:30 | 09:30 | Market open |
| 05:00+1 | 16:00 | Market close |

```bash
# Check service TZ
systemctl cat l2-scalping | grep TZ
# Should show: TZ=America/New_York
```

---

## 8. NTFY Alert Topics

| Topic | Used by |
|-------|---------|
| `jacobw-trading-alerts` | Health checks, trade notifications, ops checks |
| `jacobw-trading-status` | Emergency alerts (exit failures, margin breaches, CPU spikes) |

---

## 9. Emergency Contacts & Rollback

```bash
# Stop everything
sudo systemctl stop l2-scalping l2-vwap-reversion intraday-paper l2-collector

# Revert code changes
cd ~/quantstack && git stash   # or git checkout <file>

# Restart
sudo systemctl daemon-reload
sudo systemctl start l2-collector l2-scalping
```
