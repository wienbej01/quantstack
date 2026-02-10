# Market Open Health Check

**Purpose**: Automated verification that all trading systems are operational 10 minutes after market open.

**Schedule**: Mon-Fri 09:40 AM ET (10 minutes after market open)

---

## What It Checks

### 1. SIP Generation ✅
- Daily SIP universe file exists for today
- File is recent (< 2 hours old)
- File contains valid symbols

### 2. IB Gateway ✅
- Connection to paper trading port (7494)
- API is responsive (timeout treated as warning, not failure)

### 3. Trading Services ✅
- **L2 Scalping**: Running
- **L2 VWAP**: Running  
- **Intraday Paper**: Running (or not started if before 09:28)

### 4. L2 Data Storage ✅
- Raw L2 data directory exists for today
- Features directory exists for today
- Recent files written (last 5 minutes)

### 5. Trading Activity ✅
- Systems have executed trades today
- Checks trades table (not fills)
- Or: It's early (< 09:35 ET) and no trades yet is OK

### 6. Trade Recording ✅
- Trades are being recorded in database
- Fills-to-trades ratio is reasonable

---

## Notifications

### All Systems Healthy ✅
```
Title: ✅ Trading Systems Healthy
Priority: default
Tags: white_check_mark, chart_with_upwards_trend
Topic: jacobw-trading-alerts

Market Open Health Check (09:40 ET)

🟢 ALL SYSTEMS OPERATIONAL

SIP Generation: ✅ 5 symbols: SLV, VZ, UNG
IB Gateway: ✅ Connected
L2 Scalping: ✅ Running
L2 VWAP: ✅ Running
Intraday Paper: ✅ Running
L2 Data Storage: ✅ 102 recent files
Trading Activity: ✅ 15 trades today
Trade Recording: ✅ l2-scalping: 8, l2-vwap: 2
```

### System Issues ⚠️
```
Title: ⚠️ Trading System Issues (2 failed)
Priority: high
Tags: warning, rotating_light
Topic: jacobw-trading-alerts

Market Open Health Check (09:40 ET)

🔴 2 SYSTEM(S) FAILED

❌ L2 VWAP: Status: inactive
❌ Trading Activity: No trades since market open

Passed:
✅ SIP Generation: ✅ 5 symbols: SLV, VZ, UNG
✅ IB Gateway: ✅ Connected
✅ L2 Scalping: ✅ Running
✅ Intraday Paper: ✅ Running
✅ L2 Data Storage: ✅ 102 recent files
✅ Trade Recording: ✅ l2-scalping: 8
```

---

## Files

**Script**: `/home/jacobw/quantstack/scripts/market_open_health_check.py`  
**Service**: `/etc/systemd/system/market-open-health-check.service`  
**Timer**: `/etc/systemd/system/market-open-health-check.timer`

---

## Runtime Notes (Important)

- The service currently runs the script with `/usr/bin/python3`. The script is written to degrade gracefully if optional deps (like `psycopg2`) are not available under that interpreter.
- IBKR connectivity checks use the `qx_broker.ibkr` session stack (same as production services). The probe defaults to `IBKR_GATEWAY_HOST=127.0.0.1`, `IBKR_GATEWAY_PORT=7494`, and `IBKR_HEALTHCHECK_CLIENT_ID=997`, with a small client-id fallback within the utilities range.
- "No trades yet" is not treated as a failure condition. Market-open health is about connectivity + data flow, not guaranteeing signals.
- Trade recording checks should prefer `executions.ibkr_time` for “today/recent” logic. `executions.received_at` is an ingestion timestamp and must be timezone-aware; naive UTC strings will skew “recent activity” windows.
- If `executions.system` shows `unknown`, it usually means order IDs were not linked in `trade_order_links` at order placement time. Health checks should not assume system attribution exists unless that link is in place.

---

## Manual Execution

```bash
# Run check now
python3 /home/jacobw/quantstack/scripts/market_open_health_check.py

# Check timer status
systemctl list-timers | grep market-open

# View last run
journalctl -u market-open-health-check.service -n 50

# Disable (if needed)
sudo systemctl stop market-open-health-check.timer
sudo systemctl disable market-open-health-check.timer
```

---

## Troubleshooting

### Check Failed: What to Do

1. **SIP Generation Failed**
   - Check: `ls ~/intraday_stack/data/daily_sip/date=$(date +%Y-%m-%d)/`
   - Fix: Run manually: `cd ~/intraday_stack && .venv/bin/python scripts/generate_daily_sip_universe.py`

2. **IB Gateway Failed**
   - Check: IB Gateway process running
   - Fix: Restart IB Gateway

3. **Service Not Running**
   - Check: `systemctl status <service>.service`
   - Fix: `systemctl start <service>.service`

4. **No Trading Activity**
   - Check: Market is open and liquid
   - Check: Systems are running
   - Check: Trades are being recorded
   - Note: Checks trades table, not fills table

5. **Trade Recording Failed**
   - Check: Database connection
   - Check: `record_trade_entry()` is being called
   - Run: `python3 ~/quantstack/scripts/validate_trade_recording.py`

---

## Integration

This check complements:
- **Nightly Validation** (01:00 AM) - Checks previous day's data integrity
- **EOD Report** (17:05 ET) - Full day performance summary

Together they provide:
- **Pre-market**: SIP generation (09:10 ET)
- **Market Open**: Health check (09:40 ET) → **jacobw-trading-alerts**
- **Post-market**: EOD report (17:05 ET)
- **Nightly**: Data validation (01:00 AM)

---

## NTFY Topic

**Topic**: `jacobw-trading-alerts`

This is the same topic used by:
- L2 Scalping trade notifications
- L2 VWAP trade notifications  
- Intraday Paper trade notifications
- System health alerts

---

## Exit Codes

- **0**: All checks passed
- **1**: One or more checks failed

---

**Created**: 2026-01-30  
**Last Updated**: 2026-02-06  
**NTFY Topic**: jacobw-trading-alerts  
**Status**: ✅ Operational
