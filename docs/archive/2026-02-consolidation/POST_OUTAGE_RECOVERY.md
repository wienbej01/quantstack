# Post-Outage Recovery Runbook

## Quick Recovery Checklist

When IBKR Gateway crashes or services fail during market hours:

```bash
# 1. Check Gateway status
ss -ltn | grep 7494

# 2. If Gateway is down, restart it manually
# (Gateway must be started via GUI or IBC - no systemd service)

# 3. Clear zombie depth subscriptions BEFORE restarting services
python ~/quantstack/scripts/clear_ibkr_depth_subscriptions.py

# 4. Restart all trading services
sudo systemctl restart l2-collector l2-scalping intraday-paper

# 5. Verify services are running with data
journalctl -u l2-scalping -f --since "1 minute ago"
# Look for: "Fresh: 3/3" (all symbols have data)
# NOT just: "Data: True" (connection only)
```

## Root Causes from Jan 19 Incident

### Issue 1: Gateway Down for 6 Hours
- Gateway was not running from 09:20 ET to 15:11 ET
- Services with `Requires=ibkr-gateway-ready` kept failing
- **Fix**: Changed to `Wants=` (soft dependency) - services now start and retry internally

### Issue 2: IBKR Auto-Logoff at 10:45 ET
- IBKR Gateway has scheduled daily logoff (even with `dailyAutoRestartEnabled=false`)
- This kills all connections and depth subscriptions
- **Fix**: Configure Gateway auto-restart, or monitor for logoff and restart services

### Issue 3: Error 309 - Max Depth Subscriptions
- IBKR limits to 3 concurrent market depth subscriptions per account
- Zombie subscriptions from crashed sessions consume the limit
- **Fix**: Run `clear_ibkr_depth_subscriptions.py` before restarting services

### Issue 4: False Positive Health Checks
- Health check reported "Data: True" but no actual L2 data was flowing
- Only 2/3 symbols had depth data = 0 signals generated
- **Fix**: Health check now validates fresh snapshots, not just connection

## Detailed Recovery Steps

### Step 1: Verify Gateway is Running

```bash
# Check if Gateway is listening
ss -ltn | grep 7494

# If not listening, Gateway needs manual restart
# Option A: Via VNC/GUI
# Option B: Via IBC (if configured)
```

### Step 2: Accept Paper Trading Disclaimer

After Gateway restart, you may need to accept the paper trading disclaimer:
- Connect via VNC to the Gateway GUI
- Accept any popup dialogs
- Verify API connections are allowed in Gateway settings

### Step 3: Clear Zombie Subscriptions

```bash
# This prevents Error 309 (max depth limit)
cd ~/quantstack
python scripts/clear_ibkr_depth_subscriptions.py
```

### Step 4: Restart Services

```bash
# Restart all L2 services
sudo systemctl restart l2-collector l2-scalping

# Restart paper trading
sudo systemctl restart intraday-paper
```

### Step 5: Verify Data Flow

```bash
# Watch l2-scalping logs
journalctl -u l2-scalping -f

# Look for:
# ✅ "Subscribed to SYMBOL" for all symbols
# ✅ "Fresh: 3/3" in health checks
# ✅ Signal generation messages

# Red flags:
# ❌ "Error 309: Max number of market depth requests"
# ❌ "Fresh: 0/3" or "Data: False"
# ❌ No signal generation after 5+ minutes
```

## Prevention Measures

### 1. Gateway Monitoring
Add to preflight check:
```bash
# Check Gateway is up before market open
ss -ltn | grep -q 7494 || echo "ALERT: Gateway not running!"
```

### 2. IBKR Auto-Restart
Configure Gateway for auto-restart after daily logoff:
- Gateway Settings → Lock and Exit → Enable "Auto restart"
- Set restart time to before market open (e.g., 04:00 ET)

### 3. Service Recovery
Services now have soft dependencies and internal retry logic.
If Gateway comes up mid-day, services will reconnect automatically.

## Emergency Contacts

- IBKR Gateway issues: Check IBKR status page
- System issues: Check journalctl logs
- NTFY alerts: jacobw-trading-alerts channel
