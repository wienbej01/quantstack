# L2 Trading Systems Investigation Plan
## Jan 30, 2026 - Abnormally Low Trade Volume

---

## Problem Statement

**L2 Scalping:**
- Normal volume: 100-1000+ trades/day
- Jan 30 volume: ~4 trades (99% reduction)
- Status: CRITICAL ANOMALY

**L2 VWAP Reversion:**
- Normal volume: 10-100+ trades/day
- Jan 30 volume: 0 trades
- Status: COMPLETE FAILURE

---

## Investigation Phases

### Phase 1: Service Health Check (5 min)

#### 1.1 Check Service Status on Jan 30
```bash
# Check if services were running
journalctl -u l2-scalping.service --since "2026-01-30 09:00" --until "2026-01-30 17:00" | grep -i "started\|stopped\|failed\|killed"
journalctl -u l2-vwap-reversion.service --since "2026-01-30 09:00" --until "2026-01-30 17:00" | grep -i "started\|stopped\|failed\|killed"

# Check for crashes/restarts
journalctl -u l2-scalping.service --since "2026-01-30" | grep -i "exit\|signal\|core\|segfault"
journalctl -u l2-vwap-reversion.service --since "2026-01-30" | grep -i "exit\|signal\|core\|segfault"

# Check memory/CPU issues
journalctl -u l2-scalping.service --since "2026-01-30" | grep -i "memory\|oom\|killed"
journalctl -u l2-vwap-reversion.service --since "2026-01-30" | grep -i "memory\|oom\|killed"
```

**Expected:** Services running continuously 9:30-16:00 ET
**Red flags:** Restarts, OOM kills, crashes

#### 1.2 Check Current Service Status
```bash
systemctl status l2-scalping.service
systemctl status l2-vwap-reversion.service
systemctl status l2-collector.service
systemctl status l2-health-monitor.service
```

**Expected:** All active (running)
**Red flags:** Failed, inactive, or degraded state

---

### Phase 2: Trade Volume Analysis (10 min)

#### 2.1 Historical Baseline
```bash
# Get trade counts for past 10 days
psql trading << 'EOF'
SELECT 
    entry_time::date as date,
    system,
    COUNT(*) as trades,
    SUM(net_pnl) as total_pnl
FROM trades 
WHERE entry_time >= '2026-01-20' 
    AND system IN ('l2-scalping', 'l2-vwap-reversion')
GROUP BY entry_time::date, system
ORDER BY date DESC, system;
EOF
```

**Expected:** L2 scalping 100-1000/day, L2 VWAP 10-100/day
**Red flags:** Sudden drop on Jan 30

#### 2.2 Jan 30 Trade Details
```bash
# Get all L2 trades on Jan 30
psql trading << 'EOF'
SELECT 
    system,
    symbol,
    entry_time,
    exit_time,
    entry_price,
    exit_price,
    net_pnl,
    exit_reason
FROM trades 
WHERE entry_time::date = '2026-01-30'
    AND system IN ('l2-scalping', 'l2-vwap-reversion')
ORDER BY entry_time;
EOF
```

**Expected:** Hundreds of L2 scalping trades
**Red flags:** Only 4 trades, all same symbol, clustered timing

#### 2.3 Signal Generation Check
```bash
# Check if signals were generated but not executed
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "signal\|opportunity\|candidate" | wc -l
journalctl -u l2-vwap-reversion.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "signal\|opportunity\|candidate" | wc -l
```

**Expected:** Thousands of signal evaluations
**Red flags:** Zero or very few signals generated

---

### Phase 3: API & Connectivity Analysis (15 min)

#### 3.1 IBKR Connection Status
```bash
# Check for disconnections
grep -i "disconnect\|connection lost\|not connected" /home/jacobw/api-exported-logs.txt | grep "2026-01-30"

# Check for API errors
grep -i "error\|failed\|rejected" /home/jacobw/api-exported-logs.txt | grep "2026-01-30" | head -50

# Check for throttling
grep -i "pacing\|throttle\|rate limit" /home/jacobw/api-exported-logs.txt | grep "2026-01-30"
```

**Expected:** Stable connection, no errors
**Red flags:** Disconnections during market hours, throttling messages

#### 3.2 Order Submission Analysis
```bash
# Count order submissions on Jan 30
grep "L2_SCALPING\|L2_VWAP" /home/jacobw/api-exported-logs.txt | grep "2026-01-30" | grep -c "placeOrder"

# Check for order rejections
grep "L2_SCALPING\|L2_VWAP" /home/jacobw/api-exported-logs.txt | grep "2026-01-30" | grep -i "reject\|cancel\|error"
```

**Expected:** Hundreds of order submissions
**Red flags:** Very few orders, many rejections

#### 3.3 Market Data Flow
```bash
# Check if L2 data was flowing
ls -lh ~/l2_data/date=2026-01-30/
du -sh ~/l2_data/date=2026-01-30/

# Check collector logs
journalctl -u l2-collector.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "collected\|snapshot\|update" | tail -20
```

**Expected:** ~6.5 hours of L2 data, multiple GB
**Red flags:** Empty directory, small files, no data collection

---

### Phase 4: Code Analysis (30 min)

#### 4.1 Check for Recent Code Changes
```bash
# Check git history around Jan 30
cd ~/l2_scalping
git log --since="2026-01-25" --until="2026-01-31" --oneline

cd ~/l2_vwap_reversion
git log --since="2026-01-25" --until="2026-01-31" --oneline
```

**Expected:** No changes or only minor fixes
**Red flags:** Major logic changes, refactoring, new features

#### 4.2 Check Configuration Changes
```bash
# Check systemd service files
ls -l /etc/systemd/system/l2-*.service
stat /etc/systemd/system/l2-scalping.service
stat /etc/systemd/system/l2-vwap-reversion.service

# Check config files
ls -l ~/l2_scalping/config/
ls -l ~/l2_vwap_reversion/config/
```

**Expected:** No recent modifications
**Red flags:** Config changes on Jan 29-30

#### 4.3 Review Entry Logic
```bash
# L2 Scalping - check for blocking conditions
cd ~/l2_scalping
grep -n "def.*should_enter\|def.*can_trade\|def.*is_valid" scripts/*.py src/**/*.py

# L2 VWAP - check for blocking conditions
cd ~/l2_vwap_reversion
grep -n "def.*should_enter\|def.*can_trade\|def.*is_valid" scripts/*.py src/**/*.py
```

**Look for:**
- New validation checks that might be too strict
- Risk limits that might be too conservative
- Disabled features or commented code

#### 4.4 Check for Infinite Loops / Deadlocks
```bash
# Check for stuck processes
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "timeout\|stuck\|waiting\|blocked"

# Check for repeated error messages (infinite loop indicator)
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 10:00" | sort | uniq -c | sort -rn | head -20
```

**Expected:** Normal log flow
**Red flags:** Same message repeated thousands of times, timeout errors

---

### Phase 5: Performance Bottlenecks (20 min)

#### 5.1 Check Processing Speed
```bash
# Look for slow operations
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "slow\|latency\|took.*ms\|elapsed"

# Check for database slowness
journalctl -u l2-scalping.service --since "2026-01-30" | grep -i "query\|database\|postgres" | grep -i "slow\|timeout"
```

**Expected:** Sub-millisecond processing
**Red flags:** Multi-second delays, database timeouts

#### 5.2 Check Resource Usage
```bash
# Check if system was under load
journalctl --since "2026-01-30 09:00" --until "2026-01-30 17:00" | grep -i "load average\|cpu\|memory"

# Check disk I/O
journalctl --since "2026-01-30 09:00" --until "2026-01-30 17:00" | grep -i "disk\|i/o\|write"
```

**Expected:** Normal system load
**Red flags:** High CPU, memory pressure, disk saturation

#### 5.3 Check for Data Processing Lag
```bash
# Check if L2 data processing fell behind
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "lag\|behind\|backlog\|queue"
```

**Expected:** Real-time processing
**Red flags:** Growing lag, backlog warnings

---

### Phase 6: Logic Flaw Analysis (30 min)

#### 6.1 Check Risk Limits
```bash
# Check if risk limits were hit immediately
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 10:00" | grep -i "risk\|limit\|max.*position\|daily.*loss"

# Check position limits
journalctl -u l2-scalping.service --since "2026-01-30" | grep -i "max.*concurrent\|position.*limit"
```

**Expected:** Normal risk management
**Red flags:** "Risk limit reached" at 9:31 AM, max positions = 0

#### 6.2 Check Market Conditions Filter
```bash
# Check if market was deemed untradeable
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "market.*condition\|volatility\|spread\|liquidity"

# Check for "no opportunities" messages
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 16:00" | grep -i "no.*opportunity\|no.*signal\|no.*candidate"
```

**Expected:** Normal market conditions
**Red flags:** "Market conditions unfavorable" for entire day

#### 6.3 Check Symbol Universe
```bash
# Check if symbol list was empty
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 10:00" | grep -i "symbol\|universe\|watchlist"

# Check L2 VWAP specifically
journalctl -u l2-vwap-reversion.service --since "2026-01-30 09:30" --until "2026-01-30 10:00" | grep -i "symbol\|universe\|watchlist"
```

**Expected:** 50-200 symbols in universe
**Red flags:** "No symbols to trade", empty universe

#### 6.4 Check Time/Date Logic
```bash
# Check if system thought it was a holiday
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 10:00" | grep -i "holiday\|closed\|not.*trading.*day"

# Check timezone issues
journalctl -u l2-scalping.service --since "2026-01-30 09:30" --until "2026-01-30 10:00" | grep -i "time\|zone\|market.*hours"
```

**Expected:** Normal trading day
**Red flags:** "Market closed", timezone errors

---

### Phase 7: Comparative Analysis (15 min)

#### 7.1 Compare Jan 29 vs Jan 30
```bash
# Trade counts
psql trading -c "SELECT entry_time::date, system, COUNT(*) FROM trades WHERE entry_time::date IN ('2026-01-29', '2026-01-30') AND system LIKE 'l2-%' GROUP BY 1,2 ORDER BY 1,2;"

# Service uptime
journalctl -u l2-scalping.service --since "2026-01-29 09:00" --until "2026-01-29 17:00" | grep -c "INFO"
journalctl -u l2-scalping.service --since "2026-01-30 09:00" --until "2026-01-30 17:00" | grep -c "INFO"
```

**Expected:** Similar log volume and trade counts
**Red flags:** 100x difference in activity

#### 7.2 Check Other Systems
```bash
# Did intraday-paper work normally?
psql trading -c "SELECT COUNT(*) FROM trades WHERE entry_time::date = '2026-01-30' AND system = 'intraday-paper';"

# This tells us if it's L2-specific or system-wide
```

**Expected:** Intraday worked (5 trades confirmed)
**Conclusion:** Issue is L2-specific, not system-wide

---

## Investigation Checklist

### Critical Questions to Answer

- [ ] Were L2 services running continuously on Jan 30?
- [ ] Was IBKR connection stable during market hours?
- [ ] Was L2 market data flowing normally?
- [ ] Were signals being generated?
- [ ] Were orders being submitted?
- [ ] Were orders being rejected?
- [ ] Did risk limits block trading?
- [ ] Was symbol universe empty?
- [ ] Were there code changes before Jan 30?
- [ ] Were there config changes before Jan 30?
- [ ] Was system under resource pressure?
- [ ] Were there logic errors in entry conditions?

### Expected Findings

**Most Likely Causes (in order):**
1. **Risk limits hit immediately** - Daily loss limit or position limit set too low
2. **Symbol universe empty** - Configuration error or data source issue
3. **Market data not flowing** - L2 collector failed or data source down
4. **IBKR connection issue** - Disconnected or throttled during market hours
5. **Code bug introduced** - Recent change broke entry logic
6. **Configuration error** - Service disabled or wrong parameters

**Least Likely:**
- Hardware failure (other systems worked)
- Market holiday (intraday-paper traded)
- Timezone issue (would affect all systems)

---

## Next Steps After Investigation

### If Service Failure
1. Check systemd logs for crash reason
2. Review memory/CPU limits
3. Add monitoring alerts

### If Code Bug
1. Review recent commits
2. Add unit tests for entry logic
3. Deploy fix and test

### If Configuration Error
1. Review config files
2. Document correct settings
3. Add validation checks

### If Risk Limits
1. Review limit settings
2. Adjust if too conservative
3. Add logging for limit hits

### If Market Data Issue
1. Check L2 collector health
2. Verify data source connectivity
3. Add data flow monitoring

---

## Automation Script

Create investigation script:
```bash
#!/bin/bash
# l2_investigation.sh - Automated L2 trading investigation

DATE="2026-01-30"
REPORT="/home/jacobw/quantstack/reports/l2_investigation_${DATE}.txt"

echo "L2 Trading Investigation - $DATE" > $REPORT
echo "======================================" >> $REPORT
echo "" >> $REPORT

# Service status
echo "=== SERVICE STATUS ===" >> $REPORT
systemctl status l2-scalping.service | head -20 >> $REPORT
systemctl status l2-vwap-reversion.service | head -20 >> $REPORT
echo "" >> $REPORT

# Trade counts
echo "=== TRADE COUNTS ===" >> $REPORT
psql trading -c "SELECT entry_time::date, system, COUNT(*) FROM trades WHERE entry_time >= '$DATE' AND system LIKE 'l2-%' GROUP BY 1,2;" >> $REPORT
echo "" >> $REPORT

# Service logs (first 100 lines)
echo "=== L2 SCALPING LOGS (first 100 lines) ===" >> $REPORT
journalctl -u l2-scalping.service --since "$DATE 09:30" --until "$DATE 16:00" | head -100 >> $REPORT
echo "" >> $REPORT

# Error summary
echo "=== ERROR SUMMARY ===" >> $REPORT
journalctl -u l2-scalping.service --since "$DATE" | grep -i "error\|fail\|exception" | head -50 >> $REPORT
echo "" >> $REPORT

echo "Report saved to: $REPORT"
```

Run with: `bash l2_investigation.sh`
