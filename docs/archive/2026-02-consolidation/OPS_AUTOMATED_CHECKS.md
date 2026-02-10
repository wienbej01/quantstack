# Automated Ops Checks (4x / 30m)

This repo includes a lightweight “ops check + safe auto-fix” runner intended for market-hours monitoring.

## What It Does

Each run checks:
- IBKR Gateway is listening on `127.0.0.1:7494`
- `l2-scalping.service` is active and `l2_scalping/src/main.py` is running (restarts if down)
- `intraday-paper.service` is active and `paper_trade.py` is running (restarts if down)
- `l2-vwap-reversion.service` (user scope) is active and `l2_vwap_reversion/src/main.py` is running (restarts if down)
- DB activity via `psql` (today’s `trades` and last 15 minutes of `executions`)
- Fill WAL growth (`logs/wal/fills_YYYYMMDD.jsonl`) using a per-run baseline state file

Each run sends a best-effort NTFY message to `jacobw-trading-alerts`.

## Schedule 4 Runs (30m/60m/90m/120m)

Preferred: transient user timers via `systemd-run`:

```bash
/home/jacobw/quantstack/scripts/schedule_ops_checks.sh
```

To confirm they’re scheduled:

```bash
systemctl --user list-timers --all | rg 'ops-check-'
```

To cancel:

```bash
systemctl --user stop ops-check-30m.timer ops-check-60m.timer ops-check-90m.timer ops-check-120m.timer
systemctl --user disable ops-check-30m.timer ops-check-60m.timer ops-check-90m.timer ops-check-120m.timer
```

## Manual Run (Single Round)

```bash
/home/jacobw/quantstack/scripts/ops_check_and_fix.sh 0
```

## Files

- Runner: `/home/jacobw/quantstack/scripts/ops_check_and_fix.sh`
- Scheduler: `/home/jacobw/quantstack/scripts/schedule_ops_checks.sh`

