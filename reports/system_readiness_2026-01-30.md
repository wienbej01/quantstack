# System Readiness Report
**Generated**: 2026-01-30 21:27 PST (08:27 EST)  
**Market Open**: 2026-01-31 09:30 EST (25.1 hours)  
**Status**: ⚠️ PARTIAL READINESS - Critical Issues Found

---

## Executive Summary

| Component | Status | Notes |
|-----------|--------|-------|
| **Overall Readiness** | ⚠️ 70% | IB Gateway API not accessible, SIP timer missing |
| **Critical Blockers** | 2 | IB Gateway API, SIP generation |
| **Warnings** | 3 | Intraday disabled, audit table missing, collation mismatch |
| **Ready** | 5 | Database, NTFY, L2 data, validation, L2 VWAP |

---

## 🔴 CRITICAL ISSUES (Must Fix Before Market Open)

### 1. IB Gateway API Not Accessible ⚠️ BLOCKER
**Status**: ❌ CRITICAL  
**Impact**: L2 scalping cannot place orders

**Details**:
- IB Gateway process is running (PID 1420688)
- Paper trading port 7494 accepts connections
- BUT: L2 scalping shows "Not connected" errors
- Last error: 2026-01-30 08:27:20 - "Order placement error: Not connected"

**Root Cause**:
- L2 scalping service running for 20+ hours
- Connection may have dropped during off-hours
- Service needs restart to reconnect

**Fix Required**:
```bash
systemctl --user restart l2-scalping.service
```

**Verification**:
```bash
# Check logs for successful connection
tail -f ~/quantstack/l2_scalping/logs/scalping_system.log | grep -i "connected"
```

---

### 2. SIP Generation Not Scheduled ⚠️ BLOCKER
**Status**: ❌ CRITICAL  
**Impact**: No trading universe for Monday

**Details**:
- Latest SIP data: 2026-01-29 (Jan 29)
- No SIP generation timer found in systemd
- No cron job for SIP generation
- Script exists: `/home/jacobw/intraday_stack/scripts/generate_daily_sip_universe.py`

**Current SIP Symbols** (Jan 29):
```
JOBY, SLV, NOW, FCX, TSCO, INTC, LVS
```

**Fix Required**:
Create systemd timer or cron job:

**Option 1: Systemd Timer** (Recommended)
```bash
# Create timer file
cat > ~/.config/systemd/user/intraday-sip.timer << 'EOF'
[Unit]
Description=Generate Daily SIP Universe

[Timer]
OnCalendar=Mon-Fri 22:10:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Create service file
cat > ~/.config/systemd/user/intraday-sip.service << 'EOF'
[Unit]
Description=Generate Daily SIP Universe

[Service]
Type=oneshot
WorkingDirectory=/home/jacobw/intraday_stack
ExecStart=/home/jacobw/intraday_stack/.venv/bin/python scripts/generate_daily_sip_universe.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

# Enable and start
systemctl --user daemon-reload
systemctl --user enable intraday-sip.timer
systemctl --user start intraday-sip.timer
```

**Option 2: Cron Job**
```bash
# Add to crontab (runs at 9:10 PM ET = 22:10 Manila)
(crontab -l 2>/dev/null; echo "10 22 * * 1-5 cd /home/jacobw/intraday_stack && .venv/bin/python scripts/generate_daily_sip_universe.py >> logs/sip_generation.log 2>&1") | crontab -
```

**Verification**:
```bash
# Check timer
systemctl --user list-timers intraday-sip.timer

# Or check cron
crontab -l | grep sip
```

---

## ⚠️ WARNINGS (Should Fix)

### 3. Intraday Paper Trading Disabled
**Status**: ⚠️ WARNING  
**Impact**: Intraday system won't trade

**Details**:
- Service: Loaded but disabled
- Timer: Exists but not enabled
- Schedule: Mon-Fri 09:25 ET (5 min before market open)

**Current State**:
```
○ intraday-paper.service - inactive (dead)
  Timer: loaded but not enabled
```

**Fix** (if you want intraday to trade):
```bash
systemctl --user enable intraday-paper.timer
systemctl --user start intraday-paper.timer
```

**Note**: Based on context, this may be intentionally disabled. Confirm before enabling.

---

### 4. Audit Log Table Missing
**Status**: ⚠️ WARNING  
**Impact**: No audit trail for trades

**Details**:
- Database query for `audit_log` table fails
- Audit log files exist: `~/quantstack/logs/audit/audit_2026-01-30.log`
- File-based audit working, database audit not configured

**Current Audit**:
- ✅ File-based: 376KB today
- ❌ Database: Table doesn't exist

**Fix** (if needed):
```sql
-- Create audit_log table
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    system TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_system ON audit_log(system);
```

**Note**: File-based audit is working. Database audit is optional enhancement.

---

### 5. Database Collation Mismatch
**Status**: ⚠️ INFO  
**Impact**: None (cosmetic warning)

**Details**:
```
WARNING: database "trading" has a collation version mismatch
Database: 2.41, OS: 2.42
```

**Fix** (optional):
```sql
ALTER DATABASE trading REFRESH COLLATION VERSION;
```

**Note**: This is a cosmetic warning. Database functions normally.

---

## ✅ READY COMPONENTS

### 6. Database ✅
**Status**: ✅ OPERATIONAL

**Details**:
- PostgreSQL: Connected
- Tables: `trades`, `fills` exist
- Validation functions: Installed
- Recent activity: 376KB audit logs today

**Test**:
```bash
psql -d trading -U jacobw -c "SELECT COUNT(*) FROM trades WHERE entry_time::date >= CURRENT_DATE - INTERVAL '7 days';"
```

---

### 7. NTFY Notifications ✅
**Status**: ✅ OPERATIONAL

**Details**:
- Service: ntfy.sh reachable
- Topic: quantstack_alerts
- Test: Successful connection

**Test**:
```bash
curl -d "Test notification" ntfy.sh/quantstack_alerts
```

---

### 8. L2 Data Collection ✅
**Status**: ✅ OPERATIONAL

**Details**:
- Latest data: 2026-01-30 (today)
- Location: `~/quantstack/data/l2/l2_maximum/features/`
- Size: Current and historical data available

**Data Available**:
```
date=2026-01-29: 4.0K
date=2026-01-30: 4.0K
```

---

### 9. Trade Recording Validation ✅
**Status**: ✅ OPERATIONAL

**Details**:
- Script: `validate_trade_recording.py`
- Schedule: Daily 1:00 AM (cron)
- NTFY alerts: Configured
- Last run: Detected expected historical issues

**Validation Results**:
```
⚠️ Orphaned fills: Historical (expected)
⚠️ Zero-slippage exits: Historical (expected)
✅ L2 recording: No activity today
```

**Note**: Warnings are from pre-fix data (expected to age out in 7 days)

---

### 10. L2 VWAP Reversion ✅
**Status**: ✅ READY

**Details**:
- Service: Installed and configured
- Timer: Enabled, next run 22:20 PST (09:20 ET)
- Last run: 2026-01-30 10:03 (44s duration, clean exit)
- IB Gateway: Will connect on paper port 7494

**Schedule**:
```
Next: Fri 2026-01-30 22:20:00 PST (56 min)
      = Sat 2026-01-31 09:20:00 ET
```

**Note**: Runs 10 minutes before market open (9:30 ET)

---

## 📊 SERVICE STATUS MATRIX

| Service | Installed | Enabled | Running | Schedule (ET) | Status |
|---------|-----------|---------|---------|---------------|--------|
| **l2-scalping** | ✅ | ❌ | ✅ | Manual | ⚠️ Connection issue |
| **l2-vwap-reversion** | ✅ | ✅ | ⏸️ | 09:20 | ✅ Ready |
| **intraday-paper** | ✅ | ❌ | ❌ | 09:25 | ⚠️ Disabled |
| **intraday-sip** | ❌ | ❌ | ❌ | 09:10 | ❌ Missing |
| **emergency-eod** | ❓ | ❓ | ❓ | 15:55 | ❓ Not found |
| **validation** | ✅ | ✅ | ⏸️ | 01:00 | ✅ Cron |

---

## 🔧 PRE-MARKET CHECKLIST

### Before 9:00 AM ET (22:00 PST Tonight)

- [ ] **Fix SIP Generation** (CRITICAL)
  - Create systemd timer or cron job
  - Test: Run manually to generate tomorrow's universe
  - Verify: Check `~/intraday_stack/data/daily_sip/date=2026-01-31/`

- [ ] **Restart L2 Scalping** (CRITICAL)
  - `systemctl --user restart l2-scalping.service`
  - Verify: Check logs for "Connected" message
  - Test: Verify IB Gateway connection

- [ ] **Verify IB Gateway** (CRITICAL)
  - Ensure IB Gateway is running
  - Confirm paper trading port 7494 is accessible
  - Test connection from Python

### Before 9:20 AM ET (22:20 PST Tonight)

- [ ] **L2 VWAP Timer Check**
  - Verify timer will fire: `systemctl --user list-timers l2-vwap-reversion.timer`
  - Expected: Next run at 22:20 PST (09:20 ET)

### Before 9:30 AM ET (Market Open)

- [ ] **Monitor Service Startup**
  - L2 VWAP should start at 09:20 ET
  - Intraday (if enabled) should start at 09:25 ET
  - L2 Scalping should already be running

- [ ] **Check Logs**
  - L2 Scalping: `tail -f ~/quantstack/l2_scalping/logs/scalping_system.log`
  - L2 VWAP: `tail -f ~/quantstack/l2_vwap_reversion/logs/vwap_reversion_*.log`
  - Intraday: `tail -f ~/intraday_stack/logs/paper_trade.log`

---

## 📈 EXPECTED BEHAVIOR AT MARKET OPEN

### 9:20 AM ET
- L2 VWAP service starts
- Connects to IB Gateway (paper port 7494)
- Loads SIP symbols
- Begins monitoring VWAP signals

### 9:25 AM ET
- Intraday Paper starts (if enabled)
- Connects to IB Gateway
- Loads SIP symbols
- Prepares for market open

### 9:30 AM ET (Market Open)
- L2 Scalping begins trading (already running)
- L2 VWAP begins trading
- Intraday begins trading (if enabled)
- All systems record fills and trades to database
- NTFY notifications sent on trade entries/exits

---

## 🔍 MONITORING COMMANDS

### Real-time Monitoring
```bash
# Watch all trading logs
tail -f ~/quantstack/l2_scalping/logs/scalping_system.log \
        ~/quantstack/l2_vwap_reversion/logs/vwap_reversion_*.log \
        ~/intraday_stack/logs/paper_trade.log

# Watch database activity
watch -n 5 'psql -d trading -U jacobw -c "SELECT system, COUNT(*) as trades FROM trades WHERE entry_time::date = CURRENT_DATE GROUP BY system;"'

# Watch service status
watch -n 10 'systemctl --user status l2-scalping l2-vwap-reversion intraday-paper | grep -E "Active:|Main PID:"'
```

### Post-Market Verification
```bash
# Run validation
python3 ~/quantstack/scripts/validate_trade_recording.py

# Check trade counts
psql -d trading -U jacobw -c "
SELECT 
    system,
    COUNT(*) as trades,
    SUM(gross_pnl) as total_pnl
FROM trades 
WHERE entry_time::date = CURRENT_DATE 
GROUP BY system;"

# Generate EOD report
python3 ~/quantstack/scripts/eod_report.py
```

---

## 🎯 RISK ASSESSMENT

### High Risk
1. **SIP Generation Missing** - No trading universe for Monday
2. **L2 Scalping Connection** - Cannot place orders

### Medium Risk
3. **Intraday Disabled** - System won't trade (may be intentional)

### Low Risk
4. **Audit Table Missing** - File-based audit working
5. **Collation Mismatch** - Cosmetic warning only

---

## ✅ RECOMMENDATION

**IMMEDIATE ACTIONS REQUIRED** (Before 22:00 PST Tonight):

1. **Create SIP generation timer** (15 minutes)
2. **Restart L2 scalping service** (2 minutes)
3. **Test IB Gateway connectivity** (5 minutes)
4. **Verify L2 VWAP timer** (2 minutes)

**TOTAL TIME**: ~25 minutes

**DECISION POINT**: Enable intraday-paper?
- If YES: `systemctl --user enable --now intraday-paper.timer`
- If NO: Leave disabled (current state)

---

## 📞 SUPPORT

**If Issues Arise**:
1. Check logs: `~/quantstack/*/logs/`
2. Check service status: `systemctl --user status <service>`
3. Check database: `psql -d trading -U jacobw`
4. Check NTFY: `curl ntfy.sh/quantstack_alerts`

**Emergency Stop**:
```bash
systemctl --user stop l2-scalping l2-vwap-reversion intraday-paper
```

---

**Report Generated**: 2026-01-30 21:27:32 PST  
**Next Update**: After fixes applied  
**Market Open**: 2026-01-31 09:30:00 EST (25.1 hours)
