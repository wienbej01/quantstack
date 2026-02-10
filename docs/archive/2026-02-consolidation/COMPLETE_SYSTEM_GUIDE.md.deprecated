# Complete System Guide

Quantstack Trading System - Operations Manual
Version: 5.0 (IBKR Gateway + ib_insync + systemd timers)
Date: 2026-01-16
Status: SYSTEMD TIMERS ENABLED (manual IBKR portal startup/auth)

## Purpose

This guide describes the current production-ready IBKR Gateway + ib_insync system.
It replaces the old CPAPI platform and uses direct socket connections via
`qx-broker` to IBKR Gateway.

## Current Architecture

- IBKR Gateway (TWS/IB Gateway) runs locally and is authenticated in browser UI.
- All services connect through `qx-broker` (ib_insync) to the Gateway.
- IBKR Gateway is started and authenticated manually each day.
- Systemd timers handle SIP, L2, scalping, intraday-paper, monitoring, reporting.
- Services are blocked on `ibkr-gateway-ready.service` (port check at 7494).

## Services and Locations

- IBKR Gateway — location: external app; entry: UI login; notes: port 7494,
  browser auth required
- Preflight check — location: /home/jacobw/quantstack/scripts; entry:
  preflight_check.py; notes: Gateway + Polygon validation
- L2 Collector — location: /home/jacobw/quantstack/qx-l2; entry: l2-collect;
  notes: L2 capture + storage
- L2 Scalping — location: /home/jacobw/quantstack/l2_scalping; entry: src/main.py;
  notes: L2 signals + trading
- Intraday Paper — location: /home/jacobw/intraday_stack; entry:
  scripts/paper_trade.py; notes: paper trading
- Audit wrapper — location: /home/jacobw/quantstack/scripts; entry:
  audit_wrapper.sh; notes: structured logging
- Health monitor — location: /home/jacobw/quantstack; entry:
  system_health_monitor.py; notes: NTFY + platform health
- Watchdog — location: /home/jacobw/quantstack/scripts; entry: l2_watchdog.py;
  notes: L2 auto-recovery
- Reports — location: /home/jacobw/quantstack/scripts; entry:
  daily_trade_report.py; notes: daily trade + fill truth

## Ports and Client ID Ranges

- IBKR Gateway host: 127.0.0.1
- IBKR Gateway port: 7494

Client ID ranges (non-overlapping):
- Preflight: 998 (read-only probe)
- L2 Collector: 1-99 (maximum_l2.yaml uses 1)
- Intraday Paper: 100-199 (data 110, exec 111, system 115)
- L2 Scalping: 200-299 (data 250, orders 200)

## Required Environment

- IBKR Gateway running and authenticated.
- `POLYGON_API_KEY` set for preflight.
- SIP universe file exists for today:
  `/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json`

Optional overrides:
- `IBKR_GATEWAY_HOST` (default 127.0.0.1)
- `IBKR_GATEWAY_PORT` (default 7494)
- `RUN_PREFLIGHT` (default 1)
- `STOP_GRACE_SECONDS` (default 3)

## Daily Startup (Manual Portal + Timers)

1) Start IBKR Gateway/Portal and authenticate in the UI.
   - Log in to paper account.
   - Enable API access ("Enable ActiveX and Socket Clients").
   - Confirm socket port `7494` and trusted IP `127.0.0.1`.
   - Keep the session open for the trading day.
2) Confirm the gateway is listening on 7494:

```bash
ss -ltn | rg ":7494"
```

3) Systemd timers take over (no manual start of services needed).
4) Manual start (debug only; uses audit wrapper and clears old PIDs):

```bash
bash /home/jacobw/quantstack/scripts/start_new_platform_manual.sh
```

Manual logs:

```bash
tail -n 40 /home/jacobw/quantstack/logs/manual/l2_collect.log
tail -n 40 /home/jacobw/quantstack/logs/manual/l2_scalping.log
tail -n 40 /home/jacobw/intraday_stack/logs/paper_trade_manual.log
```

## Systemd Schedule (ET)

- 08:00 - trading-orchestrator
- 09:00 - intraday-sip, preflight-check
- 09:26 - l2-collector start
- 09:26 - l2-scalping start
- 09:28 - intraday-paper start
- 17:00 - l2-collector stop
- 17:01 - l2-scalping stop
- 17:02 - intraday-paper stop
- 17:10 - daily trade reports (trade_report + fill_truth)
- Every 2 minutes during 07:00-16:30 - system-health-monitor

## Systemd Status and Checks

Timers:
```bash
systemctl list-timers --all --no-pager | rg -n \
  "intraday-sip|preflight|trading-orchestrator|l2-collector|l2-scalping|" \
  "intraday-paper|system-health|daily-trade-report"
```

Services:
```bash
systemctl status l2-collector l2-scalping intraday-paper l2-watchdog position-monitor --no-pager
```

Logs:
```bash
journalctl -u l2-collector.service -n 50 --no-pager
journalctl -u l2-scalping.service -n 50 --no-pager
journalctl -u intraday-paper.service -n 50 --no-pager
journalctl -u system-health-monitor.service -n 50 --no-pager
journalctl -u daily-trade-report.service -n 50 --no-pager
```

Manual logs (if running outside systemd):
```bash
tail -n 40 /home/jacobw/quantstack/logs/manual/l2_collect.log
tail -n 40 /home/jacobw/quantstack/logs/manual/l2_scalping.log
tail -n 40 /home/jacobw/intraday_stack/logs/paper_trade_manual.log
```

## Data Storage

L2 collector data:
```
/home/jacobw/quantstack/data/l2_maximum/raw/
  date=YYYY-MM-DD/
    symbol=TICKER/
      *.parquet
```

## Audit Logging

All manual starts are wrapped by `scripts/audit_wrapper.sh`.
Audit logs live in:
```
/home/jacobw/quantstack/logs/audit/
```

Reference:
- `docs/AUDIT_LOGGING.md`
- `docs/AUDIT_QUICK_REF.md`

## L2 Feature/PnL Correlation

L2 scalping now logs per-trade decision features (signal metrics, thresholds, context regime)
into the shared event store for correlation with realized PnL.

Generate the correlation report:
```bash
python3 /home/jacobw/quantstack/scripts/l2_feature_pnl_report.py --date YYYY-MM-DD
```

Outputs:
- `/home/jacobw/quantstack/reports/l2_feature_pnl_dataset_YYYY-MM-DD.csv`
- `/home/jacobw/quantstack/reports/l2_feature_pnl_corr_YYYY-MM-DD.csv`

Notes:
- Correlation requires l2-scalping trades with decision features logged (new runs only).
- Join key is `signal_id` captured at decision time and stored in the trades table.

## Manual Stop (Emergency)

To stop all services (clean shutdown):

```bash
pkill -f "/home/jacobw/quantstack/l2_scalping/src/main.py" || true
pkill -f "/home/jacobw/.local/bin/l2-collect" || true
pkill -f "/home/jacobw/intraday_stack/scripts/paper_trade.py" || true
pkill -f "audit_wrapper.sh l2-collect" || true
pkill -f "audit_wrapper.sh l2-scalping" || true
pkill -f "audit_wrapper.sh intraday-paper" || true
```

To disable timers (emergency pause):

```bash
sudo systemctl stop intraday-sip.timer preflight-check.timer trading-orchestrator.timer \
  l2-collector.timer l2-collector-stop.timer l2-scalping.timer l2-scalping-stop.timer \
  intraday-paper.timer intraday-paper-stop.timer system-health-monitor.timer \
  daily-trade-report.timer
```

## Systemd Status (Current)

Systemd timers are enabled for all services. The IBKR Gateway/Portal is started
and authenticated manually each day. Legacy platform services are disabled:
- ibkr-platform.service
- ibkr-gateway.service
- ibkr-gateway-startup.service
- gateway-manager.service

## Troubleshooting

- Preflight shows "IBKR disconnected" but then passes:
  - OK. The probe disconnects after validation.

- "Gateway authenticated" fails:
  - Ensure Gateway is logged in and API access is enabled.
  - Confirm correct port (7494) in Gateway settings.

- Polygon check fails:
  - Ensure `POLYGON_API_KEY` is set and DNS/network is working.

- Intraday paper log permission errors:
  - Ensure `/home/jacobw/intraday_stack/logs` is writable.
  - Script will fall back to `/home/jacobw/quantstack/logs/manual` if needed.

- Duplicate IBKR client IDs:
  - Run the manual start script to clear old processes.
  - If Gateway shows stale clients, restart the Gateway UI.

## References

- Connection protocol: `docs/IBKR_IB_INSYNC_CONNECTION_PROTOCOL.md`
- Audit logging: `docs/AUDIT_LOGGING.md`
- Sprint plan: `new_master_sprint_plan.md`
